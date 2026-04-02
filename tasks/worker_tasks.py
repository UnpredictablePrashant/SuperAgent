from tasks.a2a_agent_utils import begin_agent_session, publish_agent_output, recent_messages_for_agent
from tasks.utils import OUTPUT_DIR, llm, log_task_update, logger, normalize_llm_response, write_text_file

def worker_agent(state):
    active_task, task_content, _ = begin_agent_session(state, "worker_agent")
    state['worker_calls']+=1
    feedback=state.get('review_reason',"")
    user_query = task_content or state.get("current_objective") or state["user_query"]
    a2a_context = recent_messages_for_agent(state, "worker_agent")
    repo_scan_summary = state.get("repo_scan_summary", "")
    project_context_md = state.get("project_context_md", "")
    log_task_update("Worker", f"Draft pass #{state['worker_calls']} started.")
    if feedback:
        logger.info(f"[Worker] Applying reviewer feedback: {feedback}")
    else:
        logger.info("[Worker] No reviewer feedback yet. Generating the first draft.")
    prompt=f"""
    You are a worker agent

    User query:{user_query}

    Current objective: {state.get('current_objective') or state['user_query']}

    Plan: {state['plan']}

    Previous reviewer feedback: {feedback}

    Current setup summary:
    {state.get('setup_summary', '')}

    Available setup actions:
    {state.get('setup_actions', [])}

    Recent A2A messages for the worker:
    {a2a_context}

    Project context (kendr.md — permanent memory about this codebase):
    {project_context_md or "No project context file (kendr.md) is attached to this run."}

    Repository scan summary (if available):
    {repo_scan_summary or "No repository scan summary was attached to this run."}

    Write the best possible improved response.
    If reviewer feedback exists, explicitly fix those issues.
    If the user asks for an integration or capability that is not configured, explain exactly what is missing and point to the available setup actions instead of pretending it is available.
    Do not claim you lack filesystem access when repository scan summary is provided above; use that evidence directly.

    """
    response=llm.invoke(prompt)

    draft_response=normalize_llm_response(response)

    state['draft_response']=draft_response

    write_text_file(f"Worker_output_{state['worker_calls']}.txt", draft_response)

    log_task_update(
        "Worker",
        f"Draft saved to {OUTPUT_DIR}/Worker_output_{state['worker_calls']}.txt",
        draft_response,
    )
    state = publish_agent_output(
        state,
        "worker_agent",
        draft_response,
        f"worker_draft_{state['worker_calls']}",
        recipients=["orchestrator_agent", "reviewer_agent"],
    )

    return state
