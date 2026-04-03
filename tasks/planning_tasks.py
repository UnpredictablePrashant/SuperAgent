import json
from datetime import datetime, timezone
from typing import Any

from kendr.llm_router import provider_status
from tasks.a2a_agent_utils import begin_agent_session, publish_agent_output
from tasks.file_memory import update_planning_file
from tasks.utils import OUTPUT_DIR, llm, log_task_update, logger, model_selection_for_agent, normalize_llm_text, write_text_file


NON_EXECUTABLE_PLAN_AGENTS = {"planner_agent"}


def _planner_provider_snapshot() -> dict[str, str]:
    selection = model_selection_for_agent("planner_agent")
    provider = str(selection.get("provider") or "").strip()
    snapshot = provider_status(provider)
    snapshot["provider"] = provider
    snapshot["model"] = str(selection.get("model") or snapshot.get("model") or "").strip()
    snapshot["model_source"] = str(selection.get("source") or "").strip()
    return snapshot


def _ensure_planner_llm_ready() -> dict[str, str]:
    snapshot = _planner_provider_snapshot()
    if snapshot.get("ready"):
        return snapshot
    provider = str(snapshot.get("provider") or "unknown").strip()
    model = str(snapshot.get("model") or "unknown").strip()
    note = str(snapshot.get("note") or "").strip()
    base_url = str(snapshot.get("base_url") or "").strip()
    parts = [f"Planner preflight failed: provider '{provider}' is not ready for model '{model}'."]
    if note:
        parts.append(note)
    if base_url:
        parts.append(f"Base URL: {base_url}")
    raise RuntimeError(" ".join(parts).strip())


def _planner_error_message(exc: Exception, snapshot: dict[str, str]) -> str:
    provider = str(snapshot.get("provider") or "unknown").strip()
    model = str(snapshot.get("model") or "unknown").strip()
    error_type = type(exc).__name__
    raw_message = str(exc or "").strip()
    lowered = raw_message.lower()
    if "api key" in lowered or "authentication" in lowered or "unauthorized" in lowered:
        guidance = "Check the configured API credentials for the active provider."
    elif "timeout" in lowered:
        guidance = "The provider timed out. Retryable after connectivity stabilizes."
    elif "connection" in lowered or "dns" in lowered or "refused" in lowered:
        guidance = "The provider could not be reached. Check network access, base URL, and provider health."
    else:
        guidance = "Inspect the provider configuration and the execution log for the full stack trace."
    if raw_message:
        return (
            f"Planner failed while calling provider '{provider}' with model '{model}' "
            f"({error_type}): {raw_message}. {guidance}"
        )
    return (
        f"Planner failed while calling provider '{provider}' with model '{model}' "
        f"({error_type}). {guidance}"
    )


def _strip_code_fences(text: str) -> str:
    stripped = normalize_llm_text(text).strip()
    if stripped.startswith("```") and stripped.endswith("```"):
        lines = stripped.splitlines()
        if len(lines) >= 2:
            return "\n".join(lines[1:-1]).strip()
    return stripped


def _as_str_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item).strip() for item in value if str(item).strip()]


def _dedupe_str_list(values: list[str]) -> list[str]:
    seen: set[str] = set()
    ordered: list[str] = []
    for value in values:
        item = str(value).strip()
        if not item or item in seen:
            continue
        seen.add(item)
        ordered.append(item)
    return ordered


def _normalize_step(item: dict[str, Any], objective: str, index: int, parent_id: str = "") -> dict[str, Any]:
    step_id = str(item.get("id") or f"{parent_id}step-{index}").strip() or f"{parent_id}step-{index}"
    title = str(item.get("title") or item.get("name") or step_id).strip() or step_id
    agent = str(item.get("agent") or "worker_agent").strip() or "worker_agent"
    selection = model_selection_for_agent(agent)
    llm_model = str(item.get("llm_model") or selection.get("model", "")).strip() or selection.get("model", "")
    model_source = str(item.get("model_source") or selection.get("source", "")).strip() or selection.get("source", "")

    substeps_raw = item.get("substeps", [])
    substeps = []
    if isinstance(substeps_raw, list):
        for sub_index, substep in enumerate(substeps_raw, start=1):
            if isinstance(substep, dict):
                substeps.append(_normalize_step(substep, objective, sub_index, parent_id=f"{step_id}."))

    return {
        "id": step_id,
        "title": title,
        "agent": agent,
        "task": str(item.get("task") or objective).strip() or objective,
        "depends_on": _as_str_list(item.get("depends_on", [])),
        "parallel_group": str(item.get("parallel_group") or "").strip(),
        "success_criteria": str(item.get("success_criteria") or "").strip(),
        "llm_model": llm_model,
        "model_source": model_source,
        "substeps": substeps,
        "status": str(item.get("status") or "pending"),
        "started_at": item.get("started_at") or None,
        "completed_at": item.get("completed_at") or None,
        "result_summary": item.get("result_summary") or None,
        "error": item.get("error") or None,
    }


