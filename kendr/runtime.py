from __future__ import annotations

import json
import os
import uuid
from collections.abc import Mapping
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from langgraph.graph import END, StateGraph
from kendr.orchestration import ResumeStateOverrides, RuntimeState, state_awaiting_user_input
from kendr.persistence import (
    get_channel_session,
    initialize_db,
    insert_agent_execution,
    insert_run,
    insert_run_checkpoint,
    update_run,
    upsert_channel_session,
    upsert_task_session,
)
from kendr.setup import build_setup_snapshot

from tasks.a2a_protocol import (
    append_artifact,
    append_message,
    append_task,
    complete_task,
    ensure_a2a_state,
    make_artifact,
    make_message,
    make_task,
    task_for_agent,
)
from tasks.file_memory import (
    append_daily_memory_note,
    append_long_term_memory,
    append_session_event,
    bootstrap_file_memory,
    close_session_memory,
    update_planning_file,
    update_session_file,
)
from tasks.privileged_control import append_privileged_audit_event, build_privileged_policy
from tasks.review_tasks import reviewer_agent
from tasks.utils import (
    OUTPUT_DIR,
    append_text_file,
    agent_model_context,
    create_run_output_dir,
    llm,
    log_task_update,
    logger,
    record_work_note,
    resolve_output_path,
    reset_text_file,
    set_active_output_dir,
    write_text_file,
)
from .recovery import write_recovery_files

from .registry import Registry


