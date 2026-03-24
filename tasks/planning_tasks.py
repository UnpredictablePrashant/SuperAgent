import json

from tasks.a2a_agent_utils import begin_agent_session, publish_agent_output
from tasks.file_memory import update_planning_file
from tasks.utils import OUTPUT_DIR, llm, log_task_update, logger, write_text_file


def _strip_code_fences(text: str) -> str:
    stripped = (text or "").strip()
    if stripped.startswith("```") and stripped.endswith("```"):
        lines = stripped.splitlines()
        if len(lines) >= 2:
            return "\n".join(lines[1:-1]).strip()
    return stripped


def _parse_plan_output(raw_output: str, objective: str) -> dict:
    fallback = {
        "needs_clarification": False,
        "clarification_questions": [],
        "summary": "Build a direct worker draft and review it against the objective.",
        "steps": [
            {
                "id": "step-1",
                "agent": "worker_agent",
                "task": objective,
                "depends_on": [],
                "parallel_group": "",
                "success_criteria": "Provide a complete response aligned with the objective.",
            },
            {
                "id": "step-2",
                "agent": "reviewer_agent",
                "task": "Review the worker output against the original objective and request revision if needed.",
                "depends_on": ["step-1"],
                "parallel_group": "",
                "success_criteria": "Output is correct and complete for the objective.",
            },
        ],
    }
    try:
        parsed = json.loads(_strip_code_fences(raw_output))
        if not isinstance(parsed, dict):
            return fallback
        steps = parsed.get("steps", [])
        if not isinstance(steps, list) or not steps:
            return fallback
        normalized_steps = []
        for idx, item in enumerate(steps, start=1):
            if not isinstance(item, dict):
                continue
            normalized_steps.append(
                {
                    "id": str(item.get("id") or f"step-{idx}"),
                    "agent": str(item.get("agent") or "worker_agent"),
                    "task": str(item.get("task") or objective),
                    "depends_on": [str(x) for x in item.get("depends_on", []) if str(x).strip()],
                    "parallel_group": str(item.get("parallel_group") or ""),
                    "success_criteria": str(item.get("success_criteria") or ""),
                }
            )
        if not normalized_steps:
            return fallback
        return {
            "needs_clarification": bool(parsed.get("needs_clarification", False)),
            "clarification_questions": [
                str(x) for x in parsed.get("clarification_questions", []) if str(x).strip()
            ],
            "summary": str(parsed.get("summary") or ""),
            "steps": normalized_steps,
        }
    except Exception:
        return fallback


def _plan_as_markdown(plan_data: dict) -> str:
    lines = []
    if plan_data.get("summary"):
        lines.append(f"Summary: {plan_data['summary']}")
        lines.append("")
    lines.append("Steps:")
    for step in plan_data.get("steps", []):
        lines.append(
            (
                f"- {step.get('id')}: agent={step.get('agent')} | task={step.get('task')} | "
                f"depends_on={step.get('depends_on', [])} | parallel_group={step.get('parallel_group', '') or 'none'} | "
                f"success={step.get('success_criteria', '') or 'n/a'}"
            )
        )
    return "\n".join(lines)


def planner_agent(state):
    _, task_content, _ = begin_agent_session(state, "planner_agent")
    log_task_update("Planner", "Analyzing the user request and building a detailed plan.")
    user_query = task_content or state.get("current_objective") or state["user_query"]
    logger.info(f"[Planner] User query: {user_query}")
    available_agents = state.get("available_agents", [])
    prompt = f"""
You are a planning agent in a multi-agent AI runtime.

Build a detailed execution plan for the objective.
If the request is ambiguous, ask clarifying questions before execution.
Prefer concrete agents from this list:
{available_agents}

Objective:
{user_query}

Return ONLY valid JSON in this schema:
{{
  "needs_clarification": true or false,
  "clarification_questions": ["question"],
  "summary": "short planning summary",
  "steps": [
    {{
      "id": "step-1",
      "agent": "agent_name",
      "task": "specific task for the agent",
      "depends_on": ["step-id"],
      "parallel_group": "group-a or empty",
      "success_criteria": "how to verify this step"
    }}
  ]
}}
""".strip()
    response = llm.invoke(prompt)
    raw_plan = response.content if hasattr(response, "content") else str(response)
    plan_data = _parse_plan_output(raw_plan, user_query)
    plan_md = _plan_as_markdown(plan_data)
    questions = plan_data.get("clarification_questions", [])

    state["plan"] = plan_md
    state["plan_data"] = plan_data
    state["plan_steps"] = plan_data.get("steps", [])
    state["plan_step_index"] = 0
    state["plan_ready"] = not bool(plan_data.get("needs_clarification", False))
    state["plan_needs_clarification"] = bool(plan_data.get("needs_clarification", False))
    state["plan_clarification_questions"] = questions
    state["current_objective"] = user_query
    if questions:
        state["pending_user_question"] = "\n".join(f"- {item}" for item in questions)

    write_text_file("planner_output.txt", plan_md)
    update_planning_file(
        state,
        status="needs_clarification" if state["plan_needs_clarification"] else "planned",
        objective=user_query,
        plan_text=plan_md,
        clarifications=questions,
        execution_note="Initial plan generated.",
    )
    log_task_update("Planner", f"Plan saved to {OUTPUT_DIR}/planner_output.txt", plan_md)
    state = publish_agent_output(
        state,
        "planner_agent",
        plan_md,
        "planner_plan",
        recipients=["orchestrator_agent", "worker_agent"],
    )
    return state
