import json
import os
import shutil
import subprocess
from pathlib import Path
from urllib.request import Request, urlopen

from tasks.a2a_agent_utils import begin_agent_session, publish_agent_output
from tasks.privileged_control import (
    append_privileged_audit_event,
    build_privileged_policy,
    path_allowed,
    redact_sensitive_text,
)
from tasks.utils import OUTPUT_DIR, llm, log_task_update, normalize_llm_text, resolve_output_path, write_text_file


RESPONSES_API_URL = "https://api.openai.com/v1/responses"
DEFAULT_CODEX_MODEL = os.getenv("OPENAI_MODEL_CODING", os.getenv("OPENAI_CODEX_MODEL", "gpt-5.3-codex"))
DEFAULT_REASONING_EFFORT = os.getenv("OPENAI_CODEX_REASONING_EFFORT", "medium")

AGENT_METADATA = {
    "coding_agent": {
        "description": "Generates production-ready code artifacts and can write the result to a target file path.",
        "skills": ["coding", "implementation", "code generation"],
        "input_keys": [
            "coding_task",
            "coding_working_directory",
            "coding_context_files",
            "coding_write_path",
            "coding_language",
            "coding_instructions",
        ],
        "output_keys": [
            "coding_summary",
            "coding_language",
            "coding_code",
            "coding_written_path",
            "coding_backend_used",
        ],
        "requirements": ["openai_or_codex_cli"],
        "display_name": "Coding Agent",
        "category": "development",
        "intent_patterns": [
            "write code", "implement function", "generate code", "create class",
            "write a script", "code this", "build a module", "write a component",
        ],
        "active_when": [],
        "config_hint": "",
    },
    "master_coding_agent": {
        "description": "Long-running coding project orchestrator that produces detailed project plans and delegates implementation/setup work to specialist agents.",
        "skills": ["project architecture", "coding orchestration", "delegation", "delivery planning"],
        "input_keys": [
            "master_coding_request",
            "coding_task",
            "coding_working_directory",
            "coding_context_files",
            "coding_write_path",
            "coding_instructions",
        ],
        "output_keys": [
            "master_coding_summary",
            "master_coding_plan",
            "master_coding_delegation",
            "master_coding_next_agent",
        ],
        "requirements": ["openai_or_codex_cli"],
    },
}


def _read_context_files(file_paths: list[str], working_directory: Path) -> tuple[str, list[str]]:
    sections = []
    missing_files = []

    for raw_path in file_paths:
        path = Path(raw_path)
        if not path.is_absolute():
            path = working_directory / path

        if not path.exists():
            missing_files.append(str(path))
            continue

        sections.append(f"File: {path}\n---\n{path.read_text(encoding='utf-8')}\n---")

    return "\n\n".join(sections), missing_files


def _build_coding_prompt(
    task: str,
    language: str,
    extra_instructions: str,
    target_write_path: str | None,
    context_blob: str,
    missing_files: list[str],
) -> str:
    write_instruction = (
        f"Return the full replacement file contents for this path: {target_write_path}."
        if target_write_path
        else "Return the code artifact directly. Do not assume any file write unless told."
    )
    missing_context = "\n".join(missing_files) if missing_files else "None"

    return f"""
You are the coding agent in a multi-agent ecosystem.

Write production-ready code for the requested task. Keep non-code text minimal.
{write_instruction}
Do not wrap the code in markdown fences.

Return EXACTLY in this format:
SUMMARY: one-line summary
LANGUAGE: {language or "best-fit"}
CODE:
full code here

Task:
{task}

Additional instructions:
{extra_instructions or "None"}

Missing context files:
{missing_context}

Relevant context:
{context_blob or "No file context provided."}
""".strip()


def _extract_output_text(payload: dict) -> str:
    if payload.get("output_text"):
        return payload["output_text"]

    chunks = []
    for item in payload.get("output", []):
        for content in item.get("content", []):
            if content.get("type") in {"output_text", "text"} and content.get("text"):
                chunks.append(content["text"])
    return "\n".join(chunks).strip()


def _parse_coding_response(raw_output: str) -> tuple[str, str, str]:
    summary = "Generated code."
    language = "text"
    code = raw_output.strip()

    if "CODE:" not in raw_output:
        return summary, language, _strip_code_fences(code)

    code_lines = []
    in_code = False

    for line in raw_output.splitlines():
        if in_code:
            code_lines.append(line)
            continue

        if line.startswith("SUMMARY:"):
            summary = line.split(":", 1)[1].strip() or summary
        elif line.startswith("LANGUAGE:"):
            language = line.split(":", 1)[1].strip() or language
        elif line.startswith("CODE:"):
            in_code = True
            remainder = line.split(":", 1)[1].lstrip()
            if remainder:
                code_lines.append(remainder)

    code = "\n".join(code_lines).strip()
    return summary, language, _strip_code_fences(code)