class AgentRuntime:
    def __init__(self, registry: Registry):
        self.registry = registry

    def _agent_cards(self) -> list[dict]:
        return self.registry.agent_cards()

    def _resolve_working_directory(self, state_overrides: dict | None = None) -> str:
        overrides = state_overrides or {}
        working_dir = str(overrides.get("working_directory") or overrides.get("KENDR_WORKING_DIR") or os.getenv("KENDR_WORKING_DIR", "")).strip()
        if not working_dir:
            raise RuntimeError(
                "Working folder is not configured. Set KENDR_WORKING_DIR in Setup UI (Core Runtime), "
                "or pass state_overrides['working_directory'] before running tasks."
            )
        resolved = Path(working_dir).expanduser().resolve()
        resolved.mkdir(parents=True, exist_ok=True)
        return str(resolved)

    def _agent_descriptions(self) -> dict[str, str]:
        return self.registry.agent_descriptions()

    def apply_runtime_setup(self, state: dict) -> dict:
        snapshot = build_setup_snapshot(self._agent_cards())
        available_agents = snapshot.get("available_agents", [])
        filtered_cards = [card for card in self._agent_cards() if card["agent_name"] in available_agents]
        state["setup_status"] = snapshot
        state["available_agents"] = available_agents
        state["disabled_agents"] = snapshot.get("disabled_agents", {})
        state["setup_actions"] = snapshot.get("setup_actions", [])
        state["setup_summary"] = snapshot.get("summary_text", "")
        state["available_agent_cards"] = filtered_cards
        ensure_a2a_state(state, filtered_cards)
        return state

    _DEFAULT_MAX_CONSECUTIVE_FAILURES = 3
    _DEFAULT_MAX_SAME_AGENT_DISPATCHES = 5
    _NON_REVIEW_AGENTS = {
        "channel_gateway_agent",
        "session_router_agent",
    }

    def _is_agent_available(self, state: dict, agent_name: str) -> bool:
        if agent_name in (state.get("_circuit_broken_agents") or {}):
            return False
        return agent_name in set(state.get("available_agents", []))

    # ------------------------------------------------------------------
    # Stuck-agent detection and circuit breaker
    # ------------------------------------------------------------------

    def _record_agent_failure(self, state: dict, agent_name: str, error_message: str) -> None:
        failures = state.setdefault("_consecutive_failures", {})
        record = failures.setdefault(agent_name, {"count": 0, "last_error": ""})
        record["count"] += 1
        record["last_error"] = str(error_message)[:500]
        max_failures = int(state.get("max_consecutive_agent_failures", self._DEFAULT_MAX_CONSECUTIVE_FAILURES))
        if record["count"] >= max_failures:
            broken = state.setdefault("_circuit_broken_agents", {})
            broken[agent_name] = {
                "reason": f"Agent failed {record['count']} consecutive times. Last error: {record['last_error']}",
                "failure_count": record["count"],
            }
            logger.warning(
                "Circuit breaker tripped for %s after %d consecutive failures: %s",
                agent_name, record["count"], record["last_error"],
            )

    def _clear_agent_failures(self, state: dict, agent_name: str) -> None:
        failures = state.get("_consecutive_failures", {})
        failures.pop(agent_name, None)

    def _is_stuck_on_agent(self, state: dict, agent_name: str) -> bool:
        history = state.get("agent_history", [])
        max_same = int(state.get("max_same_agent_dispatches", self._DEFAULT_MAX_SAME_AGENT_DISPATCHES))
        if len(history) < max_same:
            return False
        recent = history[-max_same:]
        return all(entry.get("agent") == agent_name for entry in recent)

    def _stuck_agent_message(self, state: dict, agent_name: str) -> str:
        failures = (state.get("_consecutive_failures") or {}).get(agent_name, {})
        broken = (state.get("_circuit_broken_agents") or {}).get(agent_name, {})
        parts = [f"Agent '{agent_name}' appears stuck in a dispatch loop."]
        last_error = str(failures.get("last_error", "") or "")
        if last_error:
            parts.append(f"Last error: {last_error}")
        if broken.get("reason"):
            parts.append(f"Circuit breaker: {broken['reason']}")
        guidance = self._stuck_agent_guidance(last_error)
        if guidance:
            parts.append(guidance)
        return " ".join(parts)

    def _stuck_agent_guidance(self, last_error: str) -> str:
        error = (last_error or "").strip().lower()
        if not error:
            return (
                "Cause is unknown. Check recent agent output files in the run directory and retry once "
                "to distinguish transient failures from deterministic contract issues."
            )
        if "no module named" in error or "modulenotfounderror" in error:
            return (
                "Likely packaging/import issue in the installed environment. Reinstall the package "
                "(`pip install -e .`) and verify the missing module is included in pyproject package discovery."
            )
        if "requires '" in error or ("requires" in error and "in state" in error):
            return (
                "Likely agent input-contract mismatch. The routed step did not provide required state keys "
                "for this agent; fix planner/orchestrator state_updates or add safe fallbacks in the agent."
            )
        if "api_key" in error or "serp_api_key" in error or "openai_api_key" in error:
            return (
                "Likely missing credentials. Verify required API keys are configured in env/setup and "
                "available to the runtime process."
            )
        if "outside allowed scope" in error or "read-only mode" in error or "permission" in error:
            return (
                "Likely permission/scope policy issue. Check privileged mode settings, allowed paths, "
                "and write permissions for the working directory."
            )
        if "database is locked" in error:
            return (
                "Likely SQLite lock contention in setup/persistence storage. Close concurrent runtime processes "
                "or increase DB timeout/retry handling."
            )
        if "timeout" in error or "timed out" in error:
            return (
                "Likely network/provider timeout. Check connectivity, provider health, and timeout limits."
            )
        return (
            "This may be a provider/runtime issue, but deterministic code or state problems are also possible. "
            "Inspect the last error and per-agent output artifacts before retrying."
        )

    def _available_agent_descriptions(self, state: dict) -> dict[str, str]:
        available = set(state.get("available_agents", []))
        return {name: description for name, description in self._agent_descriptions().items() if name in available}

    def _agent_enum(self, state: dict, include_finish: bool = False) -> str:
        choices = list(state.get("available_agents", []))
        if include_finish:
            choices.append("finish")
        return "|".join(choices)

    def _truncate(self, text: str, limit: int = 1200) -> str:
        cleaned = " ".join((text or "").split())
        if len(cleaned) <= limit:
            return cleaned
        return cleaned[: limit - 3] + "..."

    def _awaiting_user_input(self, state: Mapping[str, Any]) -> bool:
        return state_awaiting_user_input(state)

    def _interpret_user_input_response(self, text: str) -> dict[str, str]:
        raw = str(text or "").strip()
        lowered = raw.lower()
        if not raw:
            return {"action": "unclear", "feedback": ""}

        revise_markers = (
            "change",
            "modify",
            "revise",
            "rework",
            "recreate",
            "adjust",
            "update",
            "replace",
            "instead",
            "add ",
            "remove ",
            "expand",
            "reduce",
            "rewrite",
            "fix",
            "not ",
            "don't",
            "do not",
        )
        approve_markers = (
            "approve",
            "approved",
            "go ahead",
            "proceed",
            "continue",
            "start",
            "execute",
            "looks good",
            "lgtm",
        )
        cleaned = lowered.strip(" \n\t.!?")
        if cleaned in {"no", "n"} or any(marker in lowered for marker in revise_markers):
            return {"action": "revise", "feedback": raw}
        if cleaned in {"approve", "approved", "yes", "y"} or any(cleaned.startswith(marker) for marker in approve_markers):
            return {"action": "approve", "feedback": raw}
        return {"action": "unclear", "feedback": raw}

    def _task_activity_label(self, agent_name: str, intent: str) -> str:
        intent_map = {
            "channel-ingest-normalization": "Normalize the incoming channel payload for orchestration.",
            "session-routing": "Resolve or create the session context for this run.",
            "local-drive-ingestion": "Scan the configured drive files and extract the most relevant evidence.",
            "drive-informed-long-document": "Draft the long-form report from the ingested drive evidence.",
            "planning": "Build the execution plan for this request.",
            "step-review": "Review the latest agent output and decide whether it should continue.",
            "correction": "Revise the previous step based on reviewer feedback.",
            "planned-step": f"Execute the next planned step with {agent_name or 'the assigned agent'}.",
            "run-generated-agent": "Run the generated agent task.",
            "project-audit-dispatch": "Run the structured codebase audit workflow.",
            "superrag-dispatch": "Build or query the superRAG knowledge session.",
            "deep-research-dispatch": "Run the deep research workflow and collect cited findings.",
            "long-document-dispatch": "Generate the long-form document section by section.",
            "master-coding-delegation": f"Continue the delegated coding workflow with {agent_name or 'the assigned agent'}.",
            "project-blueprint": "Designing the complete technical architecture for the project.",
        }
        if intent in intent_map:
            return intent_map[intent]
        agent_map = {
            "channel_gateway_agent": "Normalizing the incoming request payload.",
            "session_router_agent": "Resolving the session context.",
            "local_drive_agent": "Scanning drive files and extracting relevant evidence.",
            "long_document_agent": "Generating long-form report sections and merging the draft.",
            "planner_agent": "Planning the execution steps.",
            "reviewer_agent": "Reviewing the latest step output.",
            "deep_research_agent": "Running deep research and collecting cited sources.",
            "superrag_agent": "Working on the superRAG knowledge session.",
            "worker_agent": "Executing the assigned work item.",
        }
        return agent_map.get(agent_name, "")

    def _active_task_summary(self, state: Mapping[str, Any], active_task: dict | None = None) -> str:
        task = active_task if isinstance(active_task, dict) else state.get("active_task", {})
        if not isinstance(task, dict):
            task = {}
        if self._awaiting_user_input(state):
            pending = " ".join(str(state.get("pending_user_question", "") or "").split())
            if pending:
                return self._truncate(pending, 240)
        content = " ".join(str(task.get("content", "") or "").split())
        objective = " ".join(str(state.get("current_objective", "") or "").split())
        user_query = " ".join(str(state.get("user_query", "") or "").split())
        agent_name = " ".join(str(task.get("recipient", "") or state.get("last_agent", "") or "").split())
        intent = " ".join(str(task.get("intent", "") or "").split())
        label = self._task_activity_label(agent_name, intent)

        if not task:
            if label:
                return self._truncate(label, 240)
            if objective or user_query:
                return "Preparing the run request and waiting for the first agent dispatch."
            return ""

        generic_content = not content or content in {objective, user_query}
        if label and generic_content:
            return self._truncate(label, 240)
        if content:
            return self._truncate(content, 240)
        if label:
            return self._truncate(label, 240)
        fallback = " ".join(str(state.get("active_agent_task", "") or "").split())
        if fallback:
            return self._truncate(fallback, 240)
        if objective:
            return self._truncate(objective, 240)
        if user_query:
            return self._truncate(user_query, 240)
        return ""

    def _plan_step_summary(self, state: Mapping[str, Any]) -> dict:
        steps = state.get("plan_steps", [])
        index = int(state.get("plan_step_index", 0) or 0)
        if not isinstance(steps, list):
            return {"plan_steps": [], "plan_step_index": index, "plan_step_total": 0}
        summarized: list[dict[str, str]] = []
        for step in steps:
            if not isinstance(step, dict):
                continue
            step_id = str(step.get("id") or "").strip()
            title = str(step.get("title") or step.get("task") or step_id or "").strip()
            agent = str(step.get("agent") or "").strip()
            if not (step_id or title or agent):
                continue
            summarized.append({"id": step_id, "title": title, "agent": agent})
        total = len(summarized)
        return {
            "plan_steps": summarized,
            "plan_step_index": max(0, index),
            "plan_step_total": total,
        }

    def _is_project_build_request(self, state: dict) -> bool:
        text = " ".join([
            str(state.get("user_query", "")),
            str(state.get("current_objective", "")),
        ]).lower()
        build_markers = (
            "build me a", "build an app", "build a project", "create a project",
            "create an app", "create a web app", "scaffold a", "generate a project",
            "full-stack app", "fullstack app", "new project", "build a web",
            "build a website", "build a saas", "build a platform", "create a platform",
            "build a dashboard", "create a dashboard", "create a backend", "build a backend",
            "create an api", "build an api", "build me an application",
        )
        if any(marker in text for marker in build_markers):
            return True
        framework_signals = ("react", "next.js", "nextjs", "fastapi", "express", "django", "flask", "vue", "angular", "svelte")
        build_intents = ("build", "create", "scaffold", "generate", "set up", "setup", "bootstrap", "start")
        return any(fw in text for fw in framework_signals) and any(i in text for i in build_intents)

    def _is_project_audit_request(self, state: dict) -> bool:
        text = " ".join(
            [
                str(state.get("user_query", "")),
                str(state.get("current_objective", "")),
            ]
        ).lower()
        markers = (
            "production ready",
            "production-ready",
            "codebase",
            "repository",
            "repo",
            "analyze my project",
            "analyze my code",
            "audit project",
            "fixation required",
        )
        return any(marker in text for marker in markers)

    def _read_file_excerpt(self, path: Path, limit: int = 5000) -> str:
        try:
            raw = path.read_text(encoding="utf-8")
        except Exception:
            return ""
        if len(raw) <= limit:
            return raw
        return raw[:limit] + "\n... [truncated]"

    def _build_repo_scan_summary(self, working_directory: str) -> str:
        root = Path(working_directory).resolve()
        if not root.exists():
            return f"Working directory does not exist: {root}"
        top_entries = sorted(p.name for p in root.iterdir())[:60]
        important_patterns = [
            "README.md",
            "pyproject.toml",
            "requirements.txt",
            "package.json",
            "Dockerfile",
            "docker-compose.yml",
            "Makefile",
            ".env.example",
        ]
        sections = [
            f"Repository root: {root}",
            f"Top-level entries ({len(top_entries)} shown): {top_entries}",
        ]
        for pattern in important_patterns:
            path = root / pattern
            if not path.exists() or not path.is_file():
                continue
            excerpt = self._read_file_excerpt(path, limit=6000)
            if excerpt:
                sections.append(f"\n=== {path.name} ===\n{excerpt}")

        py_files = sorted([p for p in root.rglob("*.py") if ".venv" not in p.parts and ".deps" not in p.parts])[:120]
        if py_files:
            rel_paths = [str(p.relative_to(root)) for p in py_files[:120]]
            sections.append(f"\nPython files sampled ({len(rel_paths)}):\n" + "\n".join(rel_paths))
        return "\n".join(sections)

    def _history_as_text(self, state: dict) -> str:
        history = state.get("agent_history", [])
        if not history:
            return "No agents have run yet."
        return "\n".join(
            f"- {item['agent']} ({item['status']}): reason={item['reason']} output={item['output_excerpt']}"
            for item in history[-6:]
        )

    def _recent_event_summary(self, state: dict, limit: int = 6) -> list[str]:
        events = state.get("recent_events", [])
        if not isinstance(events, list) or not events:
            return []
        lines: list[str] = []
        for item in events[-limit:]:
            if not isinstance(item, dict):
                continue
            actor = str(item.get("actor", "")).strip() or "system"
            event = str(item.get("event", "")).strip() or "event"
            detail = str(item.get("detail", "")).strip()
            if detail:
                detail = self._truncate(detail, 140)
                lines.append(f"{actor}: {event} · {detail}")
            else:
                lines.append(f"{actor}: {event}")
        return lines

    def _recent_a2a_messages(self, state: dict) -> str:
        ensure_a2a_state(state, state.get("available_agent_cards") or self._agent_cards())
        messages = state["a2a"]["messages"]
        if not messages:
            return "No A2A messages yet."
        return "\n".join(
            f"- {item['sender']} -> {item['recipient']} [{item['role']}]: {self._truncate(item['content'], 240)}"
            for item in messages[-8:]
        )

    def _append_history(self, state: dict, agent_name: str, status: str, reason: str, output_text: str) -> dict:
        timestamp = datetime.now(timezone.utc).isoformat()
        history = state.get("agent_history", [])
        history.append(
            {
                "timestamp": timestamp,
                "agent": agent_name,
                "status": status,
                "reason": reason,
                "output_excerpt": self._truncate(output_text),
            }
        )
        state["agent_history"] = history
        state["last_agent"] = agent_name
        state["last_agent_status"] = status
        state["last_agent_output"] = output_text
        run_id = state.get("run_id")
        if run_id:
            insert_agent_execution(run_id, timestamp, agent_name, status, reason, self._truncate(output_text))
        self._write_session_record(state, status="running", active_agent=agent_name)
        return state

    def _session_payload(self, state: RuntimeState, *, status: str, active_agent: str = "", completed_at: str = "") -> dict:
        channel_session = state.get("channel_session", {}) if isinstance(state.get("channel_session"), dict) else {}
        plan_summary = self._plan_step_summary(state)
        return {
            "session_id": state.get("session_id", ""),
            "run_id": state.get("run_id", ""),
            "channel": state.get("incoming_channel", ""),
            "session_key": channel_session.get("session_key", ""),
            "started_at": state.get("session_started_at", ""),
            "updated_at": datetime.now(timezone.utc).isoformat(),
            "completed_at": completed_at,
            "status": status,
            "active_agent": active_agent,
            "step_count": self._display_step_count(state, status=status, active_agent=active_agent),
            "summary": {
                "objective": state.get("current_objective", ""),
                "last_agent": state.get("last_agent", ""),
                "last_status": state.get("last_agent_status", ""),
                "last_error": state.get("last_error", ""),
                "active_task": self._active_task_summary(state),
                "awaiting_user_input": state_awaiting_user_input(state),
                "pending_user_input_kind": state.get("pending_user_input_kind", ""),
                "approval_pending_scope": state.get("approval_pending_scope", ""),
                "pending_user_question": state.get("pending_user_question", ""),
                "plan_approval_status": state.get("plan_approval_status", ""),
                "plan_steps": plan_summary.get("plan_steps", []),
                "plan_step_index": plan_summary.get("plan_step_index", 0),
                "plan_step_total": plan_summary.get("plan_step_total", 0),
                "recent_events": self._recent_event_summary(state),
            },
        }

    def _display_step_count(self, state: Mapping[str, Any], *, status: str, active_agent: str = "") -> int:
        completed_steps = int(state.get("effective_steps", 0) or 0)
        history = state.get("agent_history", [])
        history_count = len(history) if isinstance(history, list) else 0
        baseline = max(completed_steps, history_count)

        if str(status or "").strip().lower() == "running" and str(active_agent or "").strip():
            last_agent = str(state.get("last_agent", "") or "").strip()
            if last_agent and last_agent == str(active_agent).strip():
                return baseline
            return baseline + 1
        return baseline

    def _write_session_record(self, state: RuntimeState, *, status: str, active_agent: str = "", completed_at: str = "") -> None:
        if not state.get("session_id"):
            return
        upsert_task_session(self._session_payload(state, status=status, active_agent=active_agent, completed_at=completed_at))
        note_parts = [
            f"status={status}",
            f"active_agent={active_agent or state.get('last_agent', '')}",
        ]
        active_task = self._active_task_summary(state)
        if active_task:
            note_parts.append(f"active_task={active_task}")
        note = "\n".join(note_parts)
        update_session_file(state, status=status, active_agent=active_agent, note=note)
        append_session_event(state, "runtime", "session_status", note)
        self._write_channel_session_progress(state, status=status, active_agent=active_agent, completed_at=completed_at)
        self._persist_recovery_state(state, status=status, active_agent=active_agent, completed_at=completed_at)

    def _base_channel_session_key(self, state: Mapping[str, Any]) -> str:
        key = str(state.get("channel_session_key", "")).strip()
        if key:
            return key
        channel = str(state.get("incoming_channel", "webchat") or "webchat").strip().lower()
        workspace_id = str(state.get("incoming_workspace_id", "") or "default").strip()
        sender_id = str(state.get("incoming_sender_id", "") or "unknown").strip()
        chat_id = str(state.get("incoming_chat_id", "") or sender_id or "unknown").strip()
        scope = "group" if bool(state.get("incoming_is_group", False)) else "main"
        return ":".join([channel, workspace_id, chat_id, scope])

    def _write_channel_session_progress(self, state: RuntimeState, *, status: str, active_agent: str = "", completed_at: str = "") -> None:
        session_key = self._base_channel_session_key(state)
        if not session_key:
            return
        previous = get_channel_session(session_key) or {}
        previous_state = previous.get("state", {}) if isinstance(previous, dict) else {}
        if not isinstance(previous_state, dict):
            previous_state = {}
        history = previous_state.get("history", [])
        if not isinstance(history, list):
            history = []
        if status == "completed":
            history.append(
                {
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "run_id": state.get("run_id", ""),
                    "objective": state.get("current_objective", state.get("user_query", "")),
                    "final_output": self._truncate(state.get("final_output") or state.get("draft_response") or "", 600),
                }
            )
            history = history[-20:]
        session_payload = {
            "session_key": session_key,
            "channel": state.get("incoming_channel", ""),
            "chat_id": state.get("incoming_chat_id", ""),
            "sender_id": state.get("incoming_sender_id", ""),
            "workspace_id": state.get("incoming_workspace_id", ""),
            "is_group": bool(state.get("incoming_is_group", False)),
            "updated_at": datetime.now(timezone.utc).isoformat(),
            "state": {
                **previous_state,
                "last_text": state.get("user_query", ""),
                "last_run_id": state.get("run_id", ""),
                "last_objective": state.get("current_objective", state.get("user_query", "")),
                "last_plan": state.get("plan", ""),
                "last_plan_data": state.get("plan_data", {}),
                "last_plan_steps": state.get("plan_steps", []),
                "last_plan_step_index": int(state.get("plan_step_index", 0) or 0),
                "plan_waiting_for_approval": bool(state.get("plan_waiting_for_approval", False)),
                "plan_approval_status": state.get("plan_approval_status", ""),
                "plan_revision_feedback": state.get("plan_revision_feedback", ""),
                "plan_revision_count": int(state.get("plan_revision_count", 0) or 0),
                "plan_version": int(state.get("plan_version", 0) or 0),
                "planning_notes": state.get("planning_notes", []),
                "review_revision_counts": state.get("review_revision_counts", {}),
                "blueprint_json": state.get("blueprint_json", {}),
                "blueprint_summary": state.get("blueprint_summary", ""),
                "blueprint_status": state.get("blueprint_status", ""),
                "blueprint_version": int(state.get("blueprint_version", 0) or 0),
                "blueprint_waiting_for_approval": bool(state.get("blueprint_waiting_for_approval", False)),
                "blueprint_tech_stack": state.get("blueprint_tech_stack", {}),
                "blueprint_db_schema": state.get("blueprint_db_schema", {}),
                "blueprint_api_design": state.get("blueprint_api_design", {}),
                "blueprint_frontend_components": state.get("blueprint_frontend_components", {}),
                "blueprint_directory_structure": state.get("blueprint_directory_structure", []),
                "blueprint_dependencies": state.get("blueprint_dependencies", {}),
                "blueprint_env_vars": state.get("blueprint_env_vars", []),
                "blueprint_docker_services": state.get("blueprint_docker_services", []),
                "project_name": state.get("project_name", ""),
                "project_root": state.get("project_root", ""),
                "project_stack": state.get("project_stack", ""),
                "last_status": status,
                "last_active_agent": active_agent or state.get("last_agent", ""),
                "last_error": state.get("last_error", ""),
                "failure_checkpoint": state.get("failure_checkpoint", {}),
                "completed_at": completed_at,
                "awaiting_user_input": state_awaiting_user_input(state),
                "pending_user_input_kind": state.get("pending_user_input_kind", ""),
                "approval_pending_scope": state.get("approval_pending_scope", ""),
                "pending_user_question": state.get("pending_user_question", ""),
                "long_document_plan_waiting_for_approval": bool(state.get("long_document_plan_waiting_for_approval", False)),
                "long_document_plan_status": state.get("long_document_plan_status", ""),
                "long_document_plan_feedback": state.get("long_document_plan_feedback", ""),
                "long_document_plan_revision_count": int(state.get("long_document_plan_revision_count", 0) or 0),
                "long_document_plan_markdown": state.get("long_document_plan_markdown", ""),
                "long_document_plan_data": state.get("long_document_plan_data", {}),
                "long_document_plan_version": int(state.get("long_document_plan_version", 0) or 0),
                "long_document_outline": state.get("long_document_outline", {}),
                "superrag_active_session_id": state.get("superrag_active_session_id", ""),
                "history": history,
            },
        }
        upsert_channel_session(session_key, session_payload)
        state["channel_session"] = session_payload

    def _persist_recovery_state(self, state: RuntimeState, *, status: str, active_agent: str = "", completed_at: str = "") -> None:
        run_id = str(state.get("run_id", "")).strip()
        if not run_id:
            return
        payloads = write_recovery_files(
            state,
            status=status,
            active_agent=active_agent,
            completed_at=completed_at,
        )
        checkpoint = payloads.get("checkpoint", {}) if isinstance(payloads, dict) else {}
        checkpoint_json = json.dumps(checkpoint, ensure_ascii=False) if checkpoint else ""
        resumable = False
        if isinstance(checkpoint, dict):
            summary = checkpoint.get("summary", {}) if isinstance(checkpoint.get("summary"), dict) else {}
            resumable = bool(summary.get("resumable", False))
        update_run(
            run_id,
            status=status,
            updated_at=datetime.now(timezone.utc).isoformat(),
            working_directory=str(state.get("working_directory", "")).strip(),
            run_output_dir=str(state.get("run_output_dir", "")).strip(),
            session_id=str(state.get("session_id", "")).strip(),
            parent_run_id=str(state.get("parent_run_id", "")).strip(),
            resumable=resumable,
            checkpoint_json=checkpoint_json,
        )
        if checkpoint:
            insert_run_checkpoint(
                {
                    "checkpoint_id": f"{run_id}_{uuid.uuid4().hex}",
                    "run_id": run_id,
                    "created_at": datetime.now(timezone.utc).isoformat(),
                    "checkpoint_kind": "session_update",
                    "step_index": int(state.get("plan_step_index", 0) or 0),
                    "status": status,
                    "data": checkpoint,
                }
            )

    def _infer_agent_output(self, before: dict, after: dict) -> str:
        if after.get("draft_response") and after.get("draft_response") != before.get("draft_response"):
            return str(after.get("draft_response", ""))
        preferred_suffixes = ("_summary", "_report", "_analysis", "_result", "_results", "_profile", "_plan", "_output")
        changed = []
        before_keys = set(before.keys())
        for key, value in after.items():
            if key.startswith("_") or key in {"a2a", "available_agent_cards", "setup_status"}:
                continue
            if before.get(key) != value:
                changed.append((key, value, key not in before_keys))
        for key, value, _ in changed:
            if key.endswith(preferred_suffixes):
                if isinstance(value, str):
                    return value
                return json.dumps(value, ensure_ascii=False)
        if changed:
            key, value, _ = changed[0]
            if isinstance(value, str):
                return value
            return json.dumps({key: value}, ensure_ascii=False)
        return ""

    def _handle_unavailable_agent_choice(self, state: dict, agent_name: str, reason: str) -> tuple[str, str]:
        if agent_name == "finish" or self._is_agent_available(state, agent_name):
            return agent_name, reason
        setup_actions = json.dumps(state.get("setup_actions", []), ensure_ascii=False)
        if self._is_agent_available(state, "agent_factory_agent"):
            state["missing_capability"] = agent_name
            return (
                "agent_factory_agent",
                f"{reason} Requested capability maps to unavailable agent {agent_name}. Create a new agent or scaffold for this gap. Setup actions: {setup_actions}",
            )
        if self._is_agent_available(state, "worker_agent"):
            return (
                "worker_agent",
                f"{reason} Requested agent {agent_name} is not configured. Explain missing setup and available actions: {setup_actions}",
            )
        return "finish", reason

    def _strip_code_fences(self, text: str) -> str:
        stripped = text.strip()
        if stripped.startswith("```") and stripped.endswith("```"):
            lines = stripped.splitlines()
            if len(lines) >= 2:
                return "\n".join(lines[1:-1]).strip()
        return stripped

    def _parse_orchestrator_output(self, raw_output: str) -> dict:
        return json.loads(self._strip_code_fences(raw_output))

    def _is_deep_research_request(self, state: dict) -> bool:
        text = " ".join(
            [
                state.get("user_query", ""),
                state.get("current_objective", ""),
                state.get("research_query", ""),
            ]
        ).lower()
        if not text.strip():
            return False

        explicit_markers = (
            "deep research",
            "deep-research",
            "in-depth research",
            "comprehensive research",
            "extensive research",
            "thorough research",
        )
        if any(marker in text for marker in explicit_markers):
            return True

        citation_markers = ("with citations", "cite sources", "source-backed", "source backed")
        research_markers = ("research", "investigate", "investigation", "literature review", "prior art")
        return any(marker in text for marker in citation_markers) and any(marker in text for marker in research_markers)

    def _is_superrag_request(self, state: dict) -> bool:
        superrag_keys = (
            "superrag_mode",
            "superrag_action",
            "superrag_session_id",
            "superrag_urls",
            "superrag_local_paths",
            "superrag_db_url",
            "superrag_chat_query",
            "superrag_onedrive_enabled",
            "superrag_onedrive_path",
        )
        if any(state.get(key) for key in superrag_keys):
            return True

        text = " ".join(
            [
                str(state.get("user_query", "")),
                str(state.get("current_objective", "")),
            ]
        ).lower()
        if not text.strip():
            return False

        markers = (
            "superrag",
            "rag session",
            "session based rag",
            "index my data",
            "index my documents",
            "knowledge base from",
            "chat with my data",
            "vector db",
            "embeddings",
            "onedrive",
            "database url",
        )
        return any(marker in text for marker in markers)

    def _is_local_command_request(self, state: dict) -> bool:
        explicit_keys = ("os_command", "target_os", "shell", "os_working_directory", "os_timeout")
        if any(state.get(key) for key in explicit_keys):
            return True

        text = " ".join(
            [
                str(state.get("user_query", "")),
                str(state.get("current_objective", "")),
            ]
        ).lower()
        if not text.strip():
            return False

        markers = (
            "run this command",
            "execute this command",
            "run a shell command",
            "execute a shell command",
            "execute in terminal",
            "run in terminal",
            "powershell command",
            "bash command",
            "cmd /c",
        )
        return any(marker in text for marker in markers)

    def _is_long_document_request(self, state: dict) -> bool:
        if bool(state.get("long_document_mode", False)):
            return True

        requested_pages = int(state.get("long_document_pages", 0) or 0)
        if requested_pages >= 20:
            return True

        text = " ".join(
            [
                str(state.get("user_query", "")),
                str(state.get("current_objective", "")),
            ]
        ).lower()
        if not text.strip():
            return False

        direct_markers = (
            "long document",
            "long-form document",
            "book chapter",
            "whitepaper",
            "monograph",
            "50 page",
            "50-page",
            "100 page",
            "100-page",
            "exhaustive report",
        )
        if any(marker in text for marker in direct_markers):
            return True

        has_page_signal = "page" in text or "pages" in text
        has_length_signal = any(token in text for token in ("very long", "exhaustive", "chapter by chapter", "multi-part"))
        return has_page_signal and has_length_signal

    def _has_local_drive_request(self, state: dict) -> bool:
        raw = (
            state.get("local_drive_paths")
            or state.get("knowledge_drive_paths")
            or state.get("drive_paths")
            or state.get("document_root_paths")
            or []
        )
        if isinstance(raw, str):
            return bool(raw.strip())
        if isinstance(raw, list):
            return any(str(item or "").strip() for item in raw)
        return False

    def _kill_switch_triggered(self, state: dict) -> bool:
        policy = build_privileged_policy(state)
        path_value = str(policy.get("kill_switch_file", "")).strip()
        if not path_value:
            return False
        try:
            return Path(path_value).expanduser().resolve().exists()
        except Exception:
            return False

    def _looks_like_resume_request(self, text: str) -> bool:
        query = str(text or "").strip().lower()
        if not query:
            return False
        markers = ("resume", "continue", "retry", "start from", "pick up", "carry on")
        return any(marker in query for marker in markers)

    def _resume_block_reason(self, error_message: str) -> str:
        message = str(error_message or "").strip().lower()
        blockers = {
            "not configured": "missing setup/configuration for the failed agent",
            "api key": "required API credentials are missing",
            "permission": "permission/authorization was denied",
            "unauthorized": "authorization failed",
            "forbidden": "authorization failed",
            "kill switch": "kill switch is enabled",
            "working folder is not configured": "working directory is not configured",
        }
        for marker, reason in blockers.items():
            if marker in message:
                return reason
        return ""

    def _build_failure_checkpoint(self, state: dict, agent_name: str, error_message: str, active_task: dict | None) -> dict:
        step_index = int(state.get("plan_step_index", 0) or 0)
        block_reason = self._resume_block_reason(error_message)
        can_resume = not bool(block_reason)
        return {
            "failed_at": datetime.now(timezone.utc).isoformat(),
            "agent": agent_name,
            "step_index": step_index,
            "task_id": active_task.get("task_id") if isinstance(active_task, dict) else "",
            "task_content": active_task.get("content") if isinstance(active_task, dict) else "",
            "error": error_message,
            "can_resume": can_resume,
            "block_reason": block_reason,
        }

    def _next_planned_agents(self, state: dict) -> list[dict]:
        steps = state.get("plan_steps", [])
        if not isinstance(steps, list) or not steps:
            return []
        index = int(state.get("plan_step_index", 0) or 0)
        if index < 0 or index >= len(steps):
            return []
        current = steps[index]
        if not isinstance(current, dict):
            return []
        group = str(current.get("parallel_group") or "").strip()
        if not group:
            return [current]
        batch = [current]
        cursor = index + 1
        while cursor < len(steps):
            candidate = steps[cursor]
            if not isinstance(candidate, dict):
                break
            if str(candidate.get("parallel_group") or "").strip() != group:
                break
            batch.append(candidate)
            cursor += 1
        return batch

    def _quality_gate_report(self, state: dict) -> tuple[bool, str]:
        if not bool(state.get("project_build_mode", False)):
            return True, ""
        if not bool(state.get("enforce_quality_gate", True)):
            return True, ""

        checks = [
            ("tests", state.get("test_agent_status"), {"passed", "pass", "ok", "completed"}),
            ("security_scan", state.get("security_scan_status"), {"passed", "pass", "ok", "completed"}),
            ("verifier", state.get("verifier_status"), {"pass", "passed", "ok", "completed"}),
        ]
        lines = ["Quality gate checks:"]
        all_ok = True
        for name, value, ok_values in checks:
            status = str(value or "missing").strip().lower() or "missing"
            ok = status in ok_values
            all_ok = all_ok and ok
            lines.append(f"- {name}: {status}")
        return all_ok, "\n".join(lines)

    def _mark_planned_step_complete(self, state: dict) -> None:
        completed_index = int(state.get("plan_step_index", 0) or 0) + 1
        total_steps = len(state.get("plan_steps", []) or [])
        completed_title = (
            state.get("last_completed_plan_step_title")
            or state.get("planned_active_step_title")
            or state.get("current_plan_step_title")
            or state.get("planned_active_step_id")
            or "planned step"
        )
        log_task_update("Plan", f"Completed step {completed_index}/{total_steps}: {completed_title}.")
        state["plan_step_index"] = completed_index
        state["plan_execution_count"] = int(state.get("plan_execution_count", 0) or 0) + 1
        update_planning_file(
            state,
            status="executing",
            objective=state.get("current_objective", state.get("user_query", "")),
            plan_text=state.get("plan", ""),
            clarifications=state.get("plan_clarification_questions", []),
            execution_note=(
                f"Executed step index {state.get('plan_step_index', 0)} "
                f"via agent {state.get('last_agent', '')}."
            ),
        )

    def _review_revision_key(self, step_id: str, agent_name: str) -> str:
        resolved_step = str(step_id or "").strip() or "adhoc-step"
        resolved_agent = str(agent_name or "").strip() or "unknown-agent"
        return f"{resolved_step}|{resolved_agent}"

    def _record_review_revision(self, state: dict, *, step_id: str, agent_name: str) -> int:
        counts = state.get("review_revision_counts", {})
        if not isinstance(counts, dict):
            counts = {}
        key = self._review_revision_key(step_id, agent_name)
        next_count = int(counts.get(key, 0) or 0) + 1
        counts[key] = next_count
        state["review_revision_counts"] = counts
        state["revision_count"] = next_count
        return next_count

    def _clear_review_revision(self, state: dict, *, step_id: str, agent_name: str) -> None:
        counts = state.get("review_revision_counts", {})
        if not isinstance(counts, dict):
            return
        key = self._review_revision_key(step_id, agent_name)
        if key in counts:
            counts.pop(key, None)
            state["review_revision_counts"] = counts
        state["revision_count"] = 0

    def _execute_agent(self, state: dict, agent_name: str) -> dict:
        if self._kill_switch_triggered(state):
            raise RuntimeError("Kill switch triggered. Refusing further execution.")
        state = self.apply_runtime_setup(state)
        if not self._is_agent_available(state, agent_name):
            unavailable_reason = (
                f"{agent_name} is not configured in the current environment. "
                f"Missing setup: {json.dumps(state.get('disabled_agents', {}).get(agent_name, {}), ensure_ascii=False)}"
            )
            state["last_error"] = unavailable_reason
            state["review_pending"] = False
            state["failure_checkpoint"] = self._build_failure_checkpoint(state, agent_name, unavailable_reason, state.get("active_task"))
            return self._append_history(state, agent_name, "skipped", state.get("orchestrator_reason", ""), unavailable_reason)

        spec = self.registry.agents[agent_name]
        log_task_update("System", f"Dispatching to {agent_name}.")
        ensure_a2a_state(state, state.get("available_agent_cards") or self._agent_cards())
        active_task = task_for_agent(state, agent_name)
        if not active_task:
            active_task = make_task(
                sender="orchestrator_agent",
                recipient=agent_name,
                intent="fallback-dispatch",
                content=state.get("orchestrator_reason", "No explicit task content was provided."),
            )
            state = append_task(state, active_task)

        state["active_task"] = active_task
        state["active_agent_task"] = self._active_task_summary(state, active_task)
        append_daily_memory_note(
            state,
            "orchestrator_agent",
            "dispatch",
            f"agent={agent_name}\ntask_id={active_task['task_id']}\nintent={active_task.get('intent', '')}",
        )
        append_session_event(
            state,
            "orchestrator_agent",
            "dispatch",
            f"agent={agent_name}\ntask_id={active_task['task_id']}\nintent={active_task.get('intent', '')}",
        )
        record_work_note(
            state,
            "orchestrator_agent",
            "dispatch",
            (
                f"agent={agent_name}\n"
                f"task_id={active_task['task_id']}\n"
                f"intent={active_task.get('intent', '')}\n"
                f"content={active_task.get('content', '')}"
            ),
        )
        state = append_message(state, make_message(active_task["sender"], agent_name, "task", active_task["content"]))
        task_updates = active_task.get("state_updates", {})
        if isinstance(task_updates, dict):
            state.update(task_updates)
        self._write_session_record(state, status="running", active_agent=agent_name)

        before_state = {k: v for k, v in state.items() if k != "a2a"}
        try:
            with agent_model_context(agent_name):
                state = spec.handler(state)
            output_text = self._infer_agent_output(before_state, state)
            self._clear_agent_failures(state, agent_name)
            state["effective_steps"] = int(state.get("effective_steps", 0)) + 1
            if active_task.get("status") == "pending":
                state = complete_task(state, active_task["task_id"], "completed")
            skip_review = bool(state.pop("_skip_review_once", False))
            hold_step_completion = bool(state.pop("_hold_planned_step_completion_once", False))
            requires_review = (
                agent_name != "reviewer_agent"
                and agent_name not in self._NON_REVIEW_AGENTS
                and not skip_review
                and not bool(state.get("skip_reviews", False))
                and not self._awaiting_user_input(state)
            )
            state["review_pending"] = requires_review
            state = self._append_history(state, agent_name, "success", state.get("orchestrator_reason", ""), output_text)
            append_daily_memory_note(state, agent_name, "completed", self._truncate(output_text, 1000))
            append_session_event(state, agent_name, "completed", self._truncate(output_text, 600))
            if agent_name == str(state.get("planned_active_agent", "")).strip():
                state["last_completed_plan_step_id"] = str(state.get("planned_active_step_id", "")).strip()
                state["last_completed_plan_step_title"] = str(state.get("planned_active_step_title", "")).strip()
                state["last_completed_plan_step_success_criteria"] = str(state.get("planned_active_step_success_criteria", "")).strip()
                state["last_completed_plan_step_agent"] = str(agent_name).strip()
                if not hold_step_completion:
                    self._mark_planned_step_complete(state)
                state["planned_active_agent"] = ""
                state["planned_active_step_id"] = ""
                state["planned_active_step_title"] = ""
                state["planned_active_step_success_criteria"] = ""
        except Exception as exc:
            error_message = str(exc)
            state["last_error"] = error_message
            self._record_agent_failure(state, agent_name, error_message)
            state = complete_task(state, active_task["task_id"], "failed")
            state["review_pending"] = False
            state = append_message(state, make_message(agent_name, "orchestrator_agent", "error", error_message))
            state = append_artifact(
                state,
                make_artifact(
                    name=f"{agent_name}_error",
                    kind="error",
                    content=error_message,
                    metadata={"task_id": active_task["task_id"], "status": "failed"},
                ),
            )
            state = self._append_history(state, agent_name, "error", state.get("orchestrator_reason", ""), error_message)
            append_daily_memory_note(state, agent_name, "failed", self._truncate(error_message, 1000))
            append_session_event(state, agent_name, "failed", self._truncate(error_message, 600))
            record_work_note(state, agent_name, "failed", f"task_id={active_task['task_id']}\nerror={error_message}")
            log_task_update("System", f"{agent_name} failed.", error_message)
            state["failure_checkpoint"] = self._build_failure_checkpoint(state, agent_name, error_message, active_task)
        return state

    def orchestrator_agent(self, state: dict) -> dict:
        state["orchestrator_calls"] = state.get("orchestrator_calls", 0) + 1
        max_steps = state.get("max_steps", 20)
        # effective_steps counts only successful agent completions (the real work budget).
        # orchestrator_calls counts every orchestrator invocation including retries/failures.
        # max_steps gates on effective_steps so retries don't eat the user's budget.
        # A hard safety ceiling (3x max_steps) prevents infinite loops even if nothing succeeds.
        effective_steps = int(state.get("effective_steps", 0))
        hard_ceiling = max_steps * 3
        state = self.apply_runtime_setup(state)
        ensure_a2a_state(state, state.get("available_agent_cards") or self._agent_cards())
        current_objective = state.get("current_objective") or state.get("user_query", "")

        if bool(state.get("user_cancelled", False)):
            state["next_agent"] = "__finish__"
            state["final_output"] = (
                state.get("final_output")
                or "Run cancelled per user request."
            )
            state = append_message(state, make_message("orchestrator_agent", "user", "final", state["final_output"]))
            return state

        if effective_steps > max_steps:
            state["next_agent"] = "__finish__"
            state["final_output"] = (
                state.get("final_output")
                or state.get("draft_response")
                or state.get("last_agent_output")
                or "Reached the orchestration step limit without a better final answer."
            )
            return state

        if state["orchestrator_calls"] > hard_ceiling:
            state["next_agent"] = "__finish__"
            state["final_output"] = (
                state.get("final_output")
                or state.get("draft_response")
                or state.get("last_agent_output")
                or (
                    f"Reached the hard safety ceiling ({hard_ceiling} total orchestrator calls) "
                    f"with only {effective_steps} effective steps completed. "
                    "This usually indicates persistent network or LLM provider failures. "
                    "Check your connection and API keys, then retry."
                )
            )
            log_task_update(
                "Orchestrator",
                f"Hard ceiling reached: {state['orchestrator_calls']} calls, {effective_steps} effective steps.",
            )
            return state

        # --- Circuit breaker: abort if any agent has been tripped ---
        broken_agents = state.get("_circuit_broken_agents") or {}
        if broken_agents:
            last_agent = state.get("last_agent", "")
            if last_agent in broken_agents:
                state["next_agent"] = "__finish__"
                state["final_output"] = self._stuck_agent_message(state, last_agent)
                log_task_update("Orchestrator", f"Circuit breaker: aborting run due to {last_agent} failures.")
                return state

        # --- Stuck-agent detection: same agent dispatched N+ times in a row ---
        last_agent = state.get("last_agent", "")
        if last_agent and self._is_stuck_on_agent(state, last_agent):
            state["next_agent"] = "__finish__"
            state["final_output"] = self._stuck_agent_message(state, last_agent)
            log_task_update("Orchestrator", f"Stuck-agent detection: {last_agent} dispatched too many times consecutively.")
            return state

        if bool(state.get("resume_blocked", False)):
            failed = state.get("failure_checkpoint", {}) if isinstance(state.get("failure_checkpoint"), dict) else {}
            failed_agent = failed.get("agent", "unknown")
            failed_error = failed.get("error", state.get("last_error", ""))
            reason = state.get("resume_block_reason", "safe resume is not possible")
            message = (
                "Cannot resume from the failed checkpoint.\n"
                f"Reason: {reason}\n"
                f"Failed agent: {failed_agent}\n"
                f"Error: {failed_error}\n"
                "Fix the blocker and start a new run, or rerun with --new-session."
            )
            state["next_agent"] = "__finish__"
            state["final_output"] = message
            state = append_message(state, make_message("orchestrator_agent", "user", "resume-blocked", message))
            return state

        if state.get("incoming_payload") and not state.get("gateway_message") and self._is_agent_available(state, "channel_gateway_agent"):
            reason = "Normalize the incoming channel payload before orchestration."
            state["orchestrator_reason"] = reason
            state["next_agent"] = "channel_gateway_agent"
            state = append_task(
                state,
                make_task(
                    sender="orchestrator_agent",
                    recipient="channel_gateway_agent",
                    intent="channel-ingest-normalization",
                    content=state.get("user_query", ""),
                    state_updates={},
                ),
            )
            return state

        if state.get("gateway_message") and not state.get("channel_session") and self._is_agent_available(state, "session_router_agent"):
            reason = "Resolve or create a channel session before task execution."
            state["orchestrator_reason"] = reason
            state["next_agent"] = "session_router_agent"
            state = append_task(
                state,
                make_task(
                    sender="orchestrator_agent",
                    recipient="session_router_agent",
                    intent="session-routing",
                    content=state.get("user_query", ""),
                    state_updates={},
                ),
            )
            return state

        # --- Project builder: blueprint before planning ---
        if (
            not state.get("plan_steps")
            and state.get("last_agent") != "project_blueprint_agent"
            and not state.get("blueprint_json")
            and self._is_agent_available(state, "project_blueprint_agent")
            and self._is_project_build_request(state)
        ):
            state["project_build_mode"] = True
            reason = "Build request detected. Route to project_blueprint_agent for technical architecture."
            state["orchestrator_reason"] = reason
            state["next_agent"] = "project_blueprint_agent"
            state = append_task(state, make_task(
                sender="orchestrator_agent", recipient="project_blueprint_agent",
                intent="project-blueprint", content=current_objective,
                state_updates={"blueprint_request": current_objective},
            ))
            return state

        if (
            not state.get("plan_steps")
            and state.get("last_agent") != "os_agent"
            and self._is_agent_available(state, "os_agent")
            and self._is_local_command_request(state)
            and not self._is_project_build_request(state)
        ):
            reason = "The request is a local command execution workflow. Route to os_agent for controlled shell execution."
            objective = state.get("current_objective") or state.get("user_query", "")
            state["orchestrator_reason"] = reason
            state["next_agent"] = "os_agent"
            state = append_task(
                state,
                make_task(
                    sender="orchestrator_agent",
                    recipient="os_agent",
                    intent="local-command-dispatch",
                    content=objective,
                    state_updates={"current_objective": objective},
                ),
            )
            return state

        # --- Project builder: blueprint approval gate ---
        if bool(state.get("blueprint_waiting_for_approval", False)):
            msg = state.get("pending_user_question") or "Review and approve the project blueprint before planning."
            state["next_agent"] = "__finish__"
            state["final_output"] = msg
            state = append_message(state, make_message("orchestrator_agent", "user", "blueprint-approval", msg))
            return state

        # Long-document workflows should bypass the generic planner to avoid unrelated plan reuse.
        if self._is_long_document_request(state):
            if state.get("plan_steps"):
                state["plan_steps"] = []
                state["plan_step_index"] = 0
                state["plan_execution_count"] = 0
            state["plan_ready"] = True
            state["plan_waiting_for_approval"] = False
            if state.get("plan_approval_status") == "approved":
                state["plan_approval_status"] = "not_started"

        if (
            bool(state.get("codebase_mode", False))
            and not state.get("plan_steps")
            and self._has_local_drive_request(state)
            and self._is_agent_available(state, "local_drive_agent")
            and state.get("last_agent") != "local_drive_agent"
            and int(state.get("local_drive_calls", 0) or 0) == 0
        ):
            reason = "Codebase mode enabled. Scan and summarize the repository before planning."
            objective = state.get("current_objective") or state.get("user_query", "")
            updates = {"current_objective": objective}
            if not str(state.get("local_drive_working_directory", "")).strip():
                updates["local_drive_working_directory"] = state.get("working_directory", "")
            state["orchestrator_reason"] = reason
            state["next_agent"] = "local_drive_agent"
            state = append_task(
                state,
                make_task(
                    sender="orchestrator_agent",
                    recipient="local_drive_agent",
                    intent="codebase-ingestion",
                    content=objective,
                    state_updates=updates,
                ),
            )
            return state

        if not state.get("plan_ready", False) and self._is_agent_available(state, "planner_agent"):
            if state.get("last_agent") != "planner_agent":
                reason = "Create a detailed step-by-step plan before execution."
                state["orchestrator_reason"] = reason
                state["next_agent"] = "planner_agent"
                state = append_task(
                    state,
                    make_task(
                        sender="orchestrator_agent",
                        recipient="planner_agent",
                        intent="planning",
                        content=current_objective,
                        state_updates={},
                    ),
                )
                return state

        if bool(state.get("plan_needs_clarification", False)):
            clarification = state.get("pending_user_question") or "I need more detail before executing the plan."
            state["next_agent"] = "__finish__"
            state["final_output"] = clarification
            state = append_message(state, make_message("orchestrator_agent", "user", "clarification", clarification))
            return state

        if bool(state.get("plan_waiting_for_approval", False)):
            approval_message = state.get("pending_user_question") or "Review and approve the plan before execution."
            state["next_agent"] = "__finish__"
            state["final_output"] = approval_message
            state = append_message(state, make_message("orchestrator_agent", "user", "plan-approval", approval_message))
            return state

        if bool(state.get("long_document_plan_waiting_for_approval", False)):
            approval_message = state.get("pending_user_question") or "Review and approve the long-document section plan before execution."
            state["next_agent"] = "__finish__"
            state["final_output"] = approval_message
            state = append_message(state, make_message("orchestrator_agent", "user", "subplan-approval", approval_message))
            return state

        if (
            not state.get("plan_steps")
            and
            self._has_local_drive_request(state)
            and self._is_agent_available(state, "local_drive_agent")
            and state.get("last_agent") != "local_drive_agent"
            and int(state.get("local_drive_calls", 0) or 0) == 0
        ):
            reason = "Ingest and summarize configured local-drive files before broader orchestration."
            objective = state.get("current_objective") or state.get("user_query", "")
            updates = {"current_objective": objective}
            if not str(state.get("local_drive_working_directory", "")).strip():
                updates["local_drive_working_directory"] = state.get("working_directory", "")
            state["orchestrator_reason"] = reason
            state["next_agent"] = "local_drive_agent"
            state = append_task(
                state,
                make_task(
                    sender="orchestrator_agent",
                    recipient="local_drive_agent",
                    intent="local-drive-ingestion",
                    content=objective,
                    state_updates=updates,
                ),
            )
            return state

        if (
            not state.get("plan_steps")
            and
            bool(state.get("local_drive_force_long_document", False))
            and self._is_long_document_request(state)
            and self._is_agent_available(state, "long_document_agent")
            and state.get("last_agent") != "long_document_agent"
            and int(state.get("local_drive_calls", 0) or 0) > 0
        ):
            reason = (
                "Local-drive ingestion is complete and a long-form output was requested. "
                "Route to long_document_agent for staged long-running synthesis."
            )
            objective = str(state.get("current_objective") or state.get("user_query", "")).strip()
            drive_summary = str(state.get("local_drive_summary") or state.get("document_summary") or "").strip()
            long_doc_objective = objective
            if drive_summary:
                long_doc_objective = (
                    f"{objective}\n\nUse this local-drive evidence summary as primary context:\n"
                    f"{self._truncate(drive_summary, 5000)}"
                )
            updates = {
                "current_objective": long_doc_objective,
                "long_document_mode": True,
            }
            if int(state.get("long_document_pages", 0) or 0) <= 0:
                updates["long_document_pages"] = 50
            state["orchestrator_reason"] = reason
            state["next_agent"] = "long_document_agent"
            state = append_task(
                state,
                make_task(
                    sender="orchestrator_agent",
                    recipient="long_document_agent",
                    intent="drive-informed-long-document",
                    content=long_doc_objective,
                    state_updates=updates,
                ),
            )
            return state

        if state.get("last_agent") and state.get("last_agent") != "reviewer_agent" and state.get("review_pending") and self._is_agent_available(state, "reviewer_agent"):
            reason = f"Review the completed step from {state['last_agent']} before continuing."
            state["orchestrator_reason"] = reason
            state["next_agent"] = "reviewer_agent"
            state = append_task(state, make_task(sender="orchestrator_agent", recipient="reviewer_agent", intent="step-review", content=reason, state_updates={}))
            record_work_note(state, "orchestrator_agent", "decision", f"next_agent=reviewer_agent\nreason={reason}\nstate_updates={{}}")
            return state

        if state.get("last_agent") == "reviewer_agent" and state.get("review_decision") == "revise":
            next_agent = state.get("review_target_agent") or "worker_agent"
            reason = state.get("review_reason", "Reviewer requested a corrected retry.")
            next_agent, reason = self._handle_unavailable_agent_choice(state, next_agent, reason)
            corrected_values = state.get("review_corrected_values", {})
            if not isinstance(corrected_values, dict):
                corrected_values = {}
            revised_objective = state.get("review_revised_objective") or current_objective
            subject_step_id = str(
                state.get("review_subject_step_id")
                or state.get("last_completed_plan_step_id")
                or state.get("current_plan_step_id")
                or ""
            ).strip()
            subject_agent = str(state.get("review_subject_agent") or next_agent).strip() or next_agent
            if (
                subject_agent == "long_document_agent"
                and str(state.get("long_document_compiled_path", "")).strip()
                and bool(state.get("long_document_addendum_on_review", True))
            ):
                attempts = int(state.get("long_document_addendum_attempts", 0) or 0)
                max_attempts = int(state.get("long_document_addendum_max_attempts", 1) or 1)
                if attempts >= max_attempts:
                    forced_reason = (
                        f"Reviewer requested addendum but max addendum attempts ({max_attempts}) reached. "
                        f"Proceeding without further retries. Last reason: {reason}"
                    )
                    log_task_update("Reviewer", forced_reason)
                    state["review_decision"] = "approve"
                    state["review_reason"] = forced_reason
                    state["review_is_output_correct"] = True
                    state["review_pending"] = False
                    update_planning_file(
                        state,
                        status="executing" if self._next_planned_agents(state) else "completed",
                        objective=current_objective,
                        plan_text=state.get("plan", ""),
                        clarifications=state.get("plan_clarification_questions", []),
                        execution_note=forced_reason,
                    )
                else:
                    addendum_instructions = (
                        f"Reviewer reason: {reason}\n"
                        f"Revised objective: {revised_objective}\n"
                        f"Corrected values: {json.dumps(corrected_values, ensure_ascii=False)}"
                    )
                    corrected_values = {
                        **corrected_values,
                        "current_objective": revised_objective,
                        "long_document_addendum_requested": True,
                        "long_document_addendum_instructions": addendum_instructions,
                    }
                    state["orchestrator_reason"] = reason
                    state["next_agent"] = "long_document_agent"
                    state = append_task(
                        state,
                        make_task(
                            sender="reviewer_agent",
                            recipient="long_document_agent",
                            intent="correction",
                            content=revised_objective,
                            state_updates=corrected_values,
                        ),
                    )
                    return state
            revision_attempt = self._record_review_revision(
                state,
                step_id=subject_step_id,
                agent_name=subject_agent,
            )
            max_revisions = max(1, int(state.get("max_step_revisions", 3) or 3))
            if revision_attempt > max_revisions:
                forced_reason = (
                    f"Reviewer requested more than {max_revisions} revisions for "
                    f"{subject_step_id or 'the current step'} handled by {subject_agent}. "
                    f"Proceeding without further retries. Last reason: {reason}"
                )
                log_task_update("Reviewer", forced_reason)
                state["review_decision"] = "approve"
                state["review_reason"] = forced_reason
                state["review_is_output_correct"] = True
                state["review_pending"] = False
                self._clear_review_revision(state, step_id=subject_step_id, agent_name=subject_agent)
                update_planning_file(
                    state,
                    status="executing" if self._next_planned_agents(state) else "completed",
                    objective=current_objective,
                    plan_text=state.get("plan", ""),
                    clarifications=state.get("plan_clarification_questions", []),
                    execution_note=forced_reason,
                )
            else:
                corrected_values = {**corrected_values, "current_objective": revised_objective}
                state["orchestrator_reason"] = reason
                state["next_agent"] = next_agent
                state = append_task(
                    state,
                    make_task(
                        sender="reviewer_agent",
                        recipient=next_agent,
                        intent="correction",
                        content=revised_objective,
                        state_updates=corrected_values,
                    ),
                )
                return state

        if state.get("last_agent") == "reviewer_agent" and state.get("review_decision") == "approve":
            approved_step_id = str(
                state.get("review_subject_step_id")
                or state.get("last_completed_plan_step_id")
                or state.get("current_plan_step_id")
                or ""
            ).strip()
            approved_agent = str(
                state.get("review_subject_agent")
                or state.get("last_completed_plan_step_agent")
                or state.get("review_target_agent")
                or ""
            ).strip()
            if approved_step_id or approved_agent:
                self._clear_review_revision(
                    state,
                    step_id=approved_step_id,
                    agent_name=approved_agent,
                )
            update_planning_file(
                state,
                status="executing" if self._next_planned_agents(state) else "completed",
                objective=current_objective,
                plan_text=state.get("plan", ""),
                clarifications=state.get("plan_clarification_questions", []),
                execution_note=(
                    f"Reviewer approved the latest step from {state.get('review_target_agent') or state.get('last_agent', '')}."
                ),
            )
            if self._next_planned_agents(state):
                state["review_pending"] = False
            else:
                gate_ok, gate_report = self._quality_gate_report(state)
                state["quality_gate_passed"] = gate_ok
                state["quality_gate_report"] = gate_report
                if not gate_ok:
                    final_text = (
                        "Quality gate failed. The run is blocked until checks pass.\n\n"
                        f"{gate_report}"
                    )
                    state["next_agent"] = "__finish__"
                    state["final_output"] = final_text
                    state = append_message(state, make_message("orchestrator_agent", "user", "final", final_text))
                    return state
                final_text = state.get("draft_response") or state.get("last_agent_output") or "Completed."
                state["next_agent"] = "__finish__"
                state["final_output"] = final_text
                state = append_message(state, make_message("orchestrator_agent", "user", "final", final_text))
                return state

        if (
            bool(state.get("extension_handler_generation_requested", False))
            and not bool(state.get("extension_handler_generation_dispatched", False))
            and self._is_agent_available(state, "agent_factory_agent")
            and state.get("last_agent") != "agent_factory_agent"
        ):
            unsupported = state.get("local_drive_unknown_extensions", [])
            unsupported_text = ", ".join(str(item) for item in unsupported if str(item).strip()) or "unknown"
            request_text = str(state.get("agent_factory_request", "")).strip() or (
                "Create file-extension ingestion capability for unsupported local-drive formats: "
                f"{unsupported_text}."
            )
            state["extension_handler_generation_dispatched"] = True
            state["missing_capability"] = str(
                state.get("missing_capability", "")
            ).strip() or f"File extension handling: {unsupported_text}"
            state["orchestrator_reason"] = (
                "Unsupported file extensions were detected and optional extension-agent generation is enabled."
            )
            state["next_agent"] = "agent_factory_agent"
            state = append_task(
                state,
                make_task(
                    sender="orchestrator_agent",
                    recipient="agent_factory_agent",
                    intent="extension-handler-generation",
                    content=request_text,
                    state_updates={
                        "agent_factory_request": request_text,
                        "missing_capability": state["missing_capability"],
                        "requested_missing_capability": state.get("requested_missing_capability", ""),
                    },
                ),
            )
            return state

        planned_batch = self._next_planned_agents(state)
        if planned_batch:
            next_step = planned_batch[0]
            next_agent = str(next_step.get("agent") or "worker_agent").strip()
            task_content = str(next_step.get("task") or current_objective)
            if len(planned_batch) > 1:
                task_content = (
                    f"{task_content}\n\nParallel batch hint: execute independently from other steps in group "
                    f"'{next_step.get('parallel_group')}'."
                )
            next_agent, reason = self._handle_unavailable_agent_choice(
                state,
                next_agent,
                f"Execute planned step {next_step.get('id', '')}: {next_step.get('success_criteria', '')}",
            )
            state["orchestrator_reason"] = reason
            state["next_agent"] = next_agent
            state["planned_active_agent"] = next_agent
            state["planned_active_step_id"] = str(next_step.get("id", "")).strip()
            state["planned_active_step_title"] = str(next_step.get("title", "")).strip()
            state["planned_active_step_success_criteria"] = str(next_step.get("success_criteria", "")).strip()
            step_index = int(state.get("plan_step_index", 0) or 0)
            total_steps = len(state.get("plan_steps", []) or [])
            step_title = state.get("planned_active_step_title") or state.get("planned_active_step_id") or "planned step"
            log_task_update(
                "Plan",
                f"Starting step {step_index + 1}/{total_steps}: {step_title} -> {next_agent}.",
            )
            state = append_task(
                state,
                make_task(
                    sender="orchestrator_agent",
                    recipient=next_agent,
                    intent="planned-step",
                    content=task_content,
                    state_updates={
                        "current_objective": task_content,
                        "current_plan_step_id": str(next_step.get("id", "")).strip(),
                        "current_plan_step_title": str(next_step.get("title", "")).strip(),
                        "current_plan_step_success_criteria": str(next_step.get("success_criteria", "")).strip(),
                    },
                ),
            )
            return state

        if state.get("last_agent") == "agent_factory_agent" and state.get("dynamic_agent_ready") and self._is_agent_available(state, "dynamic_agent_runner"):
            reason = "A generated agent is ready. Execute it through the dynamic agent runner."
            state["orchestrator_reason"] = reason
            state["next_agent"] = "dynamic_agent_runner"
            state = append_task(
                state,
                make_task(
                    sender="orchestrator_agent",
                    recipient="dynamic_agent_runner",
                    intent="run-generated-agent",
                    content=state.get("generated_agent_task") or current_objective,
                    state_updates={
                        "generated_agent_name": state.get("generated_agent_name", ""),
                        "generated_agent_function": state.get("generated_agent_function", ""),
                        "generated_agent_module_path": state.get("generated_agent_module_path", ""),
                        "generated_agent_task": state.get("generated_agent_task") or current_objective,
                    },
                ),
            )
            return state

        if state.get("last_agent") == "master_coding_agent":
            delegated_agent = str(state.get("master_coding_next_agent", "")).strip()
            delegated_reason = str(state.get("master_coding_reason", "")).strip() or "Continue master coding workflow."
            delegated_task = (
                state.get("master_coding_task_content")
                or state.get("current_objective")
                or state.get("user_query", "")
            )
            delegated_updates = state.get("master_coding_state_updates", {})
            if not isinstance(delegated_updates, dict):
                delegated_updates = {}

            if delegated_agent == "finish":
                state["orchestrator_reason"] = delegated_reason
                state["next_agent"] = "__finish__"
                state["final_output"] = state.get("draft_response") or state.get("last_agent_output") or "Master coding workflow completed."
                state = append_message(state, make_message("orchestrator_agent", "user", "final", state["final_output"]))
                return state

            if delegated_agent:
                delegated_agent, delegated_reason = self._handle_unavailable_agent_choice(state, delegated_agent, delegated_reason)
                if delegated_agent == "finish":
                    state["orchestrator_reason"] = delegated_reason
                    state["next_agent"] = "__finish__"
                    state["final_output"] = state.get("draft_response") or state.get("last_agent_output") or "Master coding workflow stopped."
                    state = append_message(state, make_message("orchestrator_agent", "user", "final", state["final_output"]))
                    return state
                state["orchestrator_reason"] = delegated_reason
                state["next_agent"] = delegated_agent
                state = append_task(
                    state,
                    make_task(
                        sender="master_coding_agent",
                        recipient=delegated_agent,
                        intent="master-coding-delegation",
                        content=delegated_task,
                        state_updates=delegated_updates,
                    ),
                )
                return state

        if (
            not state.get("plan_steps")
            and
            state.get("last_agent") != "master_coding_agent"
            and self._is_agent_available(state, "master_coding_agent")
            and self._is_project_audit_request(state)
        ):
            reason = "The request is a project/codebase audit. Route to master_coding_agent for a structured production-readiness assessment."
            objective = state.get("current_objective") or state.get("user_query", "")
            state["orchestrator_reason"] = reason
            state["next_agent"] = "master_coding_agent"
            state = append_task(
                state,
                make_task(
                    sender="orchestrator_agent",
                    recipient="master_coding_agent",
                    intent="project-audit-dispatch",
                    content=objective,
                    state_updates={"master_coding_request": objective, "coding_task": objective},
                ),
            )
            return state

        if (
            not state.get("plan_steps")
            and
            state.get("last_agent") != "superrag_agent"
            and self._is_agent_available(state, "superrag_agent")
            and self._is_superrag_request(state)
        ):
            reason = (
                "The request is a RAG/session knowledge-system workflow. "
                "Route to superrag_agent for ingestion, indexing, session switching, or chat."
            )
            objective = state.get("current_objective") or state.get("user_query", "")
            state["orchestrator_reason"] = reason
            state["next_agent"] = "superrag_agent"
            state = append_task(
                state,
                make_task(
                    sender="orchestrator_agent",
                    recipient="superrag_agent",
                    intent="superrag-dispatch",
                    content=objective,
                    state_updates={"current_objective": objective},
                ),
            )
            record_work_note(
                state,
                "orchestrator_agent",
                "decision",
                f"next_agent=superrag_agent\nreason={reason}\nstate_updates={{'current_objective': '{objective}'}}",
            )
            return state

        if (
            bool(state.get("research_pipeline_enabled", False))
            and not state.get("plan_steps")
            and state.get("last_agent") != "research_pipeline_agent"
            and self._is_agent_available(state, "research_pipeline_agent")
        ):
            pipeline_query = state.get("current_objective") or state.get("user_query", "")
            reason = (
                "research_pipeline_enabled is set. Routing to research_pipeline_agent "
                "to perform parallel multi-source evidence collection and LLM synthesis."
            )
            sources = state.get("research_sources") or ["web"]
            state["orchestrator_reason"] = reason
            state["next_agent"] = "research_pipeline_agent"
            state = append_task(
                state,
                make_task(
                    sender="orchestrator_agent",
                    recipient="research_pipeline_agent",
                    intent="research-pipeline-dispatch",
                    content=pipeline_query,
                    state_updates={
                        "research_sources": sources,
                        "research_pipeline_enabled": True,
                    },
                ),
            )
            record_work_note(
                state,
                "orchestrator_agent",
                "decision",
                (
                    f"next_agent=research_pipeline_agent\nreason={reason}\n"
                    f"state_updates={{'research_sources': {sources!r}, 'research_pipeline_enabled': True}}"
                ),
            )
            return state

        if (
            not state.get("plan_steps")
            and
            state.get("last_agent") != "deep_research_agent"
            and self._is_agent_available(state, "deep_research_agent")
            and not self._is_long_document_request(state)
            and self._is_deep_research_request(state)
        ):
            reason = "The request is a deep research task. Route to deep_research_agent for OpenAI web-grounded deep research."
            research_query = state.get("current_objective") or state.get("user_query", "")
            state["orchestrator_reason"] = reason
            state["next_agent"] = "deep_research_agent"
            state = append_task(
                state,
                make_task(
                    sender="orchestrator_agent",
                    recipient="deep_research_agent",
                    intent="deep-research-dispatch",
                    content=research_query,
                    state_updates={"research_query": research_query},
                ),
            )
            record_work_note(
                state,
                "orchestrator_agent",
                "decision",
                f"next_agent=deep_research_agent\nreason={reason}\nstate_updates={{'research_query': '{research_query}'}}",
            )
            return state

        if (
            not state.get("plan_steps")
            and
            state.get("last_agent") != "long_document_agent"
            and self._is_agent_available(state, "long_document_agent")
            and self._is_long_document_request(state)
        ):
            reason = (
                "The request is a very long/exhaustive document objective. "
                "Route to long_document_agent for staged section research and final merge."
            )
            long_doc_objective = state.get("current_objective") or state.get("user_query", "")
            updates = {
                "current_objective": long_doc_objective,
                "long_document_mode": True,
            }
            state["orchestrator_reason"] = reason
            state["next_agent"] = "long_document_agent"
            state = append_task(
                state,
                make_task(
                    sender="orchestrator_agent",
                    recipient="long_document_agent",
                    intent="long-document-dispatch",
                    content=long_doc_objective,
                    state_updates=updates,
                ),
            )
            record_work_note(
                state,
                "orchestrator_agent",
                "decision",
                (
                    "next_agent=long_document_agent\n"
                    f"reason={reason}\n"
                    f"state_updates={json.dumps(updates, ensure_ascii=False)}"
                ),
            )
            return state

        prompt = f"""
You are the orchestration agent for a plugin-driven multi-agent AI system.

Your job is to decide which agent should run next, or whether the workflow should finish.
Choose from exactly these currently available agents:
{json.dumps(self._available_agent_descriptions(state), indent=2)}

Rules:
- Only choose agents that appear in the available-agent list above.
- Use the description of each agent as the source of truth for what it does.
- If incoming_channel or incoming_payload is present and gateway_message has not been created yet, prefer channel_gateway_agent first.
- If gateway_message exists but channel_session is missing, prefer session_router_agent before other work.
- If the user asks for an unavailable integration, use worker_agent to explain the missing setup unless agent_factory_agent is better suited.
- For end-to-end software build requests that need detailed architecture, project planning, and delegated implementation/setup, prefer master_coding_agent first.
- Finish when the current state already contains a good final answer.
- Never use any agent for exploitation, credential attacks, service disruption, or unauthorized access.
- If the reviewer already requested a retry, follow that instruction rather than inventing a different reroute.
- Avoid repeating the same failing agent unless the inputs changed.
- Put only useful state updates for the chosen agent in `state_updates`.

Current user query:
{state.get("user_query", "")}

Current objective:
{current_objective}

Current plan:
{state.get("plan", "") or "None"}

Current draft response:
{state.get("draft_response", "") or "None"}

Current review decision:
{state.get("review_decision", "") or "None"}

Current review reason:
{state.get("review_reason", "") or "None"}

Reviewer recommended next agent:
{state.get("review_target_agent", "") or "None"}

Reviewer corrected values:
{json.dumps(state.get("review_corrected_values", {}), ensure_ascii=False)}

Current setup summary:
{state.get("setup_summary", "")}

File memory context:
{self._truncate(state.get("file_memory_context", "") or "None", 1800)}

Disabled or unavailable agents:
{json.dumps(state.get("disabled_agents", {}), indent=2, ensure_ascii=False)}

Available setup actions:
{json.dumps(state.get("setup_actions", []), indent=2, ensure_ascii=False)}

A2A agent cards:
{json.dumps(state["a2a"]["agent_cards"], indent=2)}

A2A messages:
{self._recent_a2a_messages(state)}

Recent agent history:
{self._history_as_text(state)}

Return ONLY valid JSON in this exact schema:
{{
  "agent": "{self._agent_enum(state, include_finish=True)}",
  "reason": "short reason",
  "state_updates": {{}},
  "task_content": "short task content for the chosen agent",
  "final_response": "required only when agent is finish"
}}
""".strip()

        try:
            with agent_model_context("orchestrator_agent"):
                response = llm.invoke(prompt)
            raw_output = response.content.strip() if hasattr(response, "content") else str(response).strip()
        except Exception as llm_exc:
            logger.warning("Orchestrator LLM call failed: %s", llm_exc)
            decision = {
                "agent": "finish",
                "reason": f"Orchestrator LLM call failed ({type(llm_exc).__name__}: {llm_exc}). "
                          "This is likely a network or API provider issue.",
                "state_updates": {},
                "final_response": (
                    state.get("draft_response")
                    or state.get("last_agent_output")
                    or f"The orchestrator could not reach the LLM provider: {llm_exc}. "
                       "Check your network connection and API keys, then retry."
                ),
            }
            state["last_error"] = f"orchestrator_llm_failed: {llm_exc}"
            raw_output = None

        if raw_output is not None:
            try:
                decision = self._parse_orchestrator_output(raw_output)
            except Exception:
                decision = {
                    "agent": "finish",
                    "reason": "The orchestrator returned invalid JSON. Falling back to the current best result.",
                    "state_updates": {},
                    "final_response": state.get("draft_response") or state.get("last_agent_output") or "The orchestrator could not produce a valid routing decision.",
                }

        state_updates = decision.get("state_updates", {})
        if isinstance(state_updates, dict):
            state.update(state_updates)

        next_agent = decision.get("agent", "finish")
        reason = decision.get("reason", "No reason provided.")
        next_agent, reason = self._handle_unavailable_agent_choice(state, next_agent, reason)
        state["orchestrator_reason"] = reason

        if next_agent == "finish":
            state["next_agent"] = "__finish__"
            state["final_output"] = decision.get("final_response") or state.get("draft_response") or state.get("last_agent_output") or "No final response was generated."
            state = append_message(state, make_message("orchestrator_agent", "user", "final", state["final_output"]))
        else:
            state["next_agent"] = next_agent
            task_content = decision.get("task_content") or state_updates.get("current_objective") or state.get("current_objective") or state.get("user_query", "")
            state = append_task(
                state,
                make_task(
                    sender="orchestrator_agent",
                    recipient=next_agent,
                    intent=reason,
                    content=task_content,
                    state_updates=state_updates if isinstance(state_updates, dict) else {},
                ),
            )
        log_task_update("Orchestrator", f"Decision: {next_agent}. Reason: {reason}")
        return state

    def orchestrator_router(self, state: dict):
        return state.get("next_agent", "__finish__")

    def build_workflow(self):
        workflow = StateGraph(dict)
        workflow.add_node("orchestrator_agent", self.orchestrator_agent)
        for agent_name in self.registry.agents:
            workflow.add_node(agent_name, lambda state, name=agent_name: self._execute_agent(state, name))
        workflow.set_entry_point("orchestrator_agent")
        edge_map = {agent_name: agent_name for agent_name in self.registry.agents}
        edge_map["__finish__"] = END
        workflow.add_conditional_edges("orchestrator_agent", self.orchestrator_router, edge_map)
        for agent_name in self.registry.agents:
            workflow.add_edge(agent_name, "orchestrator_agent")
        return workflow.compile()

    def save_graph(self, app):
        # Graph rendering can fail on some LangGraph versions for dynamic dict state.
        # Keep this as an opt-in diagnostic feature so normal runs are not noisy.
        if os.getenv("KENDR_SAVE_GRAPH", "").strip().lower() not in {"1", "true", "yes", "on"}:
            return
        try:
            graph = app.get_graph()
            mermaid_text = graph.draw_mermaid()
            mermaid_path = resolve_output_path("graph.mmd")
            with open(mermaid_path, "w", encoding="utf-8") as f:
                f.write(mermaid_text)
            log_task_update("System", f"Workflow graph (Mermaid) saved to {mermaid_path}")

            if os.getenv("KENDR_SAVE_GRAPH_PNG", "").strip().lower() in {"1", "true", "yes", "on"}:
                png_data = graph.draw_mermaid_png()
                graph_path = resolve_output_path("graph.png")
                with open(graph_path, "wb") as f:
                    f.write(png_data)
                log_task_update("System", f"Workflow graph PNG saved to {graph_path}")
        except Exception as exc:
            logger.warning(f"Skipping graph export: {exc}")

    def new_run_id(self) -> str:
        return f"run_{datetime.now(timezone.utc).timestamp()}"

    def _restore_pending_user_input(self, initial_state: RuntimeState, prior_channel_state: Mapping[str, Any], user_query: str) -> None:
        pending_kind = str(prior_channel_state.get("pending_user_input_kind", "") or "").strip()
        if not pending_kind and prior_channel_state.get("awaiting_user_input"):
            pending_kind = "clarification"
        if not pending_kind:
            return

        # Ensure plan context is available before applying approval replies.
        # This prevents re-planning after an approved resume when the snapshot
        # contains the plan but the initial state does not.
        if not initial_state.get("plan_steps") and isinstance(prior_channel_state.get("plan_steps"), list):
            initial_state["plan_steps"] = prior_channel_state.get("plan_steps", [])
            initial_state["plan_step_index"] = int(prior_channel_state.get("plan_step_index", 0) or 0)
            initial_state["plan_execution_count"] = int(prior_channel_state.get("plan_execution_count", 0) or 0)
            if prior_channel_state.get("plan"):
                initial_state["plan"] = str(prior_channel_state.get("plan", "") or "")
            if isinstance(prior_channel_state.get("plan_data"), dict):
                initial_state["plan_data"] = prior_channel_state.get("plan_data", {})
            if prior_channel_state.get("plan_approval_status"):
                initial_state["plan_approval_status"] = str(prior_channel_state.get("plan_approval_status", "") or "")
            if isinstance(prior_channel_state.get("plan_waiting_for_approval"), bool):
                initial_state["plan_waiting_for_approval"] = bool(prior_channel_state.get("plan_waiting_for_approval", False))

        previous_objective = str(prior_channel_state.get("last_objective", "") or "").strip()
        if pending_kind == "clarification":
            if previous_objective:
                initial_state["current_objective"] = f"{previous_objective}\n\nUser clarification: {user_query}"
            initial_state["plan_needs_clarification"] = False
            initial_state["pending_user_input_kind"] = ""
            initial_state["pending_user_question"] = ""
            initial_state["plan_ready"] = False
            return

        scope = str(prior_channel_state.get("approval_pending_scope", "") or "").strip()
        prompt = str(prior_channel_state.get("pending_user_question", "") or "").strip()
        if previous_objective:
            initial_state["current_objective"] = previous_objective
        response = self._interpret_user_input_response(user_query)

        if scope == "drive_data_sufficiency":
            if response["action"] == "approve":
                initial_state["pending_user_input_kind"] = ""
                initial_state["approval_pending_scope"] = ""
                initial_state["pending_user_question"] = ""
                initial_state["local_drive_insufficient_approved"] = True
                initial_state["local_drive_insufficient_response"] = response.get("feedback", "")
                return
            if response["action"] == "revise":
                initial_state["pending_user_input_kind"] = ""
                initial_state["approval_pending_scope"] = ""
                initial_state["pending_user_question"] = ""
                initial_state["user_cancelled"] = True
                initial_state["final_output"] = (
                    "Run cancelled per your response. Add more source files and re-run when ready, "
                    "or reply with updated instructions to proceed."
                )
                return

        if response["action"] == "approve":
            initial_state["pending_user_input_kind"] = ""
            initial_state["approval_pending_scope"] = ""
            initial_state["pending_user_question"] = ""
            if scope == "project_blueprint":
                initial_state["blueprint_waiting_for_approval"] = False
                initial_state["blueprint_status"] = "approved"
                initial_state["plan_ready"] = False  # force planner to run next
            elif scope == "root_plan":
                initial_state["plan_waiting_for_approval"] = False
                initial_state["plan_approval_status"] = "approved"
                initial_state["plan_ready"] = bool(initial_state.get("plan_steps"))
                initial_state["plan_needs_clarification"] = False
            elif scope == "long_document_plan":
                initial_state["long_document_plan_waiting_for_approval"] = False
                initial_state["long_document_plan_status"] = "approved"
                initial_state["long_document_execute_from_saved_outline"] = True
                initial_state["plan_ready"] = bool(initial_state.get("plan_steps")) and initial_state.get("plan_approval_status") == "approved"
            return

        if response["action"] == "revise":
            initial_state["pending_user_input_kind"] = ""
            initial_state["approval_pending_scope"] = ""
            initial_state["pending_user_question"] = ""
            if scope == "project_blueprint":
                initial_state["blueprint_waiting_for_approval"] = False
                initial_state["blueprint_status"] = "revision_requested"
                initial_state["blueprint_json"] = {}  # clear so blueprint agent reruns
                initial_state["plan_ready"] = False
                if previous_objective:
                    initial_state["current_objective"] = (
                        f"{previous_objective}\n\nBlueprint revision instructions from the user:\n{response['feedback']}"
                    )
            elif scope == "root_plan":
                initial_state["plan_waiting_for_approval"] = False
                initial_state["plan_approval_status"] = "revision_requested"
                initial_state["plan_revision_feedback"] = response["feedback"]
                initial_state["plan_revision_count"] = int(initial_state.get("plan_revision_count", 0) or 0) + 1
                initial_state["plan_ready"] = False
                if previous_objective:
                    initial_state["current_objective"] = (
                        f"{previous_objective}\n\nPlan revision instructions from the user:\n{response['feedback']}"
                    )
            elif scope == "long_document_plan":
                initial_state["long_document_plan_waiting_for_approval"] = False
                initial_state["long_document_plan_status"] = "revision_requested"
                initial_state["long_document_plan_feedback"] = response["feedback"]
                initial_state["long_document_plan_revision_count"] = int(initial_state.get("long_document_plan_revision_count", 0) or 0) + 1
                initial_state["long_document_replan_requested"] = True
                initial_state["plan_ready"] = bool(initial_state.get("plan_steps")) and initial_state.get("plan_approval_status") == "approved"
                if previous_objective:
                    initial_state["current_objective"] = previous_objective
            return

        explicit_instruction = "Reply `approve` to continue, or describe the changes you want."
        initial_state["pending_user_input_kind"] = pending_kind
        initial_state["approval_pending_scope"] = scope
        if prompt:
            initial_state["pending_user_question"] = prompt if explicit_instruction in prompt else f"{prompt}\n\n{explicit_instruction}"
        else:
            initial_state["pending_user_question"] = explicit_instruction
        if scope == "project_blueprint":
            initial_state["blueprint_waiting_for_approval"] = True
            initial_state["plan_ready"] = False
        elif scope == "root_plan":
            initial_state["plan_waiting_for_approval"] = True
            initial_state["plan_ready"] = False
        elif scope == "long_document_plan":
            initial_state["long_document_plan_waiting_for_approval"] = True
            initial_state["plan_ready"] = bool(initial_state.get("plan_steps")) and initial_state.get("plan_approval_status") == "approved"

    def _restore_from_resume_checkpoint(
        self,
        initial_state: RuntimeState,
        checkpoint_payload: Mapping[str, Any],
        user_query: str,
    ) -> None:
        if not isinstance(checkpoint_payload, Mapping):
            return

        summary = checkpoint_payload.get("summary", {})
        if not isinstance(summary, dict):
            summary = {}
        snapshot = checkpoint_payload.get("state_snapshot", {})
        if not isinstance(snapshot, dict):
            snapshot = {}

        mode = str(initial_state.get("resume_mode", "resume") or "resume").strip().lower()
        source_run_id = str(summary.get("run_id") or snapshot.get("run_id", "")).strip()
        source_status = str(summary.get("status", "") or snapshot.get("last_status", "")).strip().lower()

        if mode == "branch":
            inherited_prefixes = ("local_drive_", "superrag_", "ocr_", "web_crawl_", "blueprint_", "project_")
            inherited_keys = {
                "documents",
                "document_summary",
                "draft_response",
                "final_output",
                "agent_history",
                "last_agent_output",
            }
            for key, value in snapshot.items():
                if key in inherited_keys or key.startswith(inherited_prefixes):
                    initial_state[key] = value
            initial_state["parent_run_id"] = source_run_id
            initial_state["branch_source_run_id"] = source_run_id
            approval_action = self._interpret_user_input_response(user_query).get("action")
            snapshot_objective = str(snapshot.get("current_objective") or snapshot.get("user_query", "")).strip()
            if approval_action == "approve" and snapshot_objective:
                initial_state["current_objective"] = snapshot_objective
            else:
                initial_state["current_objective"] = str(user_query or snapshot_objective).strip()

            plan_steps = snapshot.get("plan_steps") if isinstance(snapshot.get("plan_steps"), list) else []
            plan_approved = str(snapshot.get("plan_approval_status", "")).strip().lower() == "approved"
            if plan_steps and plan_approved:
                initial_state["plan"] = str(snapshot.get("plan", "") or "")
                initial_state["plan_data"] = snapshot.get("plan_data", {}) if isinstance(snapshot.get("plan_data"), dict) else {}
                initial_state["plan_steps"] = plan_steps
                initial_state["plan_execution_count"] = int(snapshot.get("plan_execution_count", 0) or 0)
                initial_state["plan_approval_status"] = "approved"
                initial_state["plan_waiting_for_approval"] = False
                initial_state["plan_needs_clarification"] = False
                initial_state["plan_ready"] = True

                target_step_id = str(
                    snapshot.get("current_plan_step_id")
                    or snapshot.get("planned_active_step_id")
                    or snapshot.get("last_completed_plan_step_id")
                    or ""
                ).strip()
                resolved_index = int(snapshot.get("plan_step_index", 0) or 0)
                if target_step_id:
                    for index, step in enumerate(plan_steps):
                        if str(step.get("id", "")).strip() == target_step_id:
                            resolved_index = index
                            break
                if resolved_index >= len(plan_steps):
                    resolved_index = max(0, len(plan_steps) - 1)
                if resolved_index < 0:
                    resolved_index = 0
                initial_state["plan_step_index"] = resolved_index
            else:
                initial_state["plan"] = ""
                initial_state["plan_data"] = {}
                initial_state["plan_steps"] = []
                initial_state["plan_step_index"] = 0
                initial_state["plan_execution_count"] = 0
                initial_state["plan_ready"] = False
                initial_state["plan_waiting_for_approval"] = False
                initial_state["plan_approval_status"] = "not_started"
                initial_state["plan_needs_clarification"] = False
            initial_state["pending_user_input_kind"] = ""
            initial_state["pending_user_question"] = ""
            initial_state["approval_pending_scope"] = ""
            initial_state["long_document_plan_waiting_for_approval"] = False
            initial_state["long_document_plan_status"] = ""
            initial_state["failure_checkpoint"] = {}
            initial_state["review_pending"] = False
            initial_state["review_decision"] = ""
            initial_state["review_reason"] = ""
            initial_state["resume_requested"] = False
            initial_state["resume_ready"] = False
            initial_state["resume_blocked"] = False
            return

        protected_keys = {
            "run_id",
            "run_output_dir",
            "working_directory",
            "parent_run_id",
            "resume_mode",
            "resume_output_dir",
            "resume_checkpoint_payload",
        }
        for key, value in snapshot.items():
            if key in protected_keys and initial_state.get(key):
                continue
            initial_state[key] = value

        initial_state["resume_source_run_id"] = source_run_id
        if source_run_id and not initial_state.get("parent_run_id"):
            initial_state["parent_run_id"] = str(snapshot.get("parent_run_id", "") or "")

        last_objective = str(snapshot.get("current_objective", "") or snapshot.get("user_query", "")).strip()
        if last_objective:
            initial_state["session_previous_objective"] = last_objective

        prior_state_like = dict(snapshot)
        prior_state_like.setdefault("last_objective", last_objective)
        prior_state_like.setdefault("last_status", source_status)
        if bool(summary.get("awaiting_user_input", False)) or str(snapshot.get("pending_user_input_kind", "")).strip():
            prior_state_like["awaiting_user_input"] = True
            self._restore_pending_user_input(initial_state, prior_state_like, user_query)
            return

        failure_checkpoint = initial_state.get("failure_checkpoint", {})
        if not isinstance(failure_checkpoint, dict):
            failure_checkpoint = {}
            initial_state["failure_checkpoint"] = {}

        if source_status in {"failed", "running", "running_stale"}:
            initial_state["resume_requested"] = True
            can_resume = bool(failure_checkpoint.get("can_resume", True))
            if source_status in {"running", "running_stale"}:
                can_resume = True
            block_reason = str(failure_checkpoint.get("block_reason", "") or "")
            if can_resume and initial_state.get("plan_steps"):
                failed_index = int(failure_checkpoint.get("step_index", initial_state.get("plan_step_index", 0)) or 0)
                initial_state["plan_step_index"] = max(
                    0,
                    min(failed_index, max(0, len(initial_state.get("plan_steps", [])) - 1)),
                )
                initial_state["plan_ready"] = initial_state.get("plan_approval_status") == "approved" and not state_awaiting_user_input(initial_state)
                initial_state["plan_needs_clarification"] = False
                initial_state["resume_ready"] = True
                failed_task = str(failure_checkpoint.get("task_content", "") or "").strip()
                if failed_task:
                    initial_state["current_objective"] = failed_task
            elif not can_resume:
                initial_state["resume_blocked"] = True
                initial_state["resume_block_reason"] = block_reason or "missing plan checkpoints for safe restart"

    def build_initial_state(self, user_query: str, **overrides: Any) -> RuntimeState:
        resolved_run_id = overrides.get("run_id", self.new_run_id())
        session_started_at = overrides.get("session_started_at") or datetime.now(timezone.utc).isoformat()
        initial_state: RuntimeState = {
            "run_id": resolved_run_id,
            "session_id": overrides.get("session_id") or f"session_{resolved_run_id}",
            "session_started_at": session_started_at,
            "work_notes_file": overrides.get("work_notes_file", "agent_work_notes.txt"),
            "user_query": user_query,
            "current_objective": user_query,
            "plan": "",
            "plan_data": {},
            "plan_steps": [],
            "plan_step_index": 0,
            "plan_execution_count": 0,
            "plan_ready": False,
            "plan_waiting_for_approval": False,
            "plan_approval_status": "not_started",
            "plan_revision_feedback": "",
            "plan_revision_count": 0,
            "plan_version": 0,
            "plan_needs_clarification": False,
            "plan_clarification_questions": [],
            "planned_active_agent": "",
            "planned_active_step_id": "",
            "planned_active_step_title": "",
            "planned_active_step_success_criteria": "",
            "current_plan_step_id": "",
            "current_plan_step_title": "",
            "current_plan_step_success_criteria": "",
            "last_completed_plan_step_id": "",
            "last_completed_plan_step_title": "",
            "last_completed_plan_step_success_criteria": "",
            "last_completed_plan_step_agent": "",
            "active_agent_task": "",
            "pending_user_question": "",
            "pending_user_input_kind": "",
            "approval_pending_scope": "",
            "planning_notes": [],
            "long_document_plan_waiting_for_approval": False,
            "long_document_plan_status": "",
            "long_document_plan_feedback": "",
            "long_document_plan_revision_count": 0,
            "long_document_plan_version": 0,
            "long_document_plan_markdown": "",
            "long_document_plan_data": {},
            "long_document_addendum_on_review": True,
            "long_document_addendum_requested": False,
            "long_document_addendum_instructions": "",
            "long_document_addendum_attempts": 0,
            "long_document_addendum_max_attempts": 1,
            "long_document_addendum_path": "",
            "long_document_addendum_completed": False,
            "resume_requested": False,
            "resume_ready": False,
            "resume_blocked": False,
            "resume_block_reason": "",
            "failure_checkpoint": {},
            "draft_response": "",
            "review_reason": "",
            "review_decision": "",
            "review_target_agent": "",
            "review_corrected_values": {},
            "review_revised_objective": user_query,
            "review_step_assessments": [],
            "review_is_output_correct": False,
            "review_pending": False,
            "review_subject_step_id": "",
            "review_subject_agent": "",
            "review_revision_counts": {},
            "enforce_quality_gate": bool(overrides.get("enforce_quality_gate", True)),
            "quality_gate_passed": False,
            "quality_gate_report": "",
            "worker_calls": 0,
            "reviewer_calls": 0,
            "revision_count": 0,
            "max_step_revisions": overrides.get("max_step_revisions", 3),
            "orchestrator_calls": 0,
            "effective_steps": 0,
            "next_agent": "",
            "orchestrator_reason": "",
            "final_output": "",
            "agent_history": [],
            "max_steps": overrides.get("max_steps", 20),
            "research_target": "",
            "use_vector_memory": True,
            "local_drive_auto_generate_extension_handlers": False,
            "local_drive_unknown_extensions": [],
            "local_drive_handler_registry": {},
            "local_drive_handler_routes": {},
            "extension_handler_generation_requested": False,
            "extension_handler_generation_dispatched": False,
            "extension_handler_generation_signature": "",
            "agent_factory_request": "",
            # Project builder defaults
            "project_build_mode": False,
            "blueprint_json": {},
            "blueprint_status": "",
            "blueprint_version": 0,
            "blueprint_waiting_for_approval": False,
            "project_name": "",
            "project_root": "",
            "project_stack": "",
            "codebase_mode": False,
        }
        initial_state.update(overrides)
        prior_channel_session = initial_state.get("channel_session", {})
        prior_channel_state = prior_channel_session.get("state", {}) if isinstance(prior_channel_session, dict) else {}
        resume_requested = self._looks_like_resume_request(user_query)
        has_pending_session_input = bool(prior_channel_state.get("awaiting_user_input")) if isinstance(prior_channel_state, dict) else False
        reuse_session_plan = resume_requested or has_pending_session_input
        if isinstance(prior_channel_state, dict):
            if reuse_session_plan and prior_channel_state.get("last_plan") and not initial_state.get("plan"):
                initial_state["plan"] = str(prior_channel_state.get("last_plan", ""))
            if reuse_session_plan and prior_channel_state.get("last_plan_data"):
                initial_state["plan_data"] = prior_channel_state.get("last_plan_data", {})
            if reuse_session_plan and prior_channel_state.get("last_plan_steps"):
                initial_state["plan_steps"] = prior_channel_state.get("last_plan_steps", [])
            if reuse_session_plan and isinstance(prior_channel_state.get("last_plan_step_index"), int):
                initial_state["plan_step_index"] = max(0, int(prior_channel_state.get("last_plan_step_index", 0)))
            if reuse_session_plan:
                initial_state["plan_waiting_for_approval"] = bool(prior_channel_state.get("plan_waiting_for_approval", False))
                initial_state["plan_approval_status"] = str(prior_channel_state.get("plan_approval_status", initial_state.get("plan_approval_status", "")) or initial_state.get("plan_approval_status", ""))
                initial_state["plan_revision_feedback"] = str(prior_channel_state.get("plan_revision_feedback", "") or "")
                initial_state["plan_revision_count"] = int(prior_channel_state.get("plan_revision_count", 0) or 0)
                initial_state["plan_version"] = int(prior_channel_state.get("plan_version", 0) or 0)
                initial_state["planning_notes"] = prior_channel_state.get("planning_notes", [])
                initial_state["review_revision_counts"] = prior_channel_state.get("review_revision_counts", {})
                initial_state["pending_user_input_kind"] = str(prior_channel_state.get("pending_user_input_kind", "") or "")
                initial_state["approval_pending_scope"] = str(prior_channel_state.get("approval_pending_scope", "") or "")
                initial_state["pending_user_question"] = str(prior_channel_state.get("pending_user_question", "") or "")
                initial_state["long_document_plan_waiting_for_approval"] = bool(prior_channel_state.get("long_document_plan_waiting_for_approval", False))
                initial_state["long_document_plan_status"] = str(prior_channel_state.get("long_document_plan_status", "") or "")
                initial_state["long_document_plan_feedback"] = str(prior_channel_state.get("long_document_plan_feedback", "") or "")
                initial_state["long_document_plan_revision_count"] = int(prior_channel_state.get("long_document_plan_revision_count", 0) or 0)
                initial_state["long_document_plan_markdown"] = str(prior_channel_state.get("long_document_plan_markdown", "") or "")
                initial_state["long_document_plan_data"] = prior_channel_state.get("long_document_plan_data", {})
                initial_state["long_document_plan_version"] = int(prior_channel_state.get("long_document_plan_version", 0) or 0)
                if prior_channel_state.get("long_document_outline"):
                    initial_state["long_document_outline"] = prior_channel_state.get("long_document_outline", {})
                if initial_state.get("plan_steps") and initial_state.get("plan_approval_status") == "approved" and not initial_state.get("plan_waiting_for_approval", False):
                    initial_state["plan_ready"] = True
            if prior_channel_state.get("blueprint_json"):
                initial_state["blueprint_json"] = prior_channel_state.get("blueprint_json", {})
            if prior_channel_state.get("blueprint_summary"):
                initial_state["blueprint_summary"] = str(prior_channel_state.get("blueprint_summary", "") or "")
            if prior_channel_state.get("blueprint_status"):
                initial_state["blueprint_status"] = str(prior_channel_state.get("blueprint_status", "") or "")
            if isinstance(prior_channel_state.get("blueprint_version"), int):
                initial_state["blueprint_version"] = int(prior_channel_state.get("blueprint_version", 0) or 0)
            initial_state["blueprint_waiting_for_approval"] = bool(
                prior_channel_state.get("blueprint_waiting_for_approval", initial_state.get("blueprint_waiting_for_approval", False))
            )
            if prior_channel_state.get("blueprint_tech_stack"):
                initial_state["blueprint_tech_stack"] = prior_channel_state.get("blueprint_tech_stack", {})
            if prior_channel_state.get("blueprint_db_schema"):
                initial_state["blueprint_db_schema"] = prior_channel_state.get("blueprint_db_schema", {})
            if prior_channel_state.get("blueprint_api_design"):
                initial_state["blueprint_api_design"] = prior_channel_state.get("blueprint_api_design", {})
            if prior_channel_state.get("blueprint_frontend_components"):
                initial_state["blueprint_frontend_components"] = prior_channel_state.get("blueprint_frontend_components", {})
            if prior_channel_state.get("blueprint_directory_structure"):
                initial_state["blueprint_directory_structure"] = prior_channel_state.get("blueprint_directory_structure", [])
            if prior_channel_state.get("blueprint_dependencies"):
                initial_state["blueprint_dependencies"] = prior_channel_state.get("blueprint_dependencies", {})
            if prior_channel_state.get("blueprint_env_vars"):
                initial_state["blueprint_env_vars"] = prior_channel_state.get("blueprint_env_vars", [])
            if prior_channel_state.get("blueprint_docker_services"):
                initial_state["blueprint_docker_services"] = prior_channel_state.get("blueprint_docker_services", [])
            if prior_channel_state.get("project_name"):
                initial_state["project_name"] = str(prior_channel_state.get("project_name", "") or "")
            if prior_channel_state.get("project_root"):
                initial_state["project_root"] = str(prior_channel_state.get("project_root", "") or "")
            if prior_channel_state.get("project_stack"):
                initial_state["project_stack"] = str(prior_channel_state.get("project_stack", "") or "")
            if prior_channel_state.get("superrag_active_session_id"):
                initial_state["superrag_active_session_id"] = str(prior_channel_state.get("superrag_active_session_id", "")).strip()
            if prior_channel_state.get("last_objective"):
                initial_state["session_previous_objective"] = str(prior_channel_state.get("last_objective", ""))
            if prior_channel_state.get("history"):
                initial_state["session_history"] = prior_channel_state.get("history", [])
            if prior_channel_state.get("failure_checkpoint"):
                initial_state["failure_checkpoint"] = prior_channel_state.get("failure_checkpoint", {})
            if prior_channel_state.get("awaiting_user_input"):
                self._restore_pending_user_input(initial_state, prior_channel_state, user_query)
            previous_failed = str(prior_channel_state.get("last_status", "")).strip().lower() == "failed"
            resume_checkpoint = initial_state.get("failure_checkpoint", {})
            if previous_failed and resume_requested and isinstance(resume_checkpoint, dict):
                initial_state["resume_requested"] = True
                can_resume = bool(resume_checkpoint.get("can_resume", False))
                block_reason = str(resume_checkpoint.get("block_reason", "") or "")
                if can_resume and initial_state.get("plan_steps"):
                    failed_index = int(resume_checkpoint.get("step_index", initial_state.get("plan_step_index", 0)) or 0)
                    initial_state["plan_step_index"] = max(0, min(failed_index, max(0, len(initial_state.get("plan_steps", [])) - 1)))
                    initial_state["plan_ready"] = initial_state.get("plan_approval_status") == "approved" and not state_awaiting_user_input(initial_state)
                    initial_state["plan_needs_clarification"] = False
                    initial_state["resume_ready"] = True
                    failed_task = str(resume_checkpoint.get("task_content", "") or "").strip()
                    if failed_task:
                        initial_state["current_objective"] = failed_task
                else:
                    initial_state["resume_blocked"] = True
                    initial_state["resume_block_reason"] = block_reason or "missing plan checkpoints for safe restart"
        resume_checkpoint_payload = initial_state.get("resume_checkpoint_payload", {})
        if isinstance(resume_checkpoint_payload, dict) and resume_checkpoint_payload:
            self._restore_from_resume_checkpoint(initial_state, resume_checkpoint_payload, user_query)
        initial_state = self.apply_runtime_setup(initial_state)
        initial_state["privileged_policy"] = build_privileged_policy(initial_state)
        if self._is_project_audit_request(initial_state) or bool(initial_state.get("codebase_mode", False)):
            try:
                working_directory = str(initial_state.get("working_directory", "")).strip()
                if working_directory:
                    initial_state["repo_scan_summary"] = self._build_repo_scan_summary(working_directory)
            except Exception as exc:
                initial_state["repo_scan_summary"] = f"Repository scan failed: {exc}"
        ensure_a2a_state(initial_state, initial_state.get("available_agent_cards") or self._agent_cards())
        initial_state = bootstrap_file_memory(initial_state)
        update_session_file(initial_state, status="initialized")
        update_planning_file(
            initial_state,
            status="initialized",
            objective=initial_state.get("current_objective", initial_state.get("user_query", "")),
            plan_text=initial_state.get("plan", ""),
            clarifications=initial_state.get("plan_clarification_questions", []),
            execution_note="Session initialized.",
        )
        append_privileged_audit_event(
            initial_state,
            actor="runtime",
            action="run_initialized",
            status="ok",
            detail={
                "run_id": initial_state.get("run_id", ""),
                "working_directory": initial_state.get("working_directory", ""),
                "privileged_policy": initial_state.get("privileged_policy", {}),
            },
        )
        return initial_state

    def invoke(self, initial_state: RuntimeState) -> RuntimeState:
        app = self.build_workflow()
        return app.invoke(initial_state)

    def run_query(
        self,
        user_query: str,
        *,
        state_overrides: ResumeStateOverrides | None = None,
        create_outputs: bool = True,
    ) -> RuntimeState:
        initialize_db()
        overrides: ResumeStateOverrides = dict(state_overrides or {})
        if not overrides.get("channel_session_key"):
            overrides["channel_session_key"] = self._base_channel_session_key(overrides)
        existing_channel_session = None
        if overrides.get("channel_session_key"):
            existing_channel_session = get_channel_session(str(overrides.get("channel_session_key")))
            if existing_channel_session:
                overrides["channel_session"] = existing_channel_session
        working_directory = self._resolve_working_directory(overrides)
        run_id = overrides.get("run_id", self.new_run_id())
        started_at = datetime.now(timezone.utc).isoformat()
        requested_output_dir = str(overrides.get("resume_output_dir") or overrides.get("run_output_dir") or "").strip()
        if requested_output_dir:
            run_output_dir = set_active_output_dir(str(Path(requested_output_dir).expanduser().resolve()), append=True)
        elif create_outputs:
            run_output_dir = create_run_output_dir(run_id, base_dir=working_directory)
        else:
            run_output_dir = set_active_output_dir(working_directory, append=False)
        insert_run(
            run_id,
            user_query,
            started_at,
            "running",
            updated_at=started_at,
            working_directory=working_directory,
            run_output_dir=run_output_dir,
            session_id=str(overrides.get("session_id", "")).strip(),
            parent_run_id=str(overrides.get("parent_run_id", "")).strip(),
            resumable=True,
        )
        work_note_header = f"Run ID: {run_id}\nStarted At: {started_at}\nUser Query: {user_query}\n{'=' * 72}\n\n"
        if requested_output_dir:
            append_text_file("agent_work_notes.txt", work_note_header)
        else:
            reset_text_file("agent_work_notes.txt", work_note_header)
        initial_state_overrides = dict(overrides)
        initial_state_overrides["run_id"] = run_id
        initial_state_overrides["run_output_dir"] = run_output_dir
        initial_state_overrides["working_directory"] = working_directory
        initial_state = self.build_initial_state(
            user_query,
            **initial_state_overrides,
        )
        if self._kill_switch_triggered(initial_state):
            raise RuntimeError("Kill switch triggered. Remove kill-switch file to continue.")
        if not self._is_agent_available(initial_state, "worker_agent"):
            raise RuntimeError("Core LLM setup is incomplete. OPENAI_API_KEY is required before the agent system can run.")
        initial_state = append_message(initial_state, make_message("user", "orchestrator_agent", "request", user_query))
        record_work_note(initial_state, "user", "request", user_query)
        append_daily_memory_note(initial_state, "user", "request", user_query)
        self._write_session_record(initial_state, status="running")
        try:
            app = self.build_workflow()
            self.save_graph(app)
            result = app.invoke(initial_state)
            final_output = result.get("final_output") or result.get("draft_response", "")
            if create_outputs:
                write_text_file("final_output.txt", final_output)
            completed_at = datetime.now(timezone.utc).isoformat()
            final_status = "awaiting_user_input" if self._awaiting_user_input(result) else "completed"
            update_run(run_id, status=final_status, completed_at=completed_at, final_output=final_output)
            append_daily_memory_note(result, "system", f"run_{final_status}", self._truncate(final_output, 1000))
            if final_status == "completed":
                append_long_term_memory(result, "Run Summary", self._truncate(final_output, 1200))
            self._write_session_record(result, status=final_status, completed_at=completed_at)
            update_planning_file(
                result,
                status=final_status,
                objective=result.get("current_objective", result.get("user_query", "")),
                plan_text=result.get("plan", ""),
                clarifications=result.get("plan_clarification_questions", []),
                execution_note="Run completed." if final_status == "completed" else "Run paused pending user input.",
            )
            close_session_memory(result, status=final_status, final_output=final_output)
            append_privileged_audit_event(
                result,
                actor="runtime",
                action="run_completed" if final_status == "completed" else "run_paused",
                status="ok",
                detail={"run_id": run_id, "final_output_excerpt": self._truncate(final_output, 400)},
            )
            return result
        except Exception:
            update_run(run_id, status="failed", completed_at=datetime.now(timezone.utc).isoformat(), final_output="workflow failed")
            if not initial_state.get("failure_checkpoint"):
                fallback_error = initial_state.get("last_error", "workflow failed")
                initial_state["failure_checkpoint"] = self._build_failure_checkpoint(
                    initial_state,
                    agent_name=initial_state.get("last_agent", "runtime"),
                    error_message=fallback_error,
                    active_task=initial_state.get("active_task"),
                )
            append_daily_memory_note(initial_state, "system", "run_failed", initial_state.get("last_error", "workflow failed"))
            self._write_session_record(initial_state, status="failed", completed_at=datetime.now(timezone.utc).isoformat())
            update_planning_file(
                initial_state,
                status="failed",
                objective=initial_state.get("current_objective", initial_state.get("user_query", "")),
                plan_text=initial_state.get("plan", ""),
                clarifications=initial_state.get("plan_clarification_questions", []),
                execution_note=f"Run failed: {initial_state.get('last_error', 'workflow failed')}",
            )
            close_session_memory(initial_state, status="failed", final_output=initial_state.get("last_error", "workflow failed"))
            append_privileged_audit_event(
                initial_state,
                actor="runtime",
                action="run_failed",
                status="error",
                detail={"run_id": run_id, "error": initial_state.get("last_error", "workflow failed")},
            )
            raise
        finally:
            set_active_output_dir(OUTPUT_DIR)