def _collect_model_assignments(steps: list[dict[str, Any]], prefix: str = "") -> list[dict[str, str]]:
    assignments: list[dict[str, str]] = []
    for position, step in enumerate(steps, start=1):
        path = f"{prefix}{position}" if prefix else str(position)
        assignments.append(
            {
                "path": path,
                "step_id": str(step.get("id", "")).strip(),
                "title": str(step.get("title", "")).strip(),
                "agent": str(step.get("agent", "")).strip(),
                "llm_model": str(step.get("llm_model", "")).strip(),
                "model_source": str(step.get("model_source", "")).strip(),
            }
        )
        child_steps = step.get("substeps", [])
        if isinstance(child_steps, list) and child_steps:
            assignments.extend(_collect_model_assignments(child_steps, prefix=f"{path}."))
    return assignments


def _collect_execution_steps(steps: list[dict[str, Any]]) -> list[dict[str, Any]]:
    execution_steps: list[dict[str, Any]] = []
    descendant_map: dict[str, list[str]] = {}

    def _expand_dependencies(depends_on: list[str], *, exclude: set[str] | None = None) -> list[str]:
        expanded: list[str] = []
        excluded = exclude or set()
        for dep in depends_on:
            dep_id = str(dep).strip()
            if not dep_id:
                continue
            replacements = descendant_map.get(dep_id)
            if replacements:
                expanded.extend(replacements)
            else:
                expanded.append(dep_id)
        return [item for item in _dedupe_str_list(expanded) if item not in excluded]

    def _should_chain_after_previous(previous_step: dict[str, Any] | None, current_step: dict[str, Any]) -> bool:
        if not previous_step:
            return False
        previous_group = str(previous_step.get("parallel_group") or "").strip()
        current_group = str(current_step.get("parallel_group") or "").strip()
        if previous_group and previous_group == current_group:
            return False
        return True

    def _visit(step: dict[str, Any], inherited_depends: list[str] | None = None) -> list[str]:
        if not isinstance(step, dict):
            return []
        step_id = str(step.get("id") or "").strip()
        agent = str(step.get("agent") or "").strip()
        child_steps = step.get("substeps", [])
        normalized_depends = _dedupe_str_list(_as_str_list(step.get("depends_on", [])) or (inherited_depends or []))

        if isinstance(child_steps, list) and child_steps:
            descendant_ids: list[str] = []
            parent_depends = normalized_depends
            previous_child_leaf_id = ""
            previous_child_step: dict[str, Any] | None = None
            for child in child_steps:
                if not isinstance(child, dict):
                    continue
                child_copy = dict(child)
                child_depends = _as_str_list(child_copy.get("depends_on", []))
                if child_depends:
                    resolved_child_depends: list[str] = []
                    for dep in child_depends:
                        dep_id = str(dep).strip()
                        if dep_id == step_id:
                            resolved_child_depends.extend(parent_depends)
                        else:
                            resolved_child_depends.append(dep_id)
                    child_copy["depends_on"] = _dedupe_str_list(resolved_child_depends)
                else:
                    if previous_child_leaf_id and _should_chain_after_previous(previous_child_step, child_copy):
                        child_copy["depends_on"] = [previous_child_leaf_id]
                    else:
                        child_copy["depends_on"] = list(parent_depends)
                child_descendants = _visit(child_copy, _as_str_list(child_copy.get("depends_on", [])))
                if child_descendants:
                    descendant_ids.extend(child_descendants)
                    previous_child_leaf_id = child_descendants[-1]
                    previous_child_step = child_copy
            if step_id:
                descendant_map[step_id] = descendant_ids
            return descendant_ids

        if agent in NON_EXECUTABLE_PLAN_AGENTS:
            if step_id:
                descendant_map[step_id] = []
            return []

        leaf_step = dict(step)
        leaf_step["depends_on"] = normalized_depends
        leaf_step["substeps"] = []
        execution_steps.append(leaf_step)
        if step_id:
            descendant_map[step_id] = [step_id]
        return [step_id] if step_id else []

    for step in steps:
        if isinstance(step, dict):
            _visit(step)

    for step in execution_steps:
        step_id = str(step.get("id") or "").strip()
        step["depends_on"] = _expand_dependencies(_as_str_list(step.get("depends_on", [])), exclude={step_id})

    return execution_steps


