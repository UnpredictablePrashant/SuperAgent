import importlib.util
import json
import re
from pathlib import Path

from tasks.a2a_agent_utils import begin_agent_session, publish_agent_output
from tasks.utils import OUTPUT_DIR, llm, log_task_update, normalize_llm_text, write_text_file


GENERATED_AGENT_DIR = Path("tasks/generated_agents")
MANIFEST_PATH = GENERATED_AGENT_DIR / "manifest.json"


def _strip_code_fences(text: str) -> str:
    stripped = normalize_llm_text(text).strip()
    if stripped.startswith("```") and stripped.endswith("```"):
        lines = stripped.splitlines()
        if len(lines) >= 2:
            return "\n".join(lines[1:-1]).strip()
    return stripped


def _safe_identifier(text: str, fallback: str = "custom_agent") -> str:
    cleaned = re.sub(r"[^a-zA-Z0-9_]+", "_", (text or "").strip().lower())
    cleaned = re.sub(r"_+", "_", cleaned).strip("_")
    if not cleaned:
        cleaned = fallback
    if cleaned[0].isdigit():
        cleaned = f"agent_{cleaned}"
    return cleaned


def _existing_agent_names(state: dict) -> list[str]:
    cards = state.get("a2a", {}).get("agent_cards", [])
    names = [card.get("agent_name") for card in cards if card.get("agent_name")]
    return sorted(dict.fromkeys(names))


def _load_manifest() -> dict:
    if not MANIFEST_PATH.exists():
        return {}
    try:
        return json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _save_manifest(payload: dict) -> None:
    GENERATED_AGENT_DIR.mkdir(parents=True, exist_ok=True)
    MANIFEST_PATH.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")


def _build_factory_prompt(request_text: str, missing_capability: str, existing_agents: list[str]) -> str:
    return f"""
You are an agent-factory planner inside a multi-agent system.

Your job is to design one new agent when the current ecosystem does not cover a needed capability.

User request:
{request_text}

Missing capability or gap:
{missing_capability or "Infer it from the user request."}

Existing agents:
{json.dumps(existing_agents, ensure_ascii=False)}

Return ONLY valid JSON in this exact schema:
{{
  "agent_name": "snake_case name ending with _agent",
  "module_name": "python_module_name",
  "function_name": "python_function_name",
  "description": "short description",
  "skills": ["skill 1", "skill 2"],
  "input_keys": ["state_input_key"],
  "output_keys": ["state_output_key"],
  "primary_input_key": "main state key this agent should read",
  "primary_output_key": "main state key this agent should write",
  "task_prompt": "what the generated agent should do in its LLM prompt",
  "requirements": ["env var or dependency requirements if any"],
  "notes": "short implementation notes"
}}
""".strip()


def _parse_factory_output(raw_output: str) -> dict:
    cleaned = _strip_code_fences(raw_output)
    return json.loads(cleaned)


def _build_generated_agent_code(spec: dict) -> str:
    function_name = spec["function_name"]
    primary_input_key = spec["primary_input_key"]
    primary_output_key = spec["primary_output_key"]
    description = spec["description"]
    task_prompt = spec["task_prompt"]
    skills = json.dumps(spec.get("skills", []), ensure_ascii=False)
    requirements = json.dumps(spec.get("requirements", []), ensure_ascii=False)

    return f'''import json

from tasks.a2a_agent_utils import begin_agent_session, publish_agent_output
from tasks.utils import OUTPUT_DIR, llm, log_task_update, write_text_file


def {function_name}(state):
    active_task, task_content, _ = begin_agent_session(state, "{function_name}")
    state["{function_name}_calls"] = state.get("{function_name}_calls", 0) + 1
    call_number = state["{function_name}_calls"]

    request_text = state.get("{primary_input_key}") or task_content or state.get("current_objective") or state.get("user_query", "")
    context = {{
        "request_text": request_text,
        "current_objective": state.get("current_objective", ""),
        "user_query": state.get("user_query", ""),
        "skills": {skills},
        "requirements": {requirements},
        "notes": {json.dumps(spec.get("notes", ""), ensure_ascii=False)},
    }}

    log_task_update("{function_name}", f"Generated agent pass #{{call_number}} started.")
    prompt = f"""
You are the {function_name} in a multi-agent ecosystem.

Description:
{description}

Primary task:
{task_prompt}

Context:
{{json.dumps(context, indent=2, ensure_ascii=False)}}

Return a concise but useful result for the requested work. If external setup is missing, say exactly what is required.
""".strip()

    response = llm.invoke(prompt)
    output_text = normalize_llm_text(response.content if hasattr(response, "content") else response)
    state["{primary_output_key}"] = output_text
    state["draft_response"] = output_text
    write_text_file("{function_name}_output_" + str(call_number) + ".txt", output_text)
    log_task_update("{function_name}", f"Generated agent output saved to {{OUTPUT_DIR}}/{function_name}_output_{{call_number}}.txt")
    return publish_agent_output(
        state,
        "{function_name}",
        output_text,
        "{function_name}_result_" + str(call_number),
        recipients=["orchestrator_agent", "worker_agent", "reviewer_agent"],
    )
'''


