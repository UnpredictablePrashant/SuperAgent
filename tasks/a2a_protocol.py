from __future__ import annotations

from copy import deepcopy
from datetime import UTC, datetime

from kendr.persistence import insert_artifact, insert_message, upsert_agent_card, upsert_task


def _utc_timestamp() -> str:
    return datetime.now(UTC).isoformat()


def make_agent_card(
    agent_name: str,
    description: str,
    skills: list[str],
    input_keys: list[str],
    output_keys: list[str],
    requirements: list[str] | None = None,
) -> dict:
    return {
        "agent_name": agent_name,
        "description": description,
        "skills": skills,
        "input_keys": input_keys,
        "output_keys": output_keys,
        "requirements": list(requirements or []),
    }


def make_message(sender: str, recipient: str, role: str, content: str) -> dict:
    return {
        "message_id": f"msg_{datetime.now(UTC).timestamp()}",
        "timestamp": _utc_timestamp(),
        "sender": sender,
        "recipient": recipient,
        "role": role,
        "content": content,
    }


def make_artifact(name: str, kind: str, content: str, metadata: dict | None = None) -> dict:
    timestamp = _utc_timestamp()
    return {
        "artifact_id": f"artifact_{datetime.now(UTC).timestamp()}",
        "timestamp": timestamp,
        "name": name,
        "kind": kind,
        "content": content,
        "metadata": metadata or {},
    }


def make_task(
    sender: str,
    recipient: str,
    intent: str,
    content: str,
    state_updates: dict | None = None,
) -> dict:
    return {
        "task_id": f"task_{datetime.now(UTC).timestamp()}",
        "timestamp": _utc_timestamp(),
        "sender": sender,
        "recipient": recipient,
        "intent": intent,
        "content": content,
        "state_updates": deepcopy(state_updates or {}),
        "status": "pending",
    }


def ensure_a2a_state(state: dict, agent_cards: list[dict] | None = None) -> dict:
    if "a2a" not in state:
        state["a2a"] = {
            "protocol": "google-a2a-inspired",
            "agent_cards": agent_cards or [],
            "messages": [],
            "tasks": [],
            "artifacts": [],
        }
        return state

    a2a = state["a2a"]
    a2a.setdefault("protocol", "google-a2a-inspired")
    a2a.setdefault("agent_cards", agent_cards or [])
    a2a.setdefault("messages", [])
    a2a.setdefault("tasks", [])
    a2a.setdefault("artifacts", [])
    if agent_cards:
        a2a["agent_cards"] = agent_cards
        for card in agent_cards:
            upsert_agent_card(card, _utc_timestamp())
    return state


def append_message(state: dict, message: dict) -> dict:
    ensure_a2a_state(state)
    state["a2a"]["messages"].append(message)
    run_id = state.get("run_id")
    if run_id:
        task_id = state.get("active_task", {}).get("task_id") if state.get("active_task") else None
        insert_message(run_id, message, task_id=task_id)
    return state


def append_task(state: dict, task: dict) -> dict:
    ensure_a2a_state(state)
    state["a2a"]["tasks"].append(task)
    run_id = state.get("run_id")
    if run_id:
        upsert_task(run_id, task)
    return state


def append_artifact(state: dict, artifact: dict) -> dict:
    ensure_a2a_state(state)
    state["a2a"]["artifacts"].append(artifact)
    run_id = state.get("run_id")
    if run_id:
        insert_artifact(run_id, artifact)
    return state


def task_for_agent(state: dict, agent_name: str) -> dict | None:
    ensure_a2a_state(state)
    tasks = state["a2a"]["tasks"]
    for task in reversed(tasks):
        if task["recipient"] == agent_name and task["status"] == "pending":
            return task
    return None


def complete_task(state: dict, task_id: str, status: str = "completed") -> dict:
    ensure_a2a_state(state)
    for task in reversed(state["a2a"]["tasks"]):
        if task["task_id"] == task_id:
            task["status"] = status
            task["completed_at"] = _utc_timestamp()
            run_id = state.get("run_id")
            if run_id:
                upsert_task(run_id, task)
            break
    return state