def normalize_plan_data(raw_plan: Any, objective: str) -> dict[str, Any]:
    fallback = {
        "needs_clarification": False,
        "clarification_questions": [],
        "summary": "Build the work in reviewed stages and verify each major milestone before final delivery.",
        "steps": [
            {
                "id": "step-1",
                "title": "Primary execution",
                "agent": "worker_agent",
                "task": objective,
                "depends_on": [],
                "parallel_group": "",
                "success_criteria": "Produce a complete draft that addresses the full objective.",
                "rationale": "Create the main deliverable.",
                "substeps": [],
            },
            {
                "id": "step-2",
                "title": "Quality review",
                "agent": "reviewer_agent",
                "task": "Review the deliverable against the objective and require revisions if needed.",
                "depends_on": ["step-1"],
                "parallel_group": "",
                "success_criteria": "Approve only if the output is complete and accurate.",
                "rationale": "Prevent incomplete final output.",
                "substeps": [],
            },
        ],
    }

    if not isinstance(raw_plan, dict):
        raw_plan = fallback

    raw_steps = raw_plan.get("steps", [])
    if not isinstance(raw_steps, list) or not raw_steps:
        raw_steps = fallback["steps"]

    steps = []
    for index, item in enumerate(raw_steps, start=1):
        if not isinstance(item, dict):
            continue
        steps.append(_normalize_step(item, objective, index))
    if not steps:
        steps = [_normalize_step(item, objective, index) for index, item in enumerate(fallback["steps"], start=1)]

    plan_data = {
        "needs_clarification": bool(raw_plan.get("needs_clarification", False)),
        "clarification_questions": _as_str_list(raw_plan.get("clarification_questions", [])),
        "summary": str(raw_plan.get("summary") or fallback["summary"]).strip() or fallback["summary"],
        "steps": steps,
    }
    execution_steps = _collect_execution_steps(steps)
    if not execution_steps:
        execution_steps = [_normalize_step(fallback["steps"][0], objective, 1)]
    plan_data["execution_steps"] = execution_steps
    plan_data["model_assignments"] = _collect_model_assignments(steps)
    return plan_data


_STATUS_ICON = {
    "pending": "⏳",
    "running": "🔄",
    "completed": "✅",
    "failed": "❌",
    "skipped": "⏭",
}


def _step_markdown_lines(step: dict[str, Any], indent: int = 0, show_status: bool = False) -> list[str]:
    prefix = "  " * indent
    title = str(step.get("title", "")).strip() or str(step.get("id", "")).strip() or "Step"
    agent = str(step.get("agent") or "").strip()
    task_text = str(step.get("task") or "").strip()
    criteria = str(step.get("success_criteria") or "").strip()
    status = str(step.get("status") or "pending")
    icon = _STATUS_ICON.get(status, "⏳")
    step_id = str(step.get("id") or "").strip()
    parallel_group = str(step.get("parallel_group") or "").strip()

    header = f"{prefix}{icon} **{step_id}: {title}**"
    if show_status and status not in ("pending",):
        header += f" [{status}]"
    lines = [header, f"{prefix}  → agent: `{agent}`"]
    if task_text:
        lines.append(f"{prefix}  → task: {task_text}")
    if criteria:
        lines.append(f"{prefix}  → done when: {criteria}")
    if parallel_group:
        lines.append(f"{prefix}  → parallel group: {parallel_group}")
    result_summary = str(step.get("result_summary") or "").strip()
    if result_summary and show_status:
        lines.append(f"{prefix}  → result: {result_summary[:200]}")
    error = str(step.get("error") or "").strip()
    if error and show_status:
        lines.append(f"{prefix}  → error: {error[:200]}")
    child_steps = step.get("substeps", [])
    if isinstance(child_steps, list) and child_steps:
        for child in child_steps:
            if isinstance(child, dict):
                lines.extend(_step_markdown_lines(child, indent=indent + 1, show_status=show_status))
    return lines