def _strip_code_fences(code: str) -> str:
    stripped = normalize_llm_text(code).strip()
    if stripped.startswith("```") and stripped.endswith("```"):
        inner = stripped.splitlines()
        if len(inner) >= 2:
            return "\n".join(inner[1:-1]).strip()
    return stripped


def _strip_json_fences(text: str) -> str:
    cleaned = normalize_llm_text(text).strip()
    if cleaned.startswith("```") and cleaned.endswith("```"):
        lines = cleaned.splitlines()
        if len(lines) >= 2:
            return "\n".join(lines[1:-1]).strip()
    return cleaned


def _build_master_coding_prompt(
    objective: str,
    working_directory: Path,
    context_files: list[str],
    context_blob: str,
    missing_files: list[str],
    available_agents: list[str],
    setup_summary: str,
    setup_actions: list[dict],
) -> str:
    return f"""
You are master_coding_agent in a multi-agent runtime.

Your job:
- Build a complete, detailed project plan for the coding objective.
- If implementation is needed, delegate to specialist agents.
- If components, tools, or dependencies must be installed/configured, delegate that setup work to other agents instead of pretending it is already done.

Current objective:
{objective}

Working directory:
{working_directory}

Available agents:
{json.dumps(available_agents, ensure_ascii=False)}

Current setup summary:
{setup_summary or "None"}

Available setup actions:
{json.dumps(setup_actions, ensure_ascii=False)}

Context files requested:
{json.dumps(context_files, ensure_ascii=False)}

Missing context files:
{json.dumps(missing_files, ensure_ascii=False)}

Context content:
{context_blob or "No file context provided."}

Decision rules:
- Prefer `coding_agent` for concrete file/code generation.
- Prefer `os_agent` when installs/system setup are needed.
- Prefer `agent_factory_agent` only if an entirely new capability/agent is required.
- Use `worker_agent` for fallback explanation when another required delegate is unavailable.
- Choose `finish` only if the final response is complete and no further delegation is needed.

Return ONLY valid JSON using this exact schema:
{{
  "summary": "short summary",
  "project_plan": {{
    "goal": "one-line goal",
    "architecture": ["key design decision"],
    "phases": [
      {{
        "name": "phase name",
        "tasks": ["task 1", "task 2"],
        "deliverables": ["deliverable 1"],
        "acceptance_criteria": ["criterion 1"]
      }}
    ],
    "required_components": [
      {{
        "name": "component/tool/library",
        "status": "present|missing|unknown",
        "purpose": "why needed",
        "install_hint": "command or setup step"
      }}
    ],
    "quality_gates": ["tests, lint, docs, verification gates"],
    "risk_controls": ["major risk and mitigation"]
  }},
  "delegation": {{
    "next_agent": "coding_agent|os_agent|agent_factory_agent|worker_agent|reviewer_agent|finish",
    "reason": "why this next agent",
    "task_content": "clear task for the next agent",
    "state_updates": {{
      "key": "value"
    }}
  }},
  "final_response": "detailed user-facing response; include architecture, plan, components, and execution details"
}}
""".strip()


def _parse_master_coding_output(raw_output: str) -> dict:
    cleaned = _strip_json_fences(raw_output)
    parsed = json.loads(cleaned)
    if not isinstance(parsed, dict):
        raise ValueError("master_coding_agent output must be a JSON object.")
    return parsed


def _project_plan_markdown(summary: str, objective: str, project_plan: dict, delegation: dict) -> str:
    phases = project_plan.get("phases", []) if isinstance(project_plan, dict) else []
    components = project_plan.get("required_components", []) if isinstance(project_plan, dict) else []
    lines = [
        "# Master Coding Plan",
        "",
        f"Objective: {objective}",
        "",
        f"Summary: {summary}",
        "",
        "## Phases",
    ]
    if phases:
        for index, phase in enumerate(phases, start=1):
            lines.append(f"{index}. {phase.get('name', 'Unnamed phase')}")
            tasks = phase.get("tasks", []) if isinstance(phase, dict) else []
            deliverables = phase.get("deliverables", []) if isinstance(phase, dict) else []
            acceptance = phase.get("acceptance_criteria", []) if isinstance(phase, dict) else []
            if tasks:
                lines.append(f"Tasks: {', '.join(str(item) for item in tasks)}")
            if deliverables:
                lines.append(f"Deliverables: {', '.join(str(item) for item in deliverables)}")
            if acceptance:
                lines.append(f"Acceptance: {', '.join(str(item) for item in acceptance)}")
            lines.append("")
    else:
        lines.extend(["- none", ""])

    lines.append("## Required Components")
    if components:
        for item in components:
            lines.append(
                f"- {item.get('name', 'component')} | status={item.get('status', 'unknown')} | purpose={item.get('purpose', '')}"
            )
    else:
        lines.append("- none")
    lines.extend(
        [
            "",
            "## Delegation",
            f"Next agent: {delegation.get('next_agent', 'finish')}",
            f"Reason: {delegation.get('reason', '')}",
            f"Task: {delegation.get('task_content', '')}",
        ]
    )
    return "\n".join(lines).strip()