def agent_factory_agent(state):
    active_task, task_content, _ = begin_agent_session(state, "agent_factory_agent")
    state["agent_factory_calls"] = state.get("agent_factory_calls", 0) + 1
    call_number = state["agent_factory_calls"]

    request_text = (
        state.get("agent_factory_request")
        or task_content
        or state.get("current_objective")
        or state.get("user_query", "")
    ).strip()
    if not request_text:
        raise ValueError("agent_factory_agent requires a request in state or task content.")

    missing_capability = state.get("missing_capability") or state.get("requested_missing_capability", "")
    existing_agents = _existing_agent_names(state)
    log_task_update("Agent Factory", f"Factory pass #{call_number} started.")

    prompt = _build_factory_prompt(request_text, missing_capability, existing_agents)
    response = llm.invoke(prompt)
    raw_output = normalize_llm_text(response.content if hasattr(response, "content") else response)

    try:
        spec = _parse_factory_output(raw_output)
    except Exception:
        fallback_name = _safe_identifier(missing_capability or "custom capability") + "_agent"
        fallback_name = fallback_name if fallback_name.endswith("_agent") else f"{fallback_name}_agent"
        spec = {
            "agent_name": fallback_name,
            "module_name": fallback_name.replace("_agent", "_tasks"),
            "function_name": fallback_name,
            "description": f"Generated fallback agent for: {missing_capability or request_text}",
            "skills": ["custom task handling", "llm synthesis"],
            "input_keys": ["current_objective", "user_query"],
            "output_keys": [f"{fallback_name}_result"],
            "primary_input_key": "current_objective",
            "primary_output_key": f"{fallback_name}_result",
            "task_prompt": request_text,
            "requirements": [],
            "notes": "Fallback spec because the factory planner returned invalid JSON.",
        }

    spec["agent_name"] = _safe_identifier(spec.get("agent_name", "custom_agent"))
    if not spec["agent_name"].endswith("_agent"):
        spec["agent_name"] = f"{spec['agent_name']}_agent"
    spec["function_name"] = _safe_identifier(spec.get("function_name", spec["agent_name"]), spec["agent_name"])
    spec["module_name"] = _safe_identifier(spec.get("module_name", spec["agent_name"].replace("_agent", "_tasks")))
    spec["primary_input_key"] = _safe_identifier(spec.get("primary_input_key", "current_objective"), "current_objective")
    spec["primary_output_key"] = _safe_identifier(
        spec.get("primary_output_key", f"{spec['function_name']}_result"),
        f"{spec['function_name']}_result",
    )

    GENERATED_AGENT_DIR.mkdir(parents=True, exist_ok=True)
    module_path = GENERATED_AGENT_DIR / f"{spec['module_name']}.py"
    code = _build_generated_agent_code(spec)
    module_path.write_text(code, encoding="utf-8")

    manifest = _load_manifest()
    manifest[spec["agent_name"]] = {
        **spec,
        "module_path": str(module_path.resolve()),
    }
    _save_manifest(manifest)

    registration_plan = {
        "module_path": str(module_path.resolve()),
        "manifest_path": str(MANIFEST_PATH.resolve()),
        "dynamic_runner_state": {
            "generated_agent_name": spec["agent_name"],
            "generated_agent_function": spec["function_name"],
            "generated_agent_module_path": str(module_path.resolve()),
            "generated_agent_task": request_text,
        },
        "next_step": "Use dynamic_agent_runner to execute the generated agent in the current workflow.",
    }
    summary = (
        f"Created generated agent {spec['agent_name']}.\n"
        f"Module: {module_path}\n"
        f"Description: {spec['description']}\n"
        f"Primary input: {spec['primary_input_key']}\n"
        f"Primary output: {spec['primary_output_key']}\n"
        f"Requirements: {', '.join(spec.get('requirements', [])) or 'None'}"
    )

    write_text_file(f"agent_factory_output_{call_number}.txt", summary + "\n\n" + json.dumps(spec, indent=2, ensure_ascii=False))
    write_text_file(f"agent_factory_manifest_{call_number}.json", json.dumps(registration_plan, indent=2, ensure_ascii=False))

    state["agent_factory_spec"] = spec
    state["agent_factory_registration_plan"] = registration_plan
    state["generated_agent_name"] = spec["agent_name"]
    state["generated_agent_function"] = spec["function_name"]
    state["generated_agent_module_path"] = str(module_path.resolve())
    state["generated_agent_task"] = request_text
    state["draft_response"] = summary
    state["dynamic_agent_ready"] = True
    log_task_update("Agent Factory", f"Generated {spec['agent_name']} at {module_path}")
    return publish_agent_output(
        state,
        "agent_factory_agent",
        summary,
        f"agent_factory_result_{call_number}",
        recipients=["orchestrator_agent", "worker_agent", "reviewer_agent", "dynamic_agent_runner"],
    )