def plan_as_markdown(plan_data: dict[str, Any], show_status: bool = False) -> str:
    lines: list[str] = []
    summary = str(plan_data.get("summary") or "").strip()
    if summary:
        lines.append(f"**Summary:** {summary}")
        lines.append("")

    execution_steps = plan_data.get("execution_steps") or plan_data.get("steps", [])
    total = len(execution_steps)
    if show_status:
        completed = sum(1 for s in execution_steps if isinstance(s, dict) and s.get("status") == "completed")
        running = sum(1 for s in execution_steps if isinstance(s, dict) and s.get("status") == "running")
        lines.append(f"**Progress:** {completed}/{total} steps complete" + (f", {running} running" if running else ""))
        lines.append("")

    lines.append(f"**Steps ({total}):**")
    steps_to_display = execution_steps if execution_steps else plan_data.get("steps", [])
    for step in steps_to_display:
        if isinstance(step, dict):
            lines.extend(_step_markdown_lines(step, show_status=show_status))
    return "\n".join(lines).strip()


def build_plan_approval_prompt(plan_md: str, *, scope_title: str, storage_note: str = "") -> str:
    lines = [f"The {scope_title} is ready for approval."]
    if storage_note:
        lines.append(storage_note.strip())
    lines.extend(
        [
            "",
            plan_md.strip(),
            "",
            "Reply `approve` to continue, or describe the changes you want and I will regenerate the plan before execution.",
        ]
    )
    return "\n".join(lines).strip()


def _planning_context(state: dict, objective: str) -> str:
    context = {
        "objective": objective,
        "current_objective": state.get("current_objective", ""),
        "available_agents": state.get("available_agents", []),
        "skill_registry_hints": state.get("plan_agent_hints", []),
        "local_drive_paths": state.get("local_drive_paths", []),
        "local_drive_summary": str(state.get("local_drive_summary", "")).strip()[:6000],
        "long_document_mode": bool(state.get("long_document_mode", False)),
        "long_document_pages": int(state.get("long_document_pages", 0) or 0),
        "superrag_mode": state.get("superrag_mode", ""),
        "superrag_urls": state.get("superrag_urls", []),
        "security_target_url": state.get("security_target_url", ""),
        "repo_scan_summary": str(state.get("repo_scan_summary", "")).strip()[:4000],
        "project_context_md": str(state.get("project_context_md", "")).strip()[:8000],
        "setup_summary": state.get("setup_summary", ""),
        "previous_plan": state.get("plan", ""),
        "revision_feedback": state.get("plan_revision_feedback", ""),
        # Project builder context
        "project_build_mode": bool(state.get("project_build_mode", False)),
        "project_name": state.get("project_name", ""),
        "project_root": state.get("project_root", ""),
        "project_stack": state.get("project_stack", ""),
        "blueprint_json": state.get("blueprint_json", {}),
        "skip_test_agent": bool(state.get("skip_test_agent", False)),
        "skip_devops_agent": bool(state.get("skip_devops_agent", False)),
    }
    return json.dumps(context, indent=2, ensure_ascii=False)


