import json

from tasks.a2a_agent_utils import begin_agent_session, publish_agent_output, recent_messages_for_agent
from tasks.utils import OUTPUT_DIR, llm, log_task_update, normalize_llm_text, write_text_file


def _strip_code_fences(text: str) -> str:
    stripped = normalize_llm_text(text).strip()
    if stripped.startswith("```") and stripped.endswith("```"):
        lines = stripped.splitlines()
        if len(lines) >= 2:
            return "\n".join(lines[1:-1]).strip()
    return stripped


def _parse_review_output(raw_output: str) -> dict:
    cleaned = _strip_code_fences(raw_output)
    data = json.loads(cleaned)
    if not isinstance(data, dict):
        raise ValueError("Reviewer output must be a JSON object.")
    return data


def reviewer_agent(state):
    active_task, task_content, _ = begin_agent_session(state, "reviewer_agent")
    state["reviewer_calls"] = state.get("reviewer_calls", 0) + 1
    a2a_context = recent_messages_for_agent(state, "reviewer_agent")
    current_objective = state.get("current_objective") or state["user_query"]
    latest_output = state.get("last_agent_output") or state.get("draft_response", "")
    latest_agent = state.get("last_agent", "unknown")
    planned_step_id = str(
        state.get("last_completed_plan_step_id")
        or state.get("current_plan_step_id")
        or ""
    ).strip()
    planned_step_title = str(
        state.get("last_completed_plan_step_title")
        or state.get("current_plan_step_title")
        or ""
    ).strip()
    planned_step_success = str(
        state.get("last_completed_plan_step_success_criteria")
        or state.get("current_plan_step_success_criteria")
        or ""
    ).strip()
    revision_counts = state.get("review_revision_counts", {})
    if not isinstance(revision_counts, dict):
        revision_counts = {}
    revision_key = f"{planned_step_id or 'adhoc-step'}|{latest_agent or 'unknown-agent'}"
    revision_attempts = int(revision_counts.get(revision_key, 0) or 0)
    recent_history = state.get("agent_history", [])[-8:]
    available_agents = [
        card.get("agent_name")
        for card in state.get("a2a", {}).get("agent_cards", [])
        if card.get("agent_name") and card.get("agent_name") != "reviewer_agent"
    ]
    if "worker_agent" not in available_agents and state.get("available_agents"):
        available_agents = [name for name in state["available_agents"] if name != "reviewer_agent"]
    allowed_next_agents = sorted(dict.fromkeys(available_agents))
    allowed_enum = "|".join(allowed_next_agents + ["finish"])
    allowed_text = ", ".join(allowed_next_agents) if allowed_next_agents else "worker_agent"
    latest_structured_context = {}
    if latest_agent == "local_drive_agent" and isinstance(state.get("local_drive_manifest"), dict):
        manifest = state.get("local_drive_manifest", {})
        latest_structured_context = {
            "folder_count": manifest.get("folder_count", 0),
            "file_count": manifest.get("file_count", 0),
            "selected_file_count": manifest.get("selected_file_count", 0),
            "excluded_file_count": manifest.get("excluded_file_count", 0),
            "truncated": bool(manifest.get("truncated", False)),
            "folders_preview": (manifest.get("folders") or [])[:5],
            "files_preview": (manifest.get("files") or [])[:10],
        }
    log_task_update(
        "Reviewer",
        f"Review pass #{state['reviewer_calls']} started. Auditing the latest step against the current objective.",
    )
    prompt=f"""
    You are a strict workflow reviewer agent in a multi-agent system.

    Your job is to review the current objective, the latest work done by the agents, and whether the latest output is correct.
    If the work is wrong or incomplete, you must:
    1. correct or tighten the objective,
    2. decide which agent should work again,
    3. provide corrected values for that agent.

    Current objective: {current_objective}
    Original user query: {state['user_query']}
    Latest agent: {latest_agent}
    Current planned step id: {planned_step_id or 'n/a'}
    Current planned step title: {planned_step_title or 'n/a'}
    Current planned step success criteria: {planned_step_success or 'n/a'}
    Prior revision attempts for this step: {revision_attempts}
    Latest output:
    {latest_output}

    Recent agent history:
    {json.dumps(recent_history, indent=2)}

    Recent A2A messages for the reviewer:
    {a2a_context}

    Relevant structured state for the latest agent:
    {json.dumps(latest_structured_context, indent=2, ensure_ascii=False)}

    Current setup summary:
    {state.get("setup_summary", "")}

    Review the latest output against the current planned step, not against the final end-to-end deliverable.
    Approve the step if it materially satisfies the current objective and success criteria, even if the full user request is not finished yet.
    Do not request a retry unless you can name a concrete deficiency that the next attempt can realistically fix.
    Allowed next agents when revision is needed:
    {allowed_text}

    Return ONLY valid JSON in this exact schema:
    {{
      "decision": "approve" or "revise",
      "reason": "brief reason",
      "is_output_correct": true or false,
      "revised_objective": "the best current objective",
      "step_reviews": [
        {{
          "agent": "agent name",
          "status": "correct|needs_revision|insufficient",
          "notes": "brief note"
        }}
      ],
      "next_agent": "{allowed_enum}",
      "corrected_values": {{
        "key": "value"
      }}
    }}
    """
    response=llm.invoke(prompt)
    raw_output=response.content.strip() if hasattr(response, "content") else str(response)

    try:
        review_data = _parse_review_output(raw_output)
    except Exception:
        review_data = {
            "decision": "revise",
            "reason": "Reviewer returned invalid JSON. Retry the worker with the current objective.",
            "is_output_correct": False,
            "revised_objective": current_objective,
            "step_reviews": [
                {
                    "agent": latest_agent,
                    "status": "needs_revision",
                    "notes": "Reviewer output was invalid JSON.",
                }
            ],
            "next_agent": "worker_agent",
            "corrected_values": {},
        }

    decision = review_data.get("decision", "revise")
    reason = review_data.get("reason", "No reason provided")
    revised_objective = review_data.get("revised_objective") or current_objective
    next_agent = review_data.get("next_agent", "finish" if decision == "approve" else "worker_agent")
    if next_agent != "finish" and next_agent not in allowed_next_agents:
        next_agent = "worker_agent" if "worker_agent" in allowed_next_agents else "finish"
        reason = f"{reason} Reviewer fallback applied because the requested retry agent is not currently available."
    corrected_values = review_data.get("corrected_values", {})
    if not isinstance(corrected_values, dict):
        corrected_values = {}

    state["review_decision"] = decision
    state["review_reason"] = reason
    state["review_is_output_correct"] = bool(review_data.get("is_output_correct", decision == "approve"))
    state["review_step_assessments"] = review_data.get("step_reviews", [])
    state["review_target_agent"] = next_agent
    state["review_corrected_values"] = corrected_values
    state["review_revised_objective"] = revised_objective
    state["review_subject_step_id"] = planned_step_id
    state["review_subject_agent"] = latest_agent
    state["current_objective"] = revised_objective

    write_text_file(
    f"reviewer_output_{state['reviewer_calls']}.txt",
    raw_output
    + (
        f"\nParsed Decision: {decision}"
        f"\nReason: {reason}"
        f"\nRevised Objective: {revised_objective}"
        f"\nNext Agent: {next_agent}"
        f"\nCorrected Values: {json.dumps(corrected_values, ensure_ascii=False)}"
    )
    )
    log_task_update(
        "Reviewer",
        f"Decision saved to {OUTPUT_DIR}/reviewer_output_{state['reviewer_calls']}.txt",
        (
            f"Decision: {decision}\n"
            f"Reason: {reason}\n"
            f"Revised Objective: {revised_objective}\n"
            f"Next Agent: {next_agent}\n"
            f"Corrected Values: {json.dumps(corrected_values, ensure_ascii=False)}"
        ),
    )
    recipients = ["orchestrator_agent"]
    if decision == "revise" and next_agent != "finish":
        recipients.append(next_agent)
    state = publish_agent_output(
        state,
        "reviewer_agent",
        (
            f"Decision: {decision}\n"
            f"Reason: {reason}\n"
            f"Revised Objective: {revised_objective}\n"
            f"Next Agent: {next_agent}\n"
            f"Corrected Values: {json.dumps(corrected_values, ensure_ascii=False)}"
        ),
        f"reviewer_decision_{state['reviewer_calls']}",
        recipients=recipients,
    )
    return state
