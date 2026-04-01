import json
import os
import time

from openai import OpenAI

from tasks.a2a_agent_utils import begin_agent_session, publish_agent_output
from tasks.coding_tasks import _extract_output_text
from tasks.utils import OUTPUT_DIR, log_task_update, write_text_file


DEFAULT_DEEP_RESEARCH_MODEL = os.getenv("OPENAI_DEEP_RESEARCH_MODEL", "o4-mini-deep-research")

AGENT_METADATA = {
    "deep_research_agent": {
        "description": "Runs OpenAI Deep Research for web-grounded, source-aware, in-depth research tasks.",
        "skills": ["deep", "research", "web", "citations", "analysis"],
        "input_keys": [
            "research_query",
            "research_model",
            "research_instructions",
            "research_max_tool_calls",
            "research_max_output_tokens",
        ],
        "output_keys": [
            "research_result",
            "research_status",
            "research_response_id",
            "research_raw",
        ],
        "requirements": ["openai"],
        "display_name": "Deep Research Agent",
        "category": "research",
        "intent_patterns": [
            "research this topic", "do deep research", "investigate in depth",
            "find citations", "source-backed analysis", "web research with sources",
        ],
        "active_when": ["env:OPENAI_API_KEY"],
        "config_hint": "Add your OpenAI API key in Setup → Providers.",
    }
}


def _serialize_response(response) -> dict:
    if hasattr(response, "model_dump"):
        return response.model_dump()
    if isinstance(response, dict):
        return response
    return {"response": str(response)}


def deep_research_agent(state):
    active_task, task_content, _ = begin_agent_session(state, "deep_research_agent")
    state["deep_research_calls"] = state.get("deep_research_calls", 0) + 1
    call_number = state["deep_research_calls"]

    query = state.get("research_query") or task_content or state.get("current_objective") or state.get("user_query", "").strip()
    if not query:
        raise ValueError("deep_research_agent requires 'research_query' or 'user_query' in state.")

    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise ValueError("OPENAI_API_KEY is required for deep_research_agent.")

    model = state.get("research_model", DEFAULT_DEEP_RESEARCH_MODEL)
    max_tool_calls = int(state.get("research_max_tool_calls", 8))
    max_output_tokens = state.get("research_max_output_tokens")
    instructions = state.get(
        "research_instructions",
        "Conduct a careful web-based deep research pass. Synthesize the results clearly, cite concrete sources when available, and call out uncertainty.",
    )
    background = state.get("research_background", True)
    poll_interval_seconds = int(state.get("research_poll_interval_seconds", 5))
    max_wait_seconds = int(state.get("research_max_wait_seconds", 600))

    client = OpenAI(api_key=api_key)

    log_task_update(
        "Deep Research",
        f"Research pass #{call_number} started with model '{model}'.",
        query,
    )

    create_kwargs = {
        "model": model,
        "input": query,
        "instructions": instructions,
        "background": background,
        "max_tool_calls": max_tool_calls,
        "reasoning": {"summary": "auto"},
        "tools": [{"type": "web_search_preview"}],
    }
    if max_output_tokens is not None:
        create_kwargs["max_output_tokens"] = int(max_output_tokens)

    response = client.responses.create(**create_kwargs)
    response_id = response.id
    status = getattr(response, "status", "unknown")

    log_task_update(
        "Deep Research",
        f"Research job created with response id '{response_id}' and initial status '{status}'.",
    )

    elapsed_seconds = 0
    while background and status not in {"completed", "failed", "cancelled", "incomplete"}:
        if elapsed_seconds >= max_wait_seconds:
            raise TimeoutError(
                f"Deep research job '{response_id}' did not finish within {max_wait_seconds} seconds."
            )

        time.sleep(poll_interval_seconds)
        elapsed_seconds += poll_interval_seconds
        response = client.responses.retrieve(response_id)
        new_status = getattr(response, "status", "unknown")

        if new_status != status:
            status = new_status
            log_task_update(
                "Deep Research",
                f"Research job '{response_id}' status changed to '{status}' after {elapsed_seconds} seconds.",
            )
        else:
            log_task_update(
                "Deep Research",
                f"Research job '{response_id}' still '{status}' after {elapsed_seconds} seconds.",
            )

    payload = _serialize_response(response)
    output_text = getattr(response, "output_text", None) or _extract_output_text(payload)

    raw_filename = f"deep_research_raw_{call_number}.json"
    output_filename = f"deep_research_output_{call_number}.txt"

    write_text_file(raw_filename, json.dumps(payload, indent=2, ensure_ascii=False))
    write_text_file(output_filename, output_text)

    state["research_response_id"] = response_id
    state["research_status"] = getattr(response, "status", status)
    state["research_result"] = output_text
    state["research_model"] = model
    state["research_raw"] = payload
    state["draft_response"] = output_text

    log_task_update(
        "Deep Research",
        f"Deep research finished with status '{state['research_status']}'. Saved artifacts to {OUTPUT_DIR}/{output_filename}.",
        output_text,
    )
    state = publish_agent_output(
        state,
        "deep_research_agent",
        output_text,
        f"deep_research_result_{call_number}",
        recipients=["orchestrator_agent", "worker_agent"],
    )
    return state