def planner_agent(state):
    _, task_content, _ = begin_agent_session(state, "planner_agent")
    log_task_update("Planner", "Analyzing the request and building a detailed plan for approval.")

    user_query = str(task_content or state.get("current_objective") or state["user_query"]).strip()
    logger.info(f"[Planner] User query: {user_query}")
    provider_snapshot = _ensure_planner_llm_ready()

    prompt = f"""
You are a planning agent in a multi-agent runtime.

Your job is to produce a CONCISE, STRUCTURED execution plan in JSON before work begins.
The user reviews and approves the plan before execution starts.

STEP LIMITS — strictly enforced:
- Standard tasks: 3–6 steps maximum.
- Complex multi-stage tasks (full project build, 50-page reports): up to 10 steps maximum.
- NO substeps unless the parent step genuinely cannot be expressed as a flat step (rare).
- Each step's "task" field: ONE sentence, ≤ 25 words. Be specific, not generic.
- "success_criteria": ONE short phrase describing the observable output (e.g. "Python file with passing tests", "JSON list of 5 competitors"). Not a paragraph.
- Do NOT include "rationale" in steps — it wastes tokens and adds no value.
- Do NOT assign planner_agent as a step agent. Planning is separate from execution.
- Do not start execution. Only plan.

STEP STATUS LIFECYCLE — each step starts as "pending". The runtime will:
  - Set status="running" when the step starts executing
  - Set status="completed" when the agent finishes successfully
  - Set status="failed" if the agent errors out
Never set these in the plan JSON — always emit "pending" as status.

CLARIFICATION POLICY — be very strict:
- Set "needs_clarification": true ONLY when the task CANNOT PHYSICALLY PROCEED without information you cannot infer. This means: missing credentials/API keys, unreferenced file path, specific codebase with no access.
- For ALL content/research/writing: assume and proceed. State assumptions in "summary". NEVER stop for content decisions.
- When in doubt, assume and proceed. Asking unnecessary questions is a serious failure.

AGENT ROUTING — the planning context has "skill_registry_hints" pre-computed by the skill registry. Treat as strong suggestions. Fallback intent keywords:
- github_agent: repo, PR, commit, branch, git, issue, fork
- coding_agent / master_coding_agent: write code, implement, generate code, fix bug, refactor
- aws_automation_agent: AWS, EC2, S3, Lambda, CloudFormation, IAM
- security_scanner_agent: security scan, vulnerability, CVE, OWASP, pen test
- devops_agent: Dockerfile, docker-compose, CI/CD, GitHub Actions
- long_document_agent: complete document, full report, handbook, guide, whitepaper (research + long-form writing pipeline)
- document_formatter_agent: ALWAYS the FINAL step in any plan producing a document, report, or guide. Exports Markdown + PDF + DOCX.

PROJECT BUILD MODE:
If the planning context contains "project_build_mode": true and a non-empty "blueprint_json",
this is a full project build. Use the following agent sequence for the plan steps:
  1. project_scaffold_agent -- Create directory structure, config files, entry points
  2. database_architect_agent -- Generate ORM models, migrations, Docker DB, seed data
  3. auth_security_agent -- Generate auth modules and security helpers (skip if auth is none or template already includes it)
  4. backend_builder_agent -- Implement API routes, services, middleware
  5. frontend_builder_agent -- Implement pages, components, API client, styling (skip if no frontend in blueprint)
  6. dependency_manager_agent -- Install all packages and validate lockfiles (scan all package.json / requirements)
  7. test_agent -- Generate and run tests (retry on failure) -- SKIP if "skip_test_agent": true in context
  8. security_scanner_agent -- Run npm audit / pip check or equivalent scans
  9. devops_agent -- Generate production Dockerfile, docker-compose, CI/CD, nginx config -- SKIP if "skip_devops_agent": true in context
 10. project_verifier_agent -- Run linters, type checks, build, and dev server health check
 11. post_setup_agent -- Run safe post-setup commands (e.g., docker compose up)
Each step's task field should reference the specific section of the blueprint it implements.
The blueprint_json in the context contains the full technical architecture.
Honor the "skip_test_agent" and "skip_devops_agent" flags in the planning context to omit those steps.

Planning context:
{_planning_context(state, user_query)}

Return ONLY valid JSON in this exact schema (no extra fields, no markdown, no explanation):
{{
  "needs_clarification": false,
  "clarification_questions": [],
  "summary": "1–2 sentence summary of the plan and key assumptions",
  "steps": [
    {{
      "id": "step-1",
      "title": "3–6 word step title",
      "agent": "agent_name_from_available_list",
      "task": "One sentence, ≤ 25 words, specific action for the agent to perform.",
      "depends_on": [],
      "parallel_group": "",
      "success_criteria": "One short phrase describing the observable output.",
      "status": "pending"
    }}
  ]
}}
""".strip()

    try:
        response = llm.invoke(prompt)
    except Exception as exc:
        raise RuntimeError(_planner_error_message(exc, provider_snapshot)) from exc
    raw_plan = normalize_llm_text(response.content if hasattr(response, "content") else response)
    try:
        parsed_plan = json.loads(_strip_code_fences(raw_plan))
    except Exception:
        parsed_plan = {}

    plan_data = normalize_plan_data(parsed_plan, user_query)
    plan_md = plan_as_markdown(plan_data)
    questions = plan_data.get("clarification_questions", [])
    plan_version = int(state.get("plan_version", 0) or 0) + 1

    state["plan"] = plan_md
    state["plan_data"] = plan_data
    state["plan_steps"] = plan_data.get("execution_steps", plan_data.get("steps", []))
    state["plan_step_index"] = 0
    state["plan_version"] = plan_version
    state["plan_ready"] = False
    state["plan_needs_clarification"] = bool(plan_data.get("needs_clarification", False))
    state["plan_clarification_questions"] = questions
    state["current_objective"] = user_query
    state["approval_pending_scope"] = ""
    state["pending_user_input_kind"] = ""
    state["plan_waiting_for_approval"] = False
    state["plan_approval_status"] = "draft"
    state["_skip_review_once"] = True

    if state["plan_needs_clarification"]:
        clarification_text = (
            "I need clarification before I can build an approval-ready plan:\n"
            + "\n".join(f"- {item}" for item in questions)
        ) if questions else "I need more detail before I can build an approval-ready plan."
        clarification_json = json.dumps({
            "type": "clarification",
            "questions": questions,
            "message": clarification_text,
        }, ensure_ascii=False)
        state["pending_user_question"] = clarification_text
        state["pending_user_input_kind"] = "clarification"
        state["plan_approval_status"] = "clarification_needed"
        state["draft_response"] = clarification_json
        planning_status = "needs_clarification"
        execution_note = f"Plan version {plan_version} needs clarification."
    else:
        auto_approve = bool(state.get("auto_approve")) or bool(state.get("auto_approve_plan"))
        plan_steps = plan_data.get("execution_steps", plan_data.get("steps", []))
        plan_json_response = json.dumps({
            "type": "plan_approval",
            "scope": f"execution plan v{plan_version}",
            "summary": plan_data.get("summary", ""),
            "steps": plan_steps,
            "plan_data": plan_data,
            "status": "approved" if auto_approve else "pending",
            "message": "Plan auto-approved — proceeding to execution." if auto_approve else "Reply `approve` to continue, or describe changes to regenerate the plan.",
        }, ensure_ascii=False)
        if auto_approve:
            state["pending_user_question"] = ""
            state["pending_user_input_kind"] = ""
            state["approval_pending_scope"] = ""
            state["plan_waiting_for_approval"] = False
            state["plan_approval_status"] = "approved"
            state["plan_ready"] = True
            state["draft_response"] = plan_json_response
            planning_status = "approved"
            execution_note = f"Plan version {plan_version} auto-approved."
            log_task_update("Planner", "Plan auto-approved; continuing to execution.")
        else:
            approval_prompt = build_plan_approval_prompt(
                plan_md,
                scope_title=f"execution plan v{plan_version}",
                storage_note=(
                    f"Stored in {OUTPUT_DIR}/planner_output.txt, {OUTPUT_DIR}/planner_output.json, "
                    "and the session planning memory."
                ),
            )
            state["pending_user_question"] = approval_prompt
            state["pending_user_input_kind"] = "plan_approval"
            state["approval_pending_scope"] = "root_plan"
            state["plan_waiting_for_approval"] = True
            state["plan_approval_status"] = "pending"
            state["draft_response"] = plan_json_response
            planning_status = "awaiting_approval"
            execution_note = f"Plan version {plan_version} generated and queued for approval."

    write_text_file("planner_output.txt", plan_md + "\n")
    write_text_file("planner_output.json", json.dumps(plan_data, indent=2, ensure_ascii=False))
    update_planning_file(
        state,
        status=planning_status,
        objective=user_query,
        plan_text=plan_md,
        clarifications=questions,
        execution_note=execution_note,
    )
    log_task_update("Planner", f"Plan saved to {OUTPUT_DIR}/planner_output.txt", plan_md)

    state = publish_agent_output(
        state,
        "planner_agent",
        plan_md,
        f"planner_plan_v{plan_version}",
        recipients=["orchestrator_agent", "worker_agent"],
    )
    return state
