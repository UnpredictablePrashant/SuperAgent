import json
from typing import Any

from tasks.a2a_agent_utils import begin_agent_session, publish_agent_output
from tasks.file_memory import update_planning_file
from tasks.utils import OUTPUT_DIR, llm, log_task_update, logger, model_selection_for_agent, write_text_file


def _strip_code_fences(text: str) -> str:
    stripped = (text or "").strip()
    if stripped.startswith("```") and stripped.endswith("```"):
        lines = stripped.splitlines()
        if len(lines) >= 2:
            return "\n".join(lines[1:-1]).strip()
    return stripped


def _as_str_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item).strip() for item in value if str(item).strip()]


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
        "rationale": str(item.get("rationale") or "").strip(),
        "llm_model": llm_model,
        "model_source": model_source,
        "substeps": substeps,
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
    plan_data["model_assignments"] = _collect_model_assignments(steps)
    return plan_data


def _step_markdown_lines(step: dict[str, Any], indent: int = 0) -> list[str]:
    prefix = "  " * indent
    depends_on = step.get("depends_on", [])
    depends_text = ", ".join(depends_on) if depends_on else "none"
    parallel_group = str(step.get("parallel_group") or "").strip() or "none"
    title = str(step.get("title", "")).strip() or str(step.get("id", "")).strip() or "Step"
    lines = [
        f"{prefix}- {step.get('id')}: {title}",
        f"{prefix}  agent={step.get('agent')} | llm={step.get('llm_model')} | source={step.get('model_source')}",
        f"{prefix}  task={step.get('task')}",
        f"{prefix}  depends_on={depends_text} | parallel_group={parallel_group}",
        f"{prefix}  success={step.get('success_criteria') or 'n/a'}",
    ]
    rationale = str(step.get("rationale") or "").strip()
    if rationale:
        lines.append(f"{prefix}  rationale={rationale}")
    child_steps = step.get("substeps", [])
    if isinstance(child_steps, list) and child_steps:
        lines.append(f"{prefix}  substeps:")
        for child in child_steps:
            if isinstance(child, dict):
                lines.extend(_step_markdown_lines(child, indent=indent + 2))
    return lines


def plan_as_markdown(plan_data: dict[str, Any]) -> str:
    lines: list[str] = []
    summary = str(plan_data.get("summary") or "").strip()
    if summary:
        lines.append(f"Summary: {summary}")
        lines.append("")

    lines.append("Model Allocation:")
    assignments = plan_data.get("model_assignments", [])
    if isinstance(assignments, list) and assignments:
        for item in assignments:
            lines.append(
                f"- {item.get('path')}: {item.get('title') or item.get('step_id')} | "
                f"agent={item.get('agent')} | llm={item.get('llm_model')} | source={item.get('model_source')}"
            )
    else:
        lines.append("- none")

    lines.append("")
    lines.append("Steps:")
    for step in plan_data.get("steps", []):
        if isinstance(step, dict):
            lines.extend(_step_markdown_lines(step))
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
        "local_drive_paths": state.get("local_drive_paths", []),
        "long_document_mode": bool(state.get("long_document_mode", False)),
        "long_document_pages": int(state.get("long_document_pages", 0) or 0),
        "superrag_mode": state.get("superrag_mode", ""),
        "superrag_urls": state.get("superrag_urls", []),
        "security_target_url": state.get("security_target_url", ""),
        "repo_scan_summary": str(state.get("repo_scan_summary", "")).strip()[:4000],
        "setup_summary": state.get("setup_summary", ""),
        "previous_plan": state.get("plan", ""),
        "revision_feedback": state.get("plan_revision_feedback", ""),
    }
    return json.dumps(context, indent=2, ensure_ascii=False)


def planner_agent(state):
    _, task_content, _ = begin_agent_session(state, "planner_agent")
    log_task_update("Planner", "Analyzing the request and building a detailed plan for approval.")

    user_query = str(task_content or state.get("current_objective") or state["user_query"]).strip()
    logger.info(f"[Planner] User query: {user_query}")

    prompt = f"""
You are a planning agent in a multi-agent runtime.

Your job is to create a very detailed execution plan before any substantive work begins.
The user must review and approve the plan before execution starts.

Requirements:
- Prefer concrete agents from the available agent list.
- Build a detailed top-level plan with explicit success criteria.
- Add substeps for complex deliverables, especially long reports, multi-document outputs, or 50-page style requests.
- If the request is ambiguous, ask clarification questions instead of guessing.
- Do not start execution. Only plan.

Planning context:
{_planning_context(state, user_query)}

Return ONLY valid JSON in this schema:
{{
  "needs_clarification": true or false,
  "clarification_questions": ["question"],
  "summary": "short planning summary",
  "steps": [
    {{
      "id": "step-1",
      "title": "short step title",
      "agent": "agent_name",
      "task": "specific task for the agent",
      "depends_on": ["step-id"],
      "parallel_group": "group-a or empty",
      "success_criteria": "how to verify this step",
      "rationale": "why this step exists",
      "substeps": [
        {{
          "id": "step-1.1",
          "title": "short substep title",
          "agent": "agent_name",
          "task": "specific task for the agent",
          "depends_on": ["step-id"],
          "parallel_group": "",
          "success_criteria": "verification target",
          "rationale": "why this substep exists"
        }}
      ]
    }}
  ]
}}
""".strip()

    response = llm.invoke(prompt)
    raw_plan = response.content if hasattr(response, "content") else str(response)
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
    state["plan_steps"] = plan_data.get("steps", [])
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
        clarification = (
            "I need clarification before I can build an approval-ready plan:\n"
            + "\n".join(f"- {item}" for item in questions)
        ) if questions else "I need more detail before I can build an approval-ready plan."
        state["pending_user_question"] = clarification
        state["pending_user_input_kind"] = "clarification"
        state["plan_approval_status"] = "clarification_needed"
        state["draft_response"] = clarification
        planning_status = "needs_clarification"
        execution_note = f"Plan version {plan_version} needs clarification."
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
        state["draft_response"] = approval_prompt
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