def dynamic_agent_runner(state):
    active_task, task_content, _ = begin_agent_session(state, "dynamic_agent_runner")
    state["dynamic_agent_runner_calls"] = state.get("dynamic_agent_runner_calls", 0) + 1
    call_number = state["dynamic_agent_runner_calls"]

    module_path = Path(state.get("generated_agent_module_path", "")).resolve()
    function_name = state.get("generated_agent_function", "")
    agent_name = state.get("generated_agent_name", "")
    task_text = state.get("generated_agent_task") or task_content or state.get("current_objective") or state.get("user_query", "")

    if not (module_path.exists() and function_name and agent_name):
        raise ValueError("dynamic_agent_runner requires generated_agent_module_path, generated_agent_function, and generated_agent_name.")

    log_task_update("Dynamic Agent Runner", f"Runner pass #{call_number} started for {agent_name}.")
    spec = importlib.util.spec_from_file_location(module_path.stem, module_path)
    if spec is None or spec.loader is None:
        raise ImportError(f"Could not load generated agent module from {module_path}.")

    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    generated_fn = getattr(module, function_name, None)
    if generated_fn is None:
        raise AttributeError(f"Generated function {function_name} was not found in {module_path}.")

    current_task = state.get("active_task")
    if isinstance(current_task, dict):
        state["active_task"] = {
            **current_task,
            "recipient": agent_name,
            "content": task_text,
        }

    result_state = generated_fn(state)
    generated_output = result_state.get("draft_response") or result_state.get(spec_from_manifest(agent_name).get("primary_output_key", ""), "")
    summary = f"Executed generated agent {agent_name} from {module_path}."
    write_text_file(
        f"dynamic_agent_runner_output_{call_number}.txt",
        summary + "\n\n" + (generated_output or "No generated output."),
    )
    result_state["generated_agent_last_result"] = generated_output
    result_state["draft_response"] = generated_output or summary
    return publish_agent_output(
        result_state,
        "dynamic_agent_runner",
        summary + ("\n\n" + generated_output if generated_output else ""),
        f"dynamic_agent_runner_result_{call_number}",
        recipients=["orchestrator_agent", "worker_agent", "reviewer_agent"],
    )


def spec_from_manifest(agent_name: str) -> dict:
    manifest = _load_manifest()
    spec = manifest.get(agent_name, {})
    return spec if isinstance(spec, dict) else {}