def _call_codex_cli(prompt: str, model: str, working_directory: Path, timeout_seconds: int) -> str:
    temp_output_path = Path(resolve_output_path("coding_agent_codex_cli_last_message.txt"))
    command = [
        "codex",
        "exec",
        "--skip-git-repo-check",
        "--sandbox",
        "read-only",
        "--cd",
        str(working_directory),
        "--output-last-message",
        str(temp_output_path),
        "-m",
        model,
        prompt,
    ]
    completed = subprocess.run(
        command,
        capture_output=True,
        text=True,
        timeout=timeout_seconds,
        check=False,
    )
    if completed.returncode != 0:
        raise RuntimeError(completed.stderr.strip() or completed.stdout.strip() or "codex exec failed")
    return temp_output_path.read_text(encoding="utf-8").strip()


def _call_openai_sdk(prompt: str, model: str, reasoning_effort: str, api_key: str) -> str:
    from openai import OpenAI

    client = OpenAI(api_key=api_key)
    response = client.responses.create(
        model=model,
        input=prompt,
        reasoning={"effort": reasoning_effort},
    )
    raw_text = getattr(response, "output_text", None)
    if raw_text:
        return raw_text.strip()
    return _extract_output_text(response.model_dump())


def _call_responses_http(prompt: str, model: str, reasoning_effort: str, api_key: str, timeout_seconds: int) -> str:
    request_body = json.dumps(
        {
            "model": model,
            "input": prompt,
            "reasoning": {"effort": reasoning_effort},
        }
    ).encode("utf-8")
    request = Request(
        RESPONSES_API_URL,
        data=request_body,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    with urlopen(request, timeout=timeout_seconds) as response:
        payload = json.loads(response.read().decode("utf-8"))
    return _extract_output_text(payload)


def _resolve_backend(preferred_backend: str, api_key: str | None) -> list[str]:
    if preferred_backend != "auto":
        return [preferred_backend]

    backends = []
    if shutil.which("codex"):
        backends.append("codex-cli")
    if api_key:
        backends.extend(["openai-sdk", "responses-http"])
    return backends


def coding_agent(state):
    active_task, task_content, _ = begin_agent_session(state, "coding_agent")
    state["coding_agent_calls"] = state.get("coding_agent_calls", 0) + 1
    call_number = state["coding_agent_calls"]

    task = state.get("coding_task") or task_content or state.get("current_objective") or state.get("user_query", "").strip()
    if not task:
        raise ValueError("coding_agent requires 'coding_task' or 'user_query' in state.")

    working_directory = Path(state.get("coding_working_directory", ".")).resolve()
    target_write_path = state.get("coding_write_path")
    context_files = state.get("coding_context_files", [])
    language = state.get("coding_language", "best-fit")
    extra_instructions = state.get("coding_instructions", "")
    preferred_backend = state.get("coding_backend", "auto")
    model = state.get("coding_model", DEFAULT_CODEX_MODEL)
    reasoning_effort = state.get("coding_reasoning_effort", DEFAULT_REASONING_EFFORT)
    timeout_seconds = int(state.get("coding_timeout", 90))
    api_key = os.getenv("OPENAI_API_KEY")
    privileged_policy = build_privileged_policy(state)

    log_task_update("Coding Agent", f"Generation pass #{call_number} started.")
    log_task_update(
        "Coding Agent",
        f"Preparing coding prompt with backend preference '{preferred_backend}' and model '{model}'.",
        task,
    )

    context_blob, missing_files = _read_context_files(context_files, working_directory)
    prompt = _build_coding_prompt(
        task=task,
        language=language,
        extra_instructions=extra_instructions,
        target_write_path=target_write_path,
        context_blob=context_blob,
        missing_files=missing_files,
    )

    raw_filename = f"coding_agent_raw_{call_number}.txt"
    code_filename = f"coding_agent_code_{call_number}.txt"
    report_filename = f"coding_agent_output_{call_number}.txt"
    report_json_filename = f"coding_agent_output_{call_number}.json"

    backend_errors = []
    raw_output = ""
    backend_used = None

    for backend in _resolve_backend(preferred_backend, api_key):
        try:
            if backend == "codex-cli":
                raw_output = _call_codex_cli(prompt, model, working_directory, timeout_seconds)
            elif backend == "openai-sdk":
                raw_output = _call_openai_sdk(prompt, model, reasoning_effort, api_key or "")
            elif backend == "responses-http":
                raw_output = _call_responses_http(prompt, model, reasoning_effort, api_key or "", timeout_seconds)
            else:
                raise ValueError(f"Unsupported coding backend: {backend}")
            backend_used = backend
            break
        except Exception as exc:
            backend_errors.append(f"{backend}: {exc}")

    if not backend_used:
        error_report = (
            "coding_agent could not generate code.\n"
            "Configure OPENAI_API_KEY or install the Codex CLI (`codex`) on PATH.\n"
            + "\n".join(backend_errors)
        ).strip()
        write_text_file(report_filename, error_report)
        raise RuntimeError(error_report)

    summary, detected_language, code = _parse_coding_response(raw_output)
    state["coding_summary"] = summary
    state["coding_language"] = detected_language
    state["coding_code"] = code
    state["coding_model"] = model
    state["coding_backend_used"] = backend_used
    state["coding_raw_output"] = raw_output

    write_text_file(raw_filename, raw_output)
    write_text_file(code_filename, code)

    written_path = None
    if target_write_path:
        written_path = Path(target_write_path)
        if not written_path.is_absolute():
            written_path = working_directory / written_path
        if privileged_policy.get("read_only", False):
            raise PermissionError("coding_agent write blocked: privileged read-only mode is enabled.")
        if not path_allowed(str(written_path), privileged_policy.get("allowed_paths", [])):
            raise PermissionError(f"coding_agent write blocked: target path is outside allowed scope: {written_path}")
        written_path.parent.mkdir(parents=True, exist_ok=True)
        written_path.write_text(code, encoding="utf-8")
        state["coding_written_path"] = str(written_path)
        append_privileged_audit_event(
            state,
            actor="coding_agent",
            action="file_write",
            status="completed",
            detail={
                "path": str(written_path),
                "language": detected_language,
                "summary": redact_sensitive_text(summary),
            },
        )

    report_lines = [
        f"Backend: {backend_used}",
        f"Model: {model}",
        f"Reasoning effort: {reasoning_effort}",
        f"Summary: {summary}",
        f"Language: {detected_language}",
        f"Target write path: {written_path or 'none'}",
        f"Context files: {', '.join(context_files) if context_files else 'none'}",
        f"Missing context files: {', '.join(missing_files) if missing_files else 'none'}",
        "",
        "Generated Code:",
        code,
    ]
    report = "\n".join(report_lines).strip()
    report_payload = {
        "backend": backend_used,
        "model": model,
        "reasoning_effort": reasoning_effort,
        "summary": summary,
        "language": detected_language,
        "target_write_path": str(written_path) if written_path else "",
        "context_files": list(context_files),
        "missing_context_files": list(missing_files),
        "code": code,
    }

    write_text_file(report_filename, report)
    write_text_file(report_json_filename, json.dumps(report_payload, indent=2, ensure_ascii=False))

    state["draft_response"] = report
    log_task_update(
        "Coding Agent",
        f"Code generation finished with backend '{backend_used}'. Saved artifacts to {OUTPUT_DIR}/{report_filename}.",
        report,
    )
    state = publish_agent_output(
        state,
        "coding_agent",
        report,
        f"coding_result_{call_number}",
        recipients=["orchestrator_agent", "worker_agent"],
    )
    return state


def master_coding_agent(state):
    active_task, task_content, _ = begin_agent_session(state, "master_coding_agent")
    state["master_coding_agent_calls"] = state.get("master_coding_agent_calls", 0) + 1
    call_number = state["master_coding_agent_calls"]

    objective = (
        state.get("master_coding_request")
        or state.get("coding_task")
        or task_content
        or state.get("current_objective")
        or state.get("user_query", "")
    ).strip()
    if not objective:
        raise ValueError("master_coding_agent requires a coding objective in state or task content.")

    working_directory = Path(state.get("coding_working_directory", ".")).resolve()
    context_files = state.get("coding_context_files", [])
    available_agents = list(state.get("available_agents", []))
    setup_summary = state.get("setup_summary", "")
    setup_actions = state.get("setup_actions", [])

    log_task_update("Master Coding Agent", f"Planning pass #{call_number} started for long-running coding workflow.")
    context_blob, missing_files = _read_context_files(context_files, working_directory)
    prompt = _build_master_coding_prompt(
        objective=objective,
        working_directory=working_directory,
        context_files=context_files,
        context_blob=context_blob,
        missing_files=missing_files,
        available_agents=available_agents,
        setup_summary=setup_summary,
        setup_actions=setup_actions if isinstance(setup_actions, list) else [],
    )
    response = llm.invoke(prompt)
    raw_output = normalize_llm_text(response.content if hasattr(response, "content") else response)

    try:
        result = _parse_master_coding_output(raw_output)
    except Exception:
        result = {
            "summary": "Built a detailed fallback coding plan and delegated implementation to coding_agent.",
            "project_plan": {
                "goal": objective,
                "architecture": ["Use existing runtime patterns and agent interfaces in this repository."],
                "phases": [
                    {
                        "name": "Scaffold",
                        "tasks": ["Create project skeleton and base configuration."],
                        "deliverables": ["Initial runnable repository layout."],
                        "acceptance_criteria": ["Project boots and base commands run."],
                    },
                    {
                        "name": "Implement",
                        "tasks": ["Build core modules and connect required integrations."],
                        "deliverables": ["Feature-complete implementation."],
                        "acceptance_criteria": ["Primary requirements implemented end-to-end."],
                    },
                    {
                        "name": "Validate",
                        "tasks": ["Add tests, docs, and operational runbook."],
                        "deliverables": ["Test suite and project documentation."],
                        "acceptance_criteria": ["Key paths verified with reproducible commands."],
                    },
                ],
                "required_components": [],
                "quality_gates": ["Unit tests pass", "Smoke test run succeeds", "Docs updated"],
                "risk_controls": ["Capture assumptions early and validate dependencies before implementation."],
            },
            "delegation": {
                "next_agent": "coding_agent",
                "reason": "Fallback path after invalid planner JSON.",
                "task_content": objective,
                "state_updates": {"coding_task": objective},
            },
            "final_response": f"Detailed coding project plan prepared for: {objective}",
        }

    delegation = result.get("delegation", {})
    if not isinstance(delegation, dict):
        delegation = {}
    next_agent = str(delegation.get("next_agent", "coding_agent")).strip() or "coding_agent"
    allowed_next = {"coding_agent", "os_agent", "agent_factory_agent", "worker_agent", "reviewer_agent", "finish"}
    if next_agent not in allowed_next:
        next_agent = "coding_agent"

    if next_agent != "finish" and available_agents and next_agent not in available_agents:
        next_agent = "worker_agent" if "worker_agent" in available_agents else "finish"

    state_updates = delegation.get("state_updates", {})
    if not isinstance(state_updates, dict):
        state_updates = {}
    task_for_next = (
        str(delegation.get("task_content", "")).strip()
        or objective
    )
    reason = str(delegation.get("reason", "")).strip() or "Continue detailed project delivery."

    project_plan = result.get("project_plan", {})
    summary = str(result.get("summary", "Detailed master coding plan prepared.")).strip()
    final_response = str(result.get("final_response", "")).strip() or summary

    state["master_coding_summary"] = summary
    state["master_coding_plan"] = project_plan
    state["master_coding_delegation"] = delegation
    state["master_coding_next_agent"] = next_agent
    state["master_coding_task_content"] = task_for_next
    state["master_coding_state_updates"] = state_updates
    state["master_coding_reason"] = reason
    state["draft_response"] = final_response

    report_payload = {
        "summary": summary,
        "objective": objective,
        "project_plan": project_plan,
        "delegation": {
            "next_agent": next_agent,
            "reason": reason,
            "task_content": task_for_next,
            "state_updates": state_updates,
        },
        "final_response": final_response,
    }
    plan_markdown = _project_plan_markdown(summary, objective, project_plan, report_payload["delegation"])
    write_text_file(f"master_coding_agent_output_{call_number}.txt", json.dumps(report_payload, indent=2, ensure_ascii=False))
    write_text_file(f"master_coding_agent_plan_{call_number}.md", plan_markdown)
    write_text_file(f"master_coding_agent_raw_{call_number}.txt", raw_output)

    log_task_update(
        "Master Coding Agent",
        f"Planning pass #{call_number} finished. Suggested next agent: {next_agent}.",
        final_response,
    )
    recipients = ["orchestrator_agent"]
    if next_agent != "finish":
        recipients.append(next_agent)
    return publish_agent_output(
        state,
        "master_coding_agent",
        final_response,
        f"master_coding_result_{call_number}",
        recipients=recipients,
    )
