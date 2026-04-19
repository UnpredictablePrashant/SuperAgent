from __future__ import annotations

import json
import os
import re
import shlex
import time
import uuid
from contextlib import nullcontext
from concurrent.futures import ThreadPoolExecutor, as_completed
from copy import deepcopy
from collections.abc import Mapping
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from langgraph.graph import END, StateGraph
from kendr.approval_resume_handlers import restore_pending_user_input
from kendr.orchestration import (
    CycleError,
    ResumeStateOverrides,
    RuntimeState,
    TaskGraph,
    annotate_plan_steps,
    build_intent_candidates,
    can_parallelize_step_batch,
    state_awaiting_user_input,
)
from kendr.execution_trace import append_execution_event, render_execution_event_line
from kendr.domain.deep_research import build_source_strategy, discover_research_intent
from kendr.direct_tools import run_direct_tool_loop
from kendr.persistence import (
    claim_plan_task,
    get_channel_session,
    get_latest_execution_plan,
    initialize_db,
    insert_agent_execution,
    insert_orchestration_event,
    insert_run,
    insert_run_checkpoint,
    release_plan_task_lease,
    replace_intent_candidates,
    replace_plan_tasks,
    resolve_db_path,
    update_execution_plan_status,
    update_plan_task_state,
    update_run,
    upsert_execution_plan,
    upsert_channel_session,
    upsert_task_session,
)
from kendr.path_utils import normalize_host_path_str
from kendr.machine_index import machine_sync_status
from kendr.software_inventory import is_inventory_stale, load_inventory_snapshot
from kendr.setup import build_setup_snapshot
from kendr.agent_routing import build_agent_routing_index, AgentRoutingIndex
from kendr.workflow_contract import is_deep_research_workflow_type, normalize_approval_request
from kendr.workflow_execution_policies import dispatch_workflow_execution_policies
from kendr.workflow_registry import WorkflowDispatchPlan
from kendr.model_workflows import build_workflow_recommendations

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
    console_logging_suppressed,
    create_run_output_dir,
    llm,
    log_task_update,
    logger,
    record_work_note,
    resolve_output_path,
    reset_text_file,
    runtime_model_override,
    set_active_output_dir,
    write_text_file,
)
from .recovery import write_recovery_files

from .registry import Registry


_DEEP_RESEARCH_OUTPUT_ONLY_BLOCKED_AGENTS = {
    "project_blueprint_agent",
    "master_coding_agent",
    "coding_agent",
    "dev_pipeline_agent",
    "project_scaffold_agent",
    "database_architect_agent",
    "auth_security_agent",
    "backend_builder_agent",
    "frontend_builder_agent",
    "dependency_manager_agent",
    "test_agent",
    "devops_agent",
    "project_verifier_agent",
    "post_setup_agent",
}

_DEEP_RESEARCH_CAPABILITY_ALLOWED_AGENTS = {
    "long_document_agent",
    "report_agent",
    "reviewer_agent",
    "planner_agent",
    "worker_agent",
    "os_agent",
    "document_formatter_agent",
    "local_drive_agent",
    "document_ingestion_agent",
    "ocr_agent",
    "excel_agent",
    "image_agent",
    "research_pipeline_agent",
}

_DEEP_RESEARCH_CAPABILITY_ALLOWED_SKILLS = {
    "web-search",
    "pdf-reader",
    "file-reader",
    "file-finder",
    "doc-summarizer",
    "spreadsheet-basic",
}


def _truthy(value: Any, default: bool = False) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


class AgentRuntime:
    _PLAN_SUCCESS_STATUSES = {"completed", "skipped"}
    _PLAN_ACTIVE_STATUSES = {"running"}
    _PLAN_BLOCKED_STATUSES = {"failed", "blocked", "cancelled"}
    _PLAN_OPEN_STATUSES = {"pending", "queued", "ready", "waiting", ""}
    _PARALLEL_PLAN_EXECUTOR = "__parallel_plan_executor__"
    _DEFAULT_MAX_PARALLEL_READ_TASKS = 3
    _DEFAULT_MAX_NO_PROGRESS_CYCLES = 6

    def __init__(self, registry: Registry):
        self.registry = registry
        self.agent_routing: AgentRoutingIndex = build_agent_routing_index(registry)
        self._live_plan_data: dict = {}
        _ar_summary = self.agent_routing.summary()
        if not console_logging_suppressed():
            print(
                f"[kendr] Agent routing index ready: "
                f"{_ar_summary['active']} active / {_ar_summary['total']} total agents across "
                f"{len(_ar_summary.get('by_category', {}))} categories."
            )

    def _agent_cards(self) -> list[dict]:
        return self.registry.agent_cards()

    def _deep_research_skill_agent_names(self) -> set[str]:
        skill_agents: set[str] = set()
        for slug in _DEEP_RESEARCH_CAPABILITY_ALLOWED_SKILLS:
            safe_slug = "".join(char if char.isalnum() else "_" for char in str(slug).lower()).strip("_")
            if safe_slug:
                skill_agents.add(f"skill_{safe_slug}_agent")
        return skill_agents

    def _use_deep_research_capability_profile(self, state: Mapping[str, Any]) -> bool:
        workflow_type = str(state.get("workflow_type", "") or "").strip().lower()
        selected_intent_type = str(state.get("selected_intent_type", "") or "").strip().lower()
        return (
            workflow_type in {"deep_research", "long_document"}
            or selected_intent_type in {"deep_research", "long_document"}
            or bool(state.get("deep_research_mode", False))
            or bool(state.get("long_document_mode", False))
        )

    def _apply_deep_research_capability_profile(self, state: dict) -> dict:
        allowed_agents = set(_DEEP_RESEARCH_CAPABILITY_ALLOWED_AGENTS) | self._deep_research_skill_agent_names()

        active_task = state.get("active_task")
        if isinstance(active_task, dict):
            recipient = str(active_task.get("recipient", "") or "").strip()
            if recipient:
                allowed_agents.add(recipient)

        for key in ("next_agent", "last_agent", "review_target_agent", "review_subject_agent"):
            name = str(state.get(key, "") or "").strip()
            if name:
                allowed_agents.add(name)

        for step in list(state.get("plan_steps") or []):
            if not isinstance(step, dict):
                continue
            name = str(step.get("agent", "") or "").strip()
            if name:
                allowed_agents.add(name)

        available_agents = [
            name for name in list(state.get("available_agents") or [])
            if str(name or "").strip() in allowed_agents
        ]
        state["available_agents"] = available_agents

        cards = [
            card for card in list(state.get("available_agent_cards") or [])
            if str(card.get("agent_name", "") or "").strip() in allowed_agents
        ]
        state["available_agent_cards"] = cards

        disabled_agents = state.get("disabled_agents", {})
        if isinstance(disabled_agents, dict):
            state["disabled_agents"] = {
                name: details
                for name, details in disabled_agents.items()
                if str(name or "").strip() in allowed_agents
            }

        connector_catalog = list(state.get("connector_catalog") or [])
        filtered_catalog = [
            item for item in connector_catalog
            if isinstance(item, dict)
            and str(item.get("agent_name", "") or "").strip() in allowed_agents
            and str(item.get("connector_type", "") or "").strip() != "mcp_tool"
        ]
        state["connector_catalog"] = filtered_catalog

        try:
            from kendr.connector_registry import ConnectorSpec, connector_catalog_prompt_block as _catalog_prompt

            filtered_specs = [
                ConnectorSpec(
                    agent_name=str(item.get("agent_name", "") or "").strip(),
                    connector_type=str(item.get("connector_type", "") or "").strip() or "task_agent",
                    display_name=str(item.get("display_name", "") or "").strip(),
                    description=str(item.get("description", "") or "").strip(),
                    icon=str(item.get("icon", "") or "").strip(),
                    status=str(item.get("status", "") or "").strip() or "ready",
                    category=str(item.get("category", "") or "").strip() or "General",
                    state_input_key=str(item.get("state_input_key", "") or "").strip(),
                    input_schema=item.get("input_schema") if isinstance(item.get("input_schema"), dict) else {},
                    required_inputs=list(item.get("required_inputs") or []),
                    state_output_key=str(item.get("state_output_key", "") or "").strip() or "draft_response",
                    output_schema=item.get("output_schema") if isinstance(item.get("output_schema"), dict) else {},
                    missing_config=list(item.get("missing_config") or []),
                    metadata=item.get("metadata") if isinstance(item.get("metadata"), dict) else {},
                )
                for item in filtered_catalog
            ]
            state["connector_catalog_prompt"] = _catalog_prompt(
                filtered_specs,
                include_types={"skill", "task_agent"},
                only_ready=True,
                max_per_type=8,
            )
        except Exception:
            state["connector_catalog_prompt"] = ""

        try:
            state["skills_context"] = self.agent_routing.user_skills_prompt_block(
                allowed_slugs=set(_DEEP_RESEARCH_CAPABILITY_ALLOWED_SKILLS),
                max_items=6,
            ) or ""
        except Exception:
            state["skills_context"] = ""

        state["mcp_servers_context"] = ""

        visible_agents = ", ".join(available_agents[:10]) if available_agents else "none"
        state["setup_summary"] = (
            "Deep research capability profile active. "
            f"Visible research agents/connectors: {visible_agents}."
        )
        return state

    def _resolve_working_directory(self, state_overrides: dict | None = None) -> str:
        overrides = state_overrides or {}
        working_dir = str(overrides.get("working_directory") or overrides.get("KENDR_WORKING_DIR") or os.getenv("KENDR_WORKING_DIR", "")).strip()
        if not working_dir:
            raise RuntimeError(
                "Working folder is not configured. Set KENDR_WORKING_DIR in Setup UI (Core Runtime), "
                "or pass state_overrides['working_directory'] before running tasks."
            )
        resolved = Path(normalize_host_path_str(working_dir))
        resolved.mkdir(parents=True, exist_ok=True)
        return str(resolved)

    def _agent_descriptions(self) -> dict[str, str]:
        return self.registry.agent_descriptions()

    def _apply_workflow_dispatch_plan(self, state: dict, plan: WorkflowDispatchPlan) -> dict:
        for key, value in (plan.state_mutations or {}).items():
            state[key] = value
        state["orchestrator_reason"] = str(plan.reason or "").strip()
        state["next_agent"] = str(plan.agent_name or "").strip()
        if state["orchestrator_reason"]:
            log_task_update("Orchestrator", state["orchestrator_reason"])
        state = append_task(
            state,
            make_task(
                sender="orchestrator_agent",
                recipient=str(plan.agent_name or "").strip(),
                intent=str(plan.intent or "").strip(),
                content=str(plan.content or "").strip(),
                state_updates=dict(plan.state_updates or {}),
            ),
        )
        if str(plan.decision_note or "").strip():
            record_work_note(state, "orchestrator_agent", "decision", str(plan.decision_note).strip())
        return state

    def apply_runtime_setup(self, state: dict) -> dict:
        working_dir = str(state.get("working_directory", "") or "").strip()
        if working_dir:
            state["working_directory"] = normalize_host_path_str(working_dir)
        project_root = str(state.get("project_root", "") or "").strip()
        if project_root:
            state["project_root"] = normalize_host_path_str(project_root, base_dir=state.get("working_directory", ""))

        snapshot = build_setup_snapshot(self._agent_cards())
        available_agents = snapshot.get("available_agents", [])
        # Exclude MCP-backed agents when use_mcp is explicitly False
        use_mcp = state.get("use_mcp")
        if use_mcp is False:
            available_agents = [a for a in available_agents if not str(a).startswith("mcp_")]
        filtered_cards = [card for card in self._agent_cards() if card["agent_name"] in available_agents]
        state["setup_status"] = snapshot
        state["available_agents"] = available_agents
        state["disabled_agents"] = snapshot.get("disabled_agents", {})
        state["setup_actions"] = snapshot.get("setup_actions", [])
        state["setup_summary"] = snapshot.get("summary_text", "")
        state["available_agent_cards"] = filtered_cards
        # Build unified connector catalog for the orchestrator prompt.
        # This replaces the old separate mcp_servers_context / skills_context
        # and surfaces exact state_input_key + required_inputs for each connector
        # so the LLM knows precisely how to invoke skills and MCP tools.
        try:
            from kendr.connector_registry import (
                build_connector_catalog as _build_catalog,
                connector_catalog_prompt_block as _catalog_prompt,
            )
            _all_specs = _build_catalog(self.registry, self.agent_routing)
            # Honour use_mcp flag: hide mcp_tool connectors if toggled off
            if state.get("use_mcp") is False:
                _all_specs = [s for s in _all_specs if s.connector_type != "mcp_tool"]
            state["connector_catalog"] = [s.to_dict() for s in _all_specs]
            state["connector_catalog_prompt"] = _catalog_prompt(_all_specs)
        except Exception:
            state["connector_catalog"] = []
            state["connector_catalog_prompt"] = ""
        # Keep legacy keys populated for any code that still reads them
        try:
            from kendr.mcp_manager import list_servers_safe as _list_mcp_safe
            _mcp_servers = _list_mcp_safe()
            _mcp_lines = []
            for _s in _mcp_servers:
                if not _s.get("enabled", True):
                    continue
                _tools = [t.get("name", "") for t in (_s.get("tools") or []) if t.get("name")]
                _mcp_lines.append(
                    f"  - {_s.get('name', _s.get('id', 'unknown'))}"
                    + (f": {', '.join(_tools)}" if _tools else " (no tools discovered)")
                )
            state["mcp_servers_context"] = "\n".join(_mcp_lines) if _mcp_lines else "None connected"
        except Exception:
            state["mcp_servers_context"] = "unavailable"
        try:
            state["skills_context"] = self.agent_routing.user_skills_prompt_block() or "No custom skills installed"
        except Exception:
            state["skills_context"] = "unavailable"
        if self._use_deep_research_capability_profile(state):
            state = self._apply_deep_research_capability_profile(state)
        ensure_a2a_state(state, state.get("available_agent_cards") or filtered_cards)
        return state

    def _db_path(self, state: Mapping[str, Any]) -> str:
        return str(state.get("db_path", "") or "").strip() or resolve_db_path()

    def _intent_flags(self, state: Mapping[str, Any]) -> dict[str, bool]:
        snapshot = dict(state)
        return {
            "security_assessment": bool(snapshot.get("security_authorized", False))
            or bool(str(snapshot.get("security_target_url", "")).strip())
            or any(marker in self._objective_text(snapshot).lower() for marker in ("security", "vulnerability", "pentest", "scan ")),
            "local_command": self._is_local_command_request(snapshot),
            "shell_plan": self._is_shell_plan_request(snapshot),
            "github": self._is_github_request(snapshot),
            "registry_discovery": self._is_registry_discovery_request(snapshot),
            "communication_digest": self._is_communication_summary_request(snapshot),
            "project_build": self._is_project_build_request(snapshot),
            "long_document": self._is_long_document_request(snapshot),
            "deep_research": self._is_deep_research_workflow(snapshot),
            "superrag": self._is_superrag_request(snapshot),
            "local_drive": self._has_local_drive_request(snapshot),
        }

    def _record_orchestration_event(
        self,
        state: Mapping[str, Any],
        *,
        event_type: str,
        subject_type: str,
        subject_id: str,
        status: str = "",
        payload: dict[str, Any] | None = None,
        plan_id: str = "",
    ) -> None:
        run_id = str(state.get("run_id", "")).strip()
        if not run_id:
            return
        try:
            insert_orchestration_event(
                {
                    "run_id": run_id,
                    "plan_id": plan_id or str(state.get("orchestration_plan_id", "")).strip(),
                    "subject_type": subject_type,
                    "subject_id": subject_id,
                    "event_type": event_type,
                    "status": status,
                    "source": "runtime",
                    "payload": dict(payload or {}),
                },
                db_path=self._db_path(state),
            )
        except Exception:
            pass

    def _refresh_intent_projection(self, state: dict[str, Any]) -> dict[str, Any]:
        objective_text = str(state.get("current_objective") or state.get("user_query") or "").strip()
        if not objective_text:
            return state
        flags = self._intent_flags(state)
        planner_signals = self._planner_signal_snapshot(state)
        discovery = build_intent_candidates(
            user_query=str(state.get("user_query", "") or ""),
            current_objective=objective_text,
            flags=flags,
            planner_signals=planner_signals,
        )
        signature = str(discovery.get("objective_signature", "")).strip()
        selected = discovery.get("selected", {}) if isinstance(discovery.get("selected"), dict) else {}
        state["intent_signature"] = signature
        state["intent_candidates"] = discovery.get("candidates", [])
        state["selected_intent"] = selected
        state["selected_intent_id"] = str(selected.get("intent_id", "")).strip()
        state["selected_intent_type"] = str(selected.get("intent_type", "")).strip()
        if (
            signature
            and state.get("_persisted_intent_signature") == signature
            and state.get("_persisted_selected_intent_id") == state.get("selected_intent_id", "")
        ):
            return state
        run_id = str(state.get("run_id", "")).strip()
        if run_id and signature:
            try:
                replace_intent_candidates(
                    run_id,
                    list(state.get("intent_candidates", [])),
                    objective_signature=signature,
                    db_path=self._db_path(state),
                )
                self._record_orchestration_event(
                    state,
                    event_type="intent.discovered",
                    subject_type="intent",
                    subject_id=state["selected_intent_id"] or signature,
                    status="selected",
                    payload={
                        "objective_signature": signature,
                        "selected_intent_type": state.get("selected_intent_type", ""),
                        "candidate_count": len(state.get("intent_candidates", []) or []),
                    },
                )
                state["_persisted_intent_signature"] = signature
                state["_persisted_selected_intent_id"] = state.get("selected_intent_id", "")
            except Exception:
                pass
        return state

    def _plan_status_from_state(self, state: Mapping[str, Any], *, final_status: str = "") -> str:
        if final_status in {"failed", "cancelled", "completed"}:
            return final_status
        if bool(state.get("plan_needs_clarification", False)):
            return "needs_clarification"
        if bool(state.get("plan_waiting_for_approval", False)):
            return "awaiting_approval"
        approval_status = str(state.get("plan_approval_status", "") or "").strip().lower()
        if approval_status == "revision_requested":
            return "revision_requested"
        if approval_status == "approved":
            steps = state.get("plan_steps", [])
            if not isinstance(steps, list) or not steps:
                return "approved"
            status_snapshot = self._plan_status_snapshot(dict(state))
            if status_snapshot["blocked"]:
                return "failed"
            if len(status_snapshot["success"]) >= len([step for step in steps if isinstance(step, dict)]):
                return "completed"
            if status_snapshot["active"] or str(state.get("planned_active_step_id", "") or "").strip():
                return "executing"
            return "ready"
        if state.get("plan_steps"):
            return "draft"
        return final_status or "draft"

    def _sync_orchestration_plan_record(self, state: dict[str, Any], *, final_status: str = "") -> dict[str, Any]:
        run_id = str(state.get("run_id", "")).strip()
        if not run_id or not (state.get("plan_steps") or state.get("plan_data")):
            return state
        plan_id = str(state.get("orchestration_plan_id", "")).strip()
        plan_version = int(state.get("orchestration_plan_version", state.get("plan_version", 0)) or state.get("plan_version", 0) or 0)
        if not plan_id:
            latest_plan = get_latest_execution_plan(run_id, db_path=self._db_path(state))
            if latest_plan:
                plan_id = str(latest_plan.get("plan_id", "")).strip()
                plan_version = int(latest_plan.get("version", plan_version or 0) or plan_version or 0)
            elif plan_version > 0:
                plan_id = f"{run_id}:plan:v{plan_version}"
        if not plan_id:
            return state
        plan_version = max(1, plan_version or 1)
        desired_status = self._plan_status_from_state(state, final_status=final_status)
        try:
            if not get_latest_execution_plan(run_id, db_path=self._db_path(state)) or not str(state.get("orchestration_plan_id", "")).strip():
                upsert_execution_plan(
                    plan_id,
                    run_id=run_id,
                    intent_id=str(state.get("selected_intent_id", "")).strip(),
                    version=plan_version,
                    status=desired_status,
                    approval_status=str(state.get("plan_approval_status", "")).strip() or "not_started",
                    needs_clarification=bool(state.get("plan_needs_clarification", False)),
                    objective=str(state.get("current_objective", state.get("user_query", ""))).strip(),
                    summary=str((state.get("plan_data", {}) or {}).get("summary", "")).strip(),
                    plan_markdown=str(state.get("plan", "")).strip(),
                    plan_data=dict(state.get("plan_data", {}) or {}),
                    metadata={
                        "plan_step_index": int(state.get("plan_step_index", 0) or 0),
                        "selected_intent_id": str(state.get("selected_intent_id", "")).strip(),
                    },
                    db_path=self._db_path(state),
                )
                replace_plan_tasks(
                    plan_id,
                    run_id,
                    list(state.get("plan_steps", []) or []),
                    db_path=self._db_path(state),
                )
                state["orchestration_plan_id"] = plan_id
                state["orchestration_plan_version"] = plan_version
            updated = update_execution_plan_status(
                plan_id,
                status=desired_status,
                approval_status=str(state.get("plan_approval_status", "")).strip() or "not_started",
                needs_clarification=bool(state.get("plan_needs_clarification", False)),
                metadata={
                    "plan_step_index": int(state.get("plan_step_index", 0) or 0),
                    "selected_intent_id": str(state.get("selected_intent_id", "")).strip(),
                    "final_status": final_status,
                },
                db_path=self._db_path(state),
            )
            if updated:
                state["orchestration_plan_id"] = str(updated.get("plan_id", "")).strip() or plan_id
                state["orchestration_plan_version"] = int(updated.get("version", plan_version) or plan_version)
            if state.get("_persisted_plan_status") != desired_status:
                self._record_orchestration_event(
                    state,
                    event_type="plan.status_changed",
                    subject_type="plan",
                    subject_id=state.get("orchestration_plan_id", plan_id),
                    status=desired_status,
                    payload={
                        "approval_status": state.get("plan_approval_status", ""),
                        "needs_clarification": bool(state.get("plan_needs_clarification", False)),
                        "plan_step_index": int(state.get("plan_step_index", 0) or 0),
                    },
                )
                state["_persisted_plan_status"] = desired_status
        except Exception:
            pass
        return state

    _DEFAULT_MAX_CONSECUTIVE_FAILURES = 3
    _DEFAULT_MAX_SAME_AGENT_DISPATCHES = 5
    _NON_REVIEW_AGENTS = {
        "channel_gateway_agent",
        "session_router_agent",
        # Data-collection agents whose output feeds into a synthesis step.
        # Adding them here prevents the reviewer from intercepting before synthesis.
        "research_pipeline_agent",
        "deep_research_agent",
        "local_drive_agent",
    }
    _CRITICAL_REVIEW_AGENTS = {
        "master_coding_agent",
        "backend_builder_agent",
        "frontend_builder_agent",
        "database_architect_agent",
        "auth_security_agent",
        "devops_agent",
        "security_scanner_agent",
        "project_verifier_agent",
    }
    _PLANNER_COMPLEXITY_MARKERS = (
        "build",
        "implement",
        "integrate",
        "migrate",
        "pipeline",
        "architecture",
        "multi-agent",
        "end-to-end",
        "full stack",
        "production",
        "deploy",
        "workflow",
        "coordinate",
        "analyze",
        "refactor",
    )
    _RISK_MARKERS = (
        "security",
        "auth",
        "payment",
        "production",
        "compliance",
        "legal",
        "privacy",
        "delete",
        "destructive",
        "credential",
        "permission",
        "migration",
    )

    def _is_agent_available(self, state: dict, agent_name: str) -> bool:
        if agent_name in (state.get("_circuit_broken_agents") or {}):
            return False
        if self._is_deep_research_workflow(dict(state)) and agent_name in _DEEP_RESEARCH_OUTPUT_ONLY_BLOCKED_AGENTS:
            return False
        return agent_name in set(state.get("available_agents", []))

    def _effective_available_agents(self, state: Mapping[str, Any]) -> list[str]:
        available = [
            str(name).strip()
            for name in state.get("available_agents", [])
            if str(name).strip()
        ]
        blocked = {
            str(name).strip()
            for name in state.get("_policy_blocked_agents", [])
            if str(name).strip()
        }
        if not blocked:
            return available
        return [name for name in available if name not in blocked]

    def _resolve_policy_mode(
        self,
        state: Mapping[str, Any],
        *,
        primary_key: str,
        aliases: tuple[str, ...] = (),
        default: str = "adaptive",
    ) -> str:
        raw_value: Any = None
        if primary_key in state:
            raw_value = state.get(primary_key)
        else:
            for alias in aliases:
                if alias in state:
                    raw_value = state.get(alias)
                    break
        if isinstance(raw_value, bool):
            return "always" if raw_value else "never"
        value = str(raw_value or default).strip().lower()
        if value in {"adaptive", "auto", "dynamic", "smart"}:
            return "adaptive"
        if value in {"always", "force", "required", "on", "true", "1"}:
            return "always"
        if value in {"never", "off", "disabled", "skip", "false", "0"}:
            return "never"
        return default

    def _resolve_execution_mode(self, state: Mapping[str, Any], *, default: str = "adaptive") -> str:
        raw_value = state.get("execution_mode", "")
        value = str(raw_value or "").strip().lower()
        if value in {"direct", "direct_tools", "tool", "tools", "agent", "agent_mode"}:
            return "direct_tools"
        if value in {"plan", "planning", "plan_mode"}:
            return "plan"
        if value in {"adaptive", "auto", "default", ""}:
            planner_mode = self._resolve_policy_mode(
                state,
                primary_key="planner_policy_mode",
                aliases=("planner_mode",),
                default="adaptive",
            )
            if planner_mode == "never":
                return "direct_tools"
            if planner_mode == "always":
                return "plan"
            return "adaptive"
        return default

    def _objective_text(self, state: Mapping[str, Any]) -> str:
        return " ".join(
            [
                str(state.get("user_query", "") or ""),
                str(state.get("current_objective", "") or ""),
            ]
        ).strip()

    def _word_count(self, text: str) -> int:
        return len(re.findall(r"[A-Za-z0-9_]+", str(text or "")))

    def _count_markers(self, text: str, markers: tuple[str, ...]) -> int:
        lowered = str(text or "").lower()
        return sum(1 for marker in markers if marker in lowered)

    def _planner_signal_snapshot(self, state: Mapping[str, Any]) -> dict[str, Any]:
        text = self._objective_text(state).lower()
        word_count = self._word_count(text)
        conjunction_count = sum(
            text.count(token) for token in (" and ", " then ", " after ", " before ", " while ", " also ")
        )
        complexity_markers = self._count_markers(text, self._PLANNER_COMPLEXITY_MARKERS)
        risk_markers = self._count_markers(text, self._RISK_MARKERS)
        explicit_plan_request = bool(re.search(r"\b(plan|roadmap|step[\s-]*by[\s-]*step|phase[s]?)\b", text))
        has_structured_inputs = bool(
            self._has_local_drive_request(dict(state))
            or self._is_superrag_request(dict(state))
            or state.get("blueprint_json")
            or state.get("incoming_payload")
        )
        return {
            "word_count": word_count,
            "conjunction_count": conjunction_count,
            "complexity_markers": complexity_markers,
            "risk_markers": risk_markers,
            "explicit_plan_request": explicit_plan_request,
            "has_structured_inputs": has_structured_inputs,
            "setup_actions": len(state.get("setup_actions", []) or []),
            "plan_revision_feedback": bool(str(state.get("plan_revision_feedback", "")).strip()),
        }

    def _should_run_planner(self, state: Mapping[str, Any]) -> tuple[bool, str, dict[str, Any]]:
        execution_mode = self._resolve_execution_mode(state, default="adaptive")
        if execution_mode == "direct_tools":
            return False, "Direct tool mode selected: skip planner and route through tool-capable agents.", {"execution_mode": execution_mode}
        if execution_mode == "plan":
            return True, "Plan mode selected: planner is required before execution.", {"execution_mode": execution_mode}

        mode = self._resolve_policy_mode(
            state,
            primary_key="planner_policy_mode",
            aliases=("planner_mode",),
            default="adaptive",
        )
        adaptive_enabled = _truthy(state.get("adaptive_agent_selection"), True)
        if mode == "never":
            return False, "Planner disabled by policy mode.", {"mode": mode}
        if mode == "always":
            return True, "Planner required by policy mode.", {"mode": mode}
        if not adaptive_enabled:
            return True, "Adaptive selection disabled; planner runs by default.", {"mode": mode}
        if state.get("plan_steps") or bool(state.get("plan_ready", False)):
            return False, "Plan already exists in state.", {"mode": mode}
        if self._awaiting_user_input(state):
            return False, "Run is waiting for user input.", {"mode": mode}
        selected_intent = state.get("selected_intent")
        if isinstance(selected_intent, Mapping):
            intent_type = str(selected_intent.get("intent_type", "")).strip()
            requires_planner = bool(selected_intent.get("requires_planner", False))
            intent_mode = str(selected_intent.get("execution_mode", "")).strip().lower()
            intent_signals = {
                "mode": mode,
                "intent_type": intent_type,
                "intent_execution_mode": intent_mode,
                "intent_requires_planner": requires_planner,
            }
            if requires_planner and intent_type:
                return True, f"Intent '{intent_type}' requires staged planning.", intent_signals
            if intent_mode in {"direct", "direct_tools"} and intent_type and intent_type != "general_task":
                return False, f"Intent '{intent_type}' routes directly without the generic planner.", intent_signals
        if self._is_local_command_request(dict(state)):
            return False, "Local command workflow routes directly to os_agent.", {"mode": mode}
        if self._is_shell_plan_request(dict(state)):
            return False, "Shell setup workflow routes directly to shell_plan_agent.", {"mode": mode}
        if self._is_github_request(dict(state)):
            return False, "GitHub workflow routes directly to github_agent.", {"mode": mode}
        if self._is_communication_summary_request(dict(state)):
            return False, "Communication digest workflow routes directly.", {"mode": mode}
        if self._is_registry_discovery_request(dict(state)):
            return False, "Capability discovery request does not require planning.", {"mode": mode}
        if self._is_project_build_request(dict(state)):
            return True, "Project build workflow requires staged planning.", {"mode": mode}
        if self._is_long_document_request(dict(state)) or self._is_deep_research_workflow(dict(state)):
            return True, "Long-document/deep-research workflow requires planning.", {"mode": mode}
        if self._is_superrag_request(dict(state)):
            return True, "SuperRAG workflow requires planning.", {"mode": mode}
        if self._has_local_drive_request(dict(state)):
            return True, "Local-drive workflows require explicit planning.", {"mode": mode}

        signals = self._planner_signal_snapshot(state)
        score = 0
        words = int(signals["word_count"])
        if words >= 70:
            score += 3
        elif words >= 35:
            score += 2
        elif words >= 18:
            score += 1
        if int(signals["conjunction_count"]) >= 3:
            score += 2
        elif int(signals["conjunction_count"]) >= 1:
            score += 1
        if int(signals["complexity_markers"]) >= 2:
            score += 2
        elif int(signals["complexity_markers"]) >= 1:
            score += 1
        if int(signals["risk_markers"]) >= 2:
            score += 2
        elif int(signals["risk_markers"]) >= 1:
            score += 1
        if bool(signals["explicit_plan_request"]):
            score += 2
        if bool(signals["has_structured_inputs"]):
            score += 2
        if int(signals["setup_actions"]) > 0:
            score += 1
        if bool(signals["plan_revision_feedback"]):
            score += 1
        if words <= 12:
            score -= 2

        threshold = int(state.get("planner_score_threshold", 4) or 4)
        signals["score"] = score
        signals["threshold"] = threshold
        signals["mode"] = mode
        if score >= threshold:
            return True, "Adaptive planner policy selected staged planning.", signals
        return False, "Adaptive planner policy selected direct execution routing.", signals

    def _should_attempt_direct_tool_loop(self, state: Mapping[str, Any], *, in_task_phase: bool) -> bool:
        if self._resolve_execution_mode(state, default="adaptive") != "direct_tools":
            return False
        if not in_task_phase:
            return False
        if bool(state.get("direct_tool_loop_attempted", False)):
            return False
        if self._awaiting_user_input(state):
            return False
        if state.get("plan_steps") or bool(state.get("plan_ready", False)):
            return False
        if state.get("last_agent"):
            return False
        if self._is_project_build_request(dict(state)):
            return False
        if self._is_project_workbench_request(dict(state)):
            return False
        if self._is_project_audit_request(dict(state)):
            return False
        if self._is_deep_research_workflow(dict(state)) or self._is_long_document_request(dict(state)):
            return False
        if self._is_superrag_request(dict(state)):
            return False
        if self._has_local_drive_request(dict(state)):
            return False
        if self._is_github_request(dict(state)):
            return False
        if self._is_communication_summary_request(dict(state)):
            return False
        return True

    def _review_signal_snapshot(self, state: Mapping[str, Any], agent_name: str, output_text: str) -> dict[str, Any]:
        objective_text = self._objective_text(state).lower()
        review_subject_step = str(
            state.get("last_completed_plan_step_id")
            or state.get("current_plan_step_id")
            or ""
        ).strip()
        review_key = self._review_revision_key(review_subject_step, agent_name)
        revision_counts = state.get("review_revision_counts", {})
        if not isinstance(revision_counts, dict):
            revision_counts = {}
        success_criteria = str(
            state.get("last_completed_plan_step_success_criteria")
            or state.get("current_plan_step_success_criteria")
            or ""
        ).strip()
        output_words = self._word_count(output_text)
        return {
            "objective_word_count": self._word_count(objective_text),
            "output_word_count": output_words,
            "has_success_criteria": bool(success_criteria),
            "risk_markers": self._count_markers(f"{objective_text}\n{str(output_text or '').lower()}", self._RISK_MARKERS),
            "critical_agent": agent_name in self._CRITICAL_REVIEW_AGENTS,
            "project_build_mode": bool(state.get("project_build_mode", False)),
            "deep_research_workflow": self._is_deep_research_workflow(dict(state)),
            "previous_revisions": int(revision_counts.get(review_key, 0) or 0),
            "quality_gate_enforced": bool(state.get("enforce_quality_gate", True)),
        }

    def _should_request_review(
        self,
        state: Mapping[str, Any],
        *,
        agent_name: str,
        output_text: str,
        skip_review_once: bool = False,
    ) -> tuple[bool, str, dict[str, Any]]:
        mode = self._resolve_policy_mode(
            state,
            primary_key="reviewer_policy_mode",
            aliases=("reviewer_mode",),
            default="adaptive",
        )
        adaptive_enabled = _truthy(state.get("adaptive_agent_selection"), True)
        if agent_name == "reviewer_agent":
            return False, "Reviewer does not self-review.", {"mode": mode}
        if agent_name in self._NON_REVIEW_AGENTS:
            return False, f"{agent_name} is excluded from review.", {"mode": mode}
        if skip_review_once:
            return False, "Review skipped for this step by runtime guard.", {"mode": mode}
        if bool(state.get("skip_reviews", False)):
            return False, "Review skipped by run option.", {"mode": mode}
        if self._awaiting_user_input(state):
            return False, "Run is waiting for user input.", {"mode": mode}
        if mode == "never":
            return False, "Reviewer disabled by policy mode.", {"mode": mode}
        if mode == "always":
            return True, "Reviewer required by policy mode.", {"mode": mode}
        if not adaptive_enabled:
            return True, "Adaptive selection disabled; reviewer runs by default.", {"mode": mode}

        signals = self._review_signal_snapshot(state, agent_name, output_text)
        if bool(signals["quality_gate_enforced"]) and bool(signals["project_build_mode"]):
            return True, "Quality gate requires reviewer in project build mode.", signals
        if bool(signals["critical_agent"]) and int(signals["output_word_count"]) >= 40:
            return True, "Critical execution step requires reviewer validation.", signals
        if int(signals["previous_revisions"]) > 0:
            return True, "Step is in revision cycle; reviewer remains active.", signals

        score = 0
        output_words = int(signals["output_word_count"])
        objective_words = int(signals["objective_word_count"])
        if bool(signals["has_success_criteria"]):
            score += 2
        if output_words >= 250:
            score += 1
        if output_words >= 800:
            score += 2
        if objective_words >= 25:
            score += 1
        if objective_words >= 60:
            score += 1
        risk_markers = int(signals["risk_markers"])
        if risk_markers >= 1:
            score += 1
        if risk_markers >= 2:
            score += 1
        if bool(signals["critical_agent"]):
            score += 1
        if bool(signals["project_build_mode"]):
            score += 2
        if bool(signals["deep_research_workflow"]):
            score += 2
        if output_words < 60:
            score -= 2
        if objective_words < 12 and not bool(signals["has_success_criteria"]):
            score -= 1

        threshold = int(state.get("reviewer_score_threshold", 5) or 5)
        signals["score"] = score
        signals["threshold"] = threshold
        signals["mode"] = mode
        if score >= threshold:
            return True, "Adaptive reviewer policy selected quality validation.", signals
        return False, "Adaptive reviewer policy skipped review for this low-risk step.", signals

    def _policy_blocked_agents(self, state: Mapping[str, Any]) -> set[str]:
        blocked: set[str] = set()
        available = set(state.get("available_agents", []) or [])
        if self._is_deep_research_workflow(dict(state)):
            blocked.update(name for name in _DEEP_RESEARCH_OUTPUT_ONLY_BLOCKED_AGENTS if name in available)
        if "planner_agent" in available and not state.get("plan_steps") and not bool(state.get("plan_ready", False)):
            run_planner, _, _ = self._should_run_planner(state)
            if not run_planner:
                blocked.add("planner_agent")
        if "reviewer_agent" in available and not bool(state.get("review_pending", False)):
            blocked.add("reviewer_agent")
        return blocked

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
        if (
            "communication agents require explicit authorization" in error
            or "communication access is disabled" in error
            or "communication_authorized" in error
        ):
            return (
                "Communication access is disabled for this run. Communication workflows are enabled by default; "
                "use `--communication-authorized` / `--no-communication-authorized` (CLI), send "
                "`communication_authorized` in gateway payloads, or set `KENDR_COMMUNICATION_AUTHORIZED` "
                "for a global default. If you only wanted capability listing, ask "
                "`what skills/capabilities do you have` in chat, run `kendr agents list`, or call "
                "`GET /registry/skills` / `GET /registry/discovery/cards`."
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
        available = set(self._effective_available_agents(state))
        return {name: description for name, description in self._agent_descriptions().items() if name in available}

    def _agent_enum(self, state: dict, include_finish: bool = False) -> str:
        choices = self._effective_available_agents(state)
        if include_finish:
            choices.append("finish")
        return "|".join(choices)

    def _truncate(self, text: str, limit: int = 1200) -> str:
        cleaned = " ".join((text or "").split())
        if len(cleaned) <= limit:
            return cleaned
        return cleaned[: limit - 3] + "..."

    def _estimate_token_count(self, value: Any) -> int:
        try:
            if isinstance(value, str):
                payload = value
            else:
                payload = json.dumps(value, ensure_ascii=False)
        except Exception:
            payload = str(value)
        return max(1, (len(payload) + 3) // 4)

    def _router_token_budget(self, state: Mapping[str, Any]) -> int:
        raw = str(state.get("router_token_budget") or os.getenv("KENDR_ROUTER_TOKEN_BUDGET", "2200")).strip()
        try:
            budget = int(raw)
        except Exception:
            budget = 2200
        return max(600, budget)

    def _router_text_hint(self, text: str, limit: int) -> str:
        normalized = " ".join(str(text or "").split())
        if not normalized:
            return ""
        if normalized in {
            "No agents have run yet.",
            "No prior chat history provided for this turn.",
            "No A2A messages yet.",
            "None",
        }:
            return ""
        return self._truncate(normalized, limit)

    def _router_setup_action_hints(self, state: Mapping[str, Any], limit: int = 4) -> list[str]:
        rows: list[str] = []
        for item in list(state.get("setup_actions") or [])[:limit]:
            if not isinstance(item, dict):
                continue
            label = str(item.get("title") or item.get("service") or item.get("action") or "").strip()
            detail = str(item.get("summary") or item.get("description") or item.get("note") or "").strip()
            if label and detail:
                rows.append(self._truncate(f"{label}: {detail}", 160))
            elif label:
                rows.append(self._truncate(label, 160))
        return rows

    def _router_setup_gap_hints(self, state: Mapping[str, Any], limit: int = 6) -> list[str]:
        disabled = state.get("disabled_agents", {})
        if not isinstance(disabled, dict):
            return []
        rows: list[str] = []
        for agent_name, details in list(disabled.items())[:limit]:
            if not isinstance(details, dict):
                rows.append(str(agent_name))
                continue
            services = details.get("missing_services", [])
            reasons = details.get("reasons", [])
            reason_text = ""
            if isinstance(services, list) and services:
                reason_text = "missing " + ", ".join(str(item).strip() for item in services[:3] if str(item).strip())
            elif isinstance(reasons, list) and reasons:
                reason_text = ", ".join(str(item).strip() for item in reasons[:2] if str(item).strip())
            elif str(details.get("reason") or "").strip():
                reason_text = str(details.get("reason") or "").strip()
            if reason_text:
                rows.append(self._truncate(f"{agent_name}: {reason_text}", 180))
            else:
                rows.append(self._truncate(str(agent_name), 180))
        return rows

    def _router_candidate_agents(self, state: Mapping[str, Any], limit: int = 8) -> list[dict[str, str]]:
        available = self._available_agent_descriptions(dict(state))
        if not available:
            return []

        workflow_type = str(state.get("workflow_type", "") or "").strip().lower()
        selected_intent_type = str(state.get("selected_intent_type", "") or "").strip().lower()
        preferred_names: list[str] = []
        seen: set[str] = set()

        def add(name: str) -> None:
            normalized = str(name or "").strip()
            if not normalized or normalized in seen or normalized not in available:
                return
            seen.add(normalized)
            preferred_names.append(normalized)

        plan_summary = self._plan_step_summary(state)
        steps = plan_summary.get("plan_steps", [])
        index = int(plan_summary.get("plan_step_index", 0) or 0)
        if isinstance(steps, list):
            for step in steps[max(0, index - 1): index + 3]:
                if isinstance(step, dict):
                    add(str(step.get("agent") or "").strip())

        add(str(state.get("review_target_agent") or "").strip())
        add(str(state.get("review_subject_agent") or "").strip())

        workflow_hints = {
            "deep_research": [
                "long_document_agent",
                "deep_research_agent",
                "research_pipeline_agent",
                "local_drive_agent",
                "ocr_agent",
                "reviewer_agent",
                "report_agent",
                "planner_agent",
            ],
            "long_document": [
                "long_document_agent",
                "report_agent",
                "deep_research_agent",
                "reviewer_agent",
                "planner_agent",
            ],
            "project_build": [
                "master_coding_agent",
                "planner_agent",
                "reviewer_agent",
                "project_verifier_agent",
                "worker_agent",
            ],
            "project_workbench": [
                "worker_agent",
                "planner_agent",
                "reviewer_agent",
                "local_drive_agent",
            ],
            "project_audit": [
                "reviewer_agent",
                "planner_agent",
                "worker_agent",
                "project_verifier_agent",
            ],
            "local_command": [
                "os_agent",
                "planner_agent",
                "worker_agent",
            ],
            "github": [
                "github_agent",
                "planner_agent",
                "reviewer_agent",
            ],
        }
        intent_hints = {
            "deep_research": ["long_document_agent", "deep_research_agent", "research_pipeline_agent", "planner_agent"],
            "long_document": ["long_document_agent", "report_agent", "planner_agent"],
            "local_command": ["os_agent", "planner_agent", "worker_agent"],
            "github_ops": ["github_agent", "planner_agent", "reviewer_agent"],
            "project_build": ["master_coding_agent", "planner_agent", "project_verifier_agent"],
            "local_drive_analysis": ["local_drive_agent", "document_ingestion_agent", "ocr_agent", "planner_agent"],
            "superrag": ["planner_agent", "worker_agent", "reviewer_agent"],
            "general_task": ["planner_agent", "worker_agent", "reviewer_agent", "report_agent"],
        }
        for name in workflow_hints.get(workflow_type, []):
            add(name)
        for name in intent_hints.get(selected_intent_type, []):
            add(name)

        last_agent = str(state.get("last_agent", "") or "").strip()
        if last_agent and last_agent != "orchestrator_agent":
            add("reviewer_agent")

        for name in ("planner_agent", "worker_agent", "reviewer_agent", "report_agent"):
            add(name)

        for name in self._effective_available_agents(dict(state)):
            add(name)
            if len(preferred_names) >= limit:
                break

        return [
            {
                "name": name,
                "description": self._truncate(available.get(name, ""), 180),
            }
            for name in preferred_names[:limit]
        ]

    def _build_router_stage_toon(self, state: Mapping[str, Any], *, current_objective: str) -> dict[str, Any]:
        available_agent_names = [str(item).strip() for item in self._effective_available_agents(dict(state)) if str(item).strip()]
        candidate_agents = self._router_candidate_agents(state)
        selected_intent = state.get("selected_intent", {}) if isinstance(state.get("selected_intent"), dict) else {}
        review_corrected_values = state.get("review_corrected_values", {})
        corrected_keys = []
        if isinstance(review_corrected_values, dict):
            corrected_keys = sorted(str(key).strip() for key in review_corrected_values.keys() if str(key).strip())[:8]

        plan_summary = self._plan_step_summary(state)
        step_rows: list[dict[str, Any]] = []
        steps = plan_summary.get("plan_steps", [])
        index = int(plan_summary.get("plan_step_index", 0) or 0)
        if isinstance(steps, list):
            for step in steps[index:index + 3]:
                if not isinstance(step, dict):
                    continue
                step_rows.append(
                    {
                        "id": str(step.get("id") or "").strip(),
                        "agent": str(step.get("agent") or "").strip(),
                        "title": self._truncate(str(step.get("title") or "").strip(), 120),
                        "status": str(step.get("status") or "").strip(),
                    }
                )

        a2a_state = state.get("a2a", {})
        a2a_messages = a2a_state.get("messages", []) if isinstance(a2a_state, dict) else []
        multi_model_plan = state.get("multi_model_plan", {}) if isinstance(state.get("multi_model_plan"), dict) else {}

        toon = {
            "toon_version": 1,
            "stage": "route",
            "objective": self._truncate(str(current_objective or ""), 640),
            "user_query": self._truncate(str(state.get("user_query", "") or ""), 480),
            "workflow_gate": {
                "workflow_type": str(state.get("workflow_type", "") or "").strip(),
                "execution_mode": str(state.get("execution_mode", "") or "").strip(),
                "planner_policy_mode": str(state.get("planner_policy_mode", "") or "").strip(),
                "reviewer_policy_mode": str(state.get("reviewer_policy_mode", "") or "").strip(),
                "plan_ready": bool(state.get("plan_ready", False)),
                "plan_waiting_for_approval": bool(state.get("plan_waiting_for_approval", False)),
                "approval_scope": str(state.get("approval_pending_scope", "") or "").strip(),
                "awaiting_user_input": self._awaiting_user_input(state),
            },
            "capability_gate": {
                "web_search_enabled": bool(state.get("research_web_search_enabled", True)),
                "kb_enabled": bool(state.get("research_kb_enabled", False)),
                "local_paths_present": bool(state.get("local_drive_paths")),
                "image_inputs_present": any(
                    Path(str(item or "")).suffix.lower() in {".png", ".jpg", ".jpeg", ".bmp", ".gif", ".webp", ".tif", ".tiff"}
                    for item in list(state.get("local_drive_paths") or [])
                ),
                "multi_model_enabled": bool(state.get("multi_model_enabled", False)),
            },
            "selected_intent": {
                "intent_id": str(selected_intent.get("intent_id", "") or "").strip(),
                "intent_type": str(selected_intent.get("intent_type", "") or "").strip(),
                "label": str(selected_intent.get("label", "") or "").strip(),
                "execution_mode": str(selected_intent.get("execution_mode", "") or "").strip(),
                "requires_planner": bool(selected_intent.get("requires_planner", False)),
                "risk_level": str(selected_intent.get("risk_level", "") or "").strip(),
                "reasons": list(selected_intent.get("reasons", []) or [])[:4],
            },
            "plan_state": {
                "summary": self._truncate(str(state.get("plan", "") or ""), 360),
                "step_index": index,
                "step_total": int(plan_summary.get("plan_step_total", 0) or 0),
                "focus_steps": step_rows,
            },
            "review_state": {
                "decision": str(state.get("review_decision", "") or "").strip(),
                "reason": self._truncate(str(state.get("review_reason", "") or ""), 220),
                "target_agent": str(state.get("review_target_agent", "") or "").strip(),
                "corrected_keys": corrected_keys,
            },
            "multi_model": {
                "enabled": bool(state.get("multi_model_enabled", False)),
                "workflow_id": str(multi_model_plan.get("workflow_id", "") or "").strip(),
                "strategy": str(multi_model_plan.get("strategy", "") or "").strip(),
                "summary": self._truncate(str(multi_model_plan.get("summary", "") or ""), 240),
            },
            "available_agent_names": available_agent_names,
            "candidate_agents": candidate_agents,
            "blocked_agent_names": [str(item).strip() for item in list(state.get("_policy_blocked_agents") or []) if str(item).strip()][:12],
            "setup_gaps": self._router_setup_gap_hints(state),
            "setup_actions": self._router_setup_action_hints(state),
            "context_hints": {
                "setup_summary": self._router_text_hint(str(state.get("setup_summary", "") or ""), 360),
                "file_memory_summary": self._router_text_hint(str(state.get("file_memory_context", "") or ""), 520),
                "agent_history": self._router_text_hint(self._history_as_text(dict(state)), 720),
                "chat_summary": self._router_text_hint(self._session_history_as_text(dict(state)), 960),
                "a2a_recent": self._router_text_hint(self._recent_a2a_messages(dict(state)), 520),
            },
            "artifacts": {
                "deep_research_confirmed": bool(state.get("deep_research_confirmed", False)),
                "deep_research_result_kind": str(
                    ((state.get("deep_research_result_card") or {}) if isinstance(state.get("deep_research_result_card"), dict) else {}).get("kind", "")
                    or ""
                ).strip(),
                "run_output_dir": self._truncate(str(state.get("run_output_dir", "") or ""), 180),
                "session_id": str(state.get("session_id", "") or "").strip(),
            },
            "counts": {
                "available_agents": len(available_agent_names),
                "blocked_agents": len(list(state.get("_policy_blocked_agents") or [])),
                "setup_actions": len(list(state.get("setup_actions") or [])),
                "setup_gaps": len(list((state.get("disabled_agents") or {}).keys())) if isinstance(state.get("disabled_agents"), dict) else 0,
                "a2a_messages": len(a2a_messages) if isinstance(a2a_messages, list) else 0,
                "agent_history": len(list(state.get("agent_history") or [])),
                "session_turns": len(list(state.get("session_history") or [])),
            },
        }

        budget_tokens = self._router_token_budget(state)
        compacted = False
        dropped_sections: list[str] = []

        def estimated_tokens() -> int:
            return self._estimate_token_count(toon)

        def _drop_context_hint(key: str, label: str, truncate_to: int = 0) -> bool:
            hints = toon.get("context_hints")
            if not isinstance(hints, dict):
                return False
            value = str(hints.get(key) or "").strip()
            if not value:
                return False
            if truncate_to > 0 and len(value) > truncate_to:
                hints[key] = self._truncate(value, truncate_to)
            else:
                hints.pop(key, None)
            dropped_sections.append(label)
            return True

        def _shrink_candidate_descriptions(limit_desc: int) -> bool:
            rows = toon.get("candidate_agents")
            if not isinstance(rows, list) or not rows:
                return False
            changed = False
            for row in rows:
                if not isinstance(row, dict):
                    continue
                desc = str(row.get("description") or "").strip()
                if not desc:
                    continue
                shortened = self._truncate(desc, limit_desc)
                if shortened != desc:
                    row["description"] = shortened
                    changed = True
            if changed:
                dropped_sections.append("candidate_agent_descriptions")
            return changed

        def _drop_candidate_descriptions() -> bool:
            rows = toon.get("candidate_agents")
            if not isinstance(rows, list) or not rows:
                return False
            changed = False
            for row in rows:
                if isinstance(row, dict) and row.pop("description", None) is not None:
                    changed = True
            if changed:
                dropped_sections.append("candidate_agent_descriptions_removed")
            return changed

        def _limit_candidate_agents(max_items: int) -> bool:
            rows = toon.get("candidate_agents")
            if not isinstance(rows, list) or len(rows) <= max_items:
                return False
            toon["candidate_agents"] = rows[:max_items]
            dropped_sections.append(f"candidate_agents_top_{max_items}")
            return True

        def _limit_focus_steps(max_items: int) -> bool:
            plan_state = toon.get("plan_state")
            if not isinstance(plan_state, dict):
                return False
            rows = plan_state.get("focus_steps")
            if not isinstance(rows, list) or len(rows) <= max_items:
                return False
            plan_state["focus_steps"] = rows[:max_items]
            dropped_sections.append(f"focus_steps_top_{max_items}")
            return True

        reducers = [
            lambda: _drop_context_hint("file_memory_summary", "file_memory_summary", truncate_to=240),
            lambda: _drop_context_hint("a2a_recent", "a2a_recent"),
            lambda: _drop_context_hint("chat_summary", "chat_summary_trimmed", truncate_to=420),
            lambda: _drop_context_hint("agent_history", "agent_history_trimmed", truncate_to=320),
            lambda: _drop_context_hint("setup_summary", "setup_summary"),
            lambda: _shrink_candidate_descriptions(96),
            _drop_candidate_descriptions,
            lambda: _limit_candidate_agents(5),
            lambda: _limit_focus_steps(2),
        ]

        for reducer in reducers:
            if estimated_tokens() <= budget_tokens:
                break
            if reducer():
                compacted = True

        toon["budget_gate"] = {
            "token_budget": budget_tokens,
            "estimated_tokens": estimated_tokens(),
            "compacted": compacted,
            "dropped_sections": dropped_sections,
        }
        return toon

    def _execution_surface_note(self, state: Mapping[str, Any]) -> str:
        raw = state.get("used_execution_surfaces") or []
        if not isinstance(raw, list):
            return ""
        labels: list[str] = []
        seen: set[str] = set()
        for item in raw:
            if not isinstance(item, dict):
                continue
            label = str(item.get("label") or "").strip()
            if not label:
                continue
            if label in seen:
                continue
            seen.add(label)
            labels.append(label)
        if not labels:
            return ""
        return "used: " + ", ".join(labels[:4])

    def _with_execution_surface_note(self, text: str, state: Mapping[str, Any]) -> str:
        base = str(text or "").rstrip()
        note = self._execution_surface_note(state)
        if not note or note in base:
            return base
        return f"{base}\n\n{note}" if base else note

    def _awaiting_user_input(self, state: Mapping[str, Any]) -> bool:
        return state_awaiting_user_input(state)

    def _run_direct_tool_loop(self, state: Mapping[str, Any]) -> dict[str, Any]:
        return run_direct_tool_loop(state)

    def _dispatch_workflow_execution_policies(
        self,
        state: dict,
        *,
        current_objective: str,
        in_task_phase: bool,
    ) -> dict[str, Any] | None:
        return dispatch_workflow_execution_policies(
            self,
            state,
            current_objective=current_objective,
            in_task_phase=in_task_phase,
        )

    def _interpret_user_input_response(self, text: str) -> dict[str, str]:
        raw = str(text or "").strip()
        lowered = raw.lower()
        if not raw:
            return {"action": "unclear", "feedback": ""}

        cancel_exact_markers = {
            "cancel",
            "cancel this",
            "stop",
            "stop this",
            "abort",
            "abort this",
            "reject",
            "reject this",
            "rejected",
            "decline",
            "declined",
            "never mind",
            "nevermind",
        }
        cancel_phrase_markers = (
            "cancel the run",
            "stop the run",
            "abort the run",
            "reject this",
            "reject it",
            "dont create",
            "don't create",
            "do not create",
            "dont build",
            "don't build",
            "do not build",
            "dont implement",
            "don't implement",
            "do not implement",
            "no need to create",
            "no existing files need to be changed",
        )
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
            "dont",
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
        quick_summary_markers = (
            "quick summary",
            "summary only",
            "brief summary",
            "just summarize",
            "quick answer",
        )
        cleaned = lowered.strip(" \n\t.!?")
        if cleaned in cancel_exact_markers or any(marker in lowered for marker in cancel_phrase_markers):
            return {"action": "cancel", "feedback": raw}
        if any(marker in lowered for marker in quick_summary_markers):
            return {"action": "quick_summary", "feedback": raw}
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
            "drive-informed-long-document": "Draft the deep research report from the ingested drive evidence.",
            "planning": "Build the execution plan for this request.",
            "step-review": "Review the latest agent output and decide whether it should continue.",
            "correction": "Revise the previous step based on reviewer feedback.",
            "planned-step": f"Execute the next planned step with {agent_name or 'the assigned agent'}.",
            "run-generated-agent": "Run the generated agent task.",
            "project-audit-dispatch": "Run the structured codebase audit workflow.",
            "superrag-dispatch": "Build or query the superRAG knowledge session.",
            "deep-research-dispatch": "Run the deep research workflow and collect cited findings.",
            "long-document-dispatch": "Generate the deep research report section by section.",
            "master-coding-delegation": f"Continue the delegated coding workflow with {agent_name or 'the assigned agent'}.",
            "project-blueprint": "Designing the complete technical architecture for the project.",
        }
        if intent in intent_map:
            return intent_map[intent]
        agent_map = {
            "channel_gateway_agent": "Normalizing the incoming request payload.",
            "session_router_agent": "Resolving the session context.",
            "local_drive_agent": "Scanning drive files and extracting relevant evidence.",
            "long_document_agent": "Generating deep research report sections and merging the draft.",
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
            approval_summary = str((normalize_approval_request(state.get("approval_request", {})) or {}).get("summary", "") or "").strip()
            if approval_summary:
                return self._truncate(approval_summary, 240)
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
        summarized: list[dict] = []
        for step in steps:
            if not isinstance(step, dict):
                continue
            step_id = str(step.get("id") or "").strip()
            title = str(step.get("title") or step.get("task") or step_id or "").strip()
            agent = str(step.get("agent") or "").strip()
            if not (step_id or title or agent):
                continue
            summarized.append({
                "id": step_id,
                "title": title,
                "agent": agent,
                "status": str(step.get("status") or "pending"),
                "started_at": step.get("started_at"),
                "completed_at": step.get("completed_at"),
                "result_summary": step.get("result_summary"),
                "error": step.get("error"),
            })
        total = len(summarized)
        return {
            "plan_steps": summarized,
            "plan_step_index": max(0, index),
            "plan_step_total": total,
        }

    def _is_project_build_request(self, state: dict) -> bool:
        if bool(state.get("project_build_mode", False)):
            return True
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
        if self._is_deep_research_workflow(state):
            return False
        if self._is_local_command_request(state):
            return False
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

    def _is_deep_research_workflow(self, state: dict) -> bool:
        workflow_type = str(state.get("workflow_type", "") or "").strip().lower()
        if is_deep_research_workflow_type(workflow_type):
            return True
        pending_scope = str(state.get("approval_pending_scope", "") or "").strip().lower()
        pending_kind = str(state.get("pending_user_input_kind", "") or "").strip().lower()
        if pending_scope in {"deep_research_confirmation", "long_document_plan"}:
            return True
        if pending_kind in {"deep_research_confirmation", "subplan_approval"}:
            return True
        if bool(state.get("deep_research_mode", False)) or bool(state.get("long_document_mode", False)):
            return True
        if state.get("deep_research_analysis") or state.get("long_document_outline"):
            return True
        if self._is_long_document_request(state):
            return True
        return self._is_deep_research_request(state)

    def _infer_workflow_type(self, state: Mapping[str, Any]) -> str:
        explicit = str(state.get("workflow_type", "") or "").strip().lower()
        if explicit and explicit not in {"general"}:
            return explicit
        if bool(state.get("deep_research_mode", False)) or self._is_deep_research_request(dict(state)):
            return "deep_research"
        if bool(state.get("long_document_mode", False)) or self._is_long_document_request(dict(state)):
            return "long_document"
        if bool(state.get("project_build_mode", False)) or self._is_project_build_request(dict(state)):
            return "project_build"
        if self._is_project_workbench_request(dict(state)):
            return "project_workbench"
        if self._is_project_audit_request(dict(state)):
            return "project_audit"
        if self._is_local_command_request(dict(state)):
            return "local_command"
        if self._is_github_request(dict(state)):
            return "github"
        return explicit or "general"

    def _ensure_workflow_type(self, state: RuntimeState) -> str:
        workflow_type = self._infer_workflow_type(state)
        if workflow_type:
            state["workflow_type"] = workflow_type
        return workflow_type

    def _infer_multi_model_workflow_id(self, state: Mapping[str, Any]) -> str:
        workflow_type = str(state.get("workflow_type", "") or "").strip().lower()
        if workflow_type in {"deep_research", "long_document"}:
            return "deep_research_report"
        if bool(state.get("deep_research_mode", False)) or bool(state.get("long_document_mode", False)):
            return "deep_research_report"
        local_paths = list(state.get("local_drive_paths") or [])
        image_exts = {".png", ".jpg", ".jpeg", ".bmp", ".gif", ".webp", ".tif", ".tiff"}
        if any(Path(str(item or "")).suffix.lower() in image_exts for item in local_paths):
            return "ocr_ingestion"
        if bool(local_paths) or bool(state.get("local_drive_files")) or bool(state.get("local_drive_document_summaries")):
            return "document_qa"
        return ""

    def _prime_multi_model_plan(self, state: RuntimeState) -> None:
        enabled = _truthy(state.get("multi_model_enabled"), False)
        if not enabled:
            state["multi_model_plan"] = {}
            state["multi_model_active_workflow"] = ""
            return
        try:
            from kendr.llm_router import all_provider_statuses

            statuses = all_provider_statuses()
            recommendations = build_workflow_recommendations(statuses, multi_model=True)
        except Exception as exc:
            state["multi_model_plan"] = {
                "error": str(exc),
                "enabled": True,
            }
            return
        state["multi_model_recommendations"] = recommendations
        workflow_id = self._infer_multi_model_workflow_id(state)
        state["multi_model_active_workflow"] = workflow_id
        strategy = str(state.get("multi_model_strategy", "best") or "best").strip().lower()
        strategy = "cheapest" if strategy == "cheapest" else "best"
        workflows = recommendations.get("workflows") if isinstance(recommendations.get("workflows"), list) else []
        workflow = next((item for item in workflows if isinstance(item, dict) and item.get("id") == workflow_id), None)
        if not isinstance(workflow, dict):
            state["multi_model_plan"] = {
                "enabled": True,
                "workflow_id": workflow_id,
                "strategy": strategy,
                "available": False,
                "reason": "no matching workflow template",
            }
            return
        combo = workflow.get(strategy) if isinstance(workflow.get(strategy), dict) else {}
        stage_models: dict[str, dict[str, Any]] = {}
        for stage in combo.get("stages", []) if isinstance(combo.get("stages"), list) else []:
            if not isinstance(stage, dict):
                continue
            stage_name = str(stage.get("stage") or "").strip()
            provider = str(stage.get("provider") or "").strip().lower()
            model = str(stage.get("model") or "").strip()
            if stage_name and provider and model:
                stage_models[stage_name] = {
                    "provider": provider,
                    "model": model,
                    "reason": str(stage.get("reason") or "").strip(),
                    "cost_band": str(stage.get("cost_band") or "").strip(),
                    "source": "recommended",
                }
        stage_option_lookup: dict[str, dict[tuple[str, str], dict[str, Any]]] = {}
        for stage_option in workflow.get("stage_options", []) if isinstance(workflow.get("stage_options"), list) else []:
            if not isinstance(stage_option, dict):
                continue
            stage_name = str(stage_option.get("stage") or "").strip()
            if not stage_name:
                continue
            option_rows: dict[tuple[str, str], dict[str, Any]] = {}
            for candidate in stage_option.get("candidates", []) if isinstance(stage_option.get("candidates"), list) else []:
                if not isinstance(candidate, dict):
                    continue
                provider = str(candidate.get("provider") or "").strip().lower()
                model = str(candidate.get("model") or "").strip()
                if provider and model:
                    option_rows[(provider, model)] = candidate
            if option_rows:
                stage_option_lookup[stage_name] = option_rows
        manual_stage_overrides = state.get("multi_model_stage_overrides", {})
        applied_stage_overrides: dict[str, dict[str, Any]] = {}
        if isinstance(manual_stage_overrides, dict):
            for raw_stage_name, raw_override in manual_stage_overrides.items():
                stage_name = str(raw_stage_name or "").strip()
                if not stage_name:
                    continue
                provider = ""
                model = ""
                if isinstance(raw_override, dict):
                    provider = str(raw_override.get("provider") or "").strip().lower()
                    model = str(raw_override.get("model") or "").strip()
                elif isinstance(raw_override, str):
                    provider_name, _, model_name = str(raw_override).partition("/")
                    provider = provider_name.strip().lower()
                    model = model_name.strip()
                if not provider or not model:
                    continue
                candidate = (stage_option_lookup.get(stage_name) or {}).get((provider, model))
                if not isinstance(candidate, dict):
                    continue
                stage_models[stage_name] = {
                    "provider": provider,
                    "model": model,
                    "reason": f"Manual selection. {str(candidate.get('reason') or '').strip()}".strip(),
                    "cost_band": str(candidate.get("cost_band") or "").strip(),
                    "source": "manual",
                }
                applied_stage_overrides[stage_name] = {
                    "provider": provider,
                    "model": model,
                }
        summary_parts: list[str] = []
        for stage_name in workflow.get("stages", []) if isinstance(workflow.get("stages"), list) else []:
            stage_key = str(stage_name or "").strip()
            selected = stage_models.get(stage_key)
            if not isinstance(selected, dict):
                continue
            provider = str(selected.get("provider") or "").strip()
            model = str(selected.get("model") or "").strip()
            if not provider or not model:
                continue
            stage_label = stage_key
            for stage_row in combo.get("stages", []) if isinstance(combo.get("stages"), list) else []:
                if isinstance(stage_row, dict) and str(stage_row.get("stage") or "").strip() == stage_key:
                    stage_label = str(stage_row.get("label") or stage_key)
                    break
            summary_parts.append(f"{stage_label}: {provider}/{model}")
            if len(summary_parts) >= 3:
                break
        state["multi_model_plan"] = {
            "enabled": True,
            "workflow_id": workflow_id,
            "strategy": strategy,
            "available": bool(combo.get("available", False)),
            "mode_used": str(combo.get("mode_used") or "").strip(),
            "summary": "; ".join(summary_parts) if summary_parts else str(combo.get("summary") or "").strip(),
            "stage_models": stage_models,
            "manual_stage_overrides": applied_stage_overrides,
        }
        # Only seed the research backend automatically when the user explicitly opted in to
        # multi-model and did not already pin a research backend for the run.
        if (
            workflow_id == "deep_research_report"
            and not str(state.get("research_model") or "").strip()
            and not str(state.get("research_provider") or "").strip()
        ):
            evidence = stage_models.get("evidence") or {}
            provider = str(evidence.get("provider") or "").strip().lower()
            model = str(evidence.get("model") or "").strip()
            if provider and model:
                state["research_provider"] = provider
                state["research_model"] = model
                state["research_model_source"] = (
                    "multi_model_manual_override"
                    if str(evidence.get("source") or "").strip().lower() == "manual"
                    else "multi_model_plan"
                )

    def _multi_model_stage_for_agent(self, agent_name: str, state: Mapping[str, Any]) -> str:
        name = str(agent_name or "").strip()
        if name in {"orchestrator_agent", "planner_agent"}:
            return "router"
        if name in {"ocr_agent", "image_agent"}:
            return "ocr"
        if name in {"reviewer_agent", "citation_agent", "claim_evidence_mapping_agent"}:
            return "verify"
        if name in {"document_ingestion_agent", "local_drive_agent"}:
            return "extract"
        if name in {"report_agent", "long_document_agent"}:
            return "merge"
        if name in {
            "deep_research_agent",
            "research_pipeline_agent",
            "google_search_agent",
            "literature_search_agent",
            "patent_search_agent",
            "company_research_agent",
            "people_research_agent",
            "news_monitor_agent",
            "reddit_agent",
            "web_crawl_agent",
            "source_verification_agent",
        }:
            return "evidence"
        return ""

    def _multi_model_override_for_agent(self, state: RuntimeState, agent_name: str) -> dict[str, Any]:
        if not _truthy(state.get("multi_model_enabled"), False):
            return {}
        plan = state.get("multi_model_plan", {})
        if not isinstance(plan, dict) or not bool(plan.get("available", False)):
            return {}
        stage = self._multi_model_stage_for_agent(agent_name, state)
        if not stage:
            return {}
        stage_models = plan.get("stage_models") if isinstance(plan.get("stage_models"), dict) else {}
        selected = stage_models.get(stage) if isinstance(stage_models.get(stage), dict) else {}
        provider = str(selected.get("provider") or "").strip().lower()
        model = str(selected.get("model") or "").strip()
        if not provider or not model:
            return {}
        if agent_name in {"ocr_agent", "image_agent"} and provider not in {
            "openai",
            "xai",
            "minimax",
            "qwen",
            "glm",
            "ollama",
            "openrouter",
            "custom",
        }:
            return {}
        return {
            "stage": stage,
            "provider": provider,
            "model": model,
            "reason": str(selected.get("reason") or "").strip(),
        }

    def _prime_deep_research_plan(self, state: RuntimeState, *, record_trace: bool = True) -> None:
        if not self._is_deep_research_workflow(dict(state)):
            return
        objective = str(state.get("current_objective") or state.get("user_query") or "").strip()
        if not objective:
            return
        max_files = max(20, int(state.get("local_drive_max_files", 200) or 200))
        local_paths_present = bool(
            state.get("local_drive_paths")
            or state.get("local_drive_files")
            or state.get("local_drive_document_summaries")
        )
        intent = state.get("deep_research_intent", {})
        if not isinstance(intent, dict) or not intent:
            intent = discover_research_intent(objective, state)
            state["deep_research_intent"] = intent
        strategy = state.get("deep_research_source_strategy", {})
        if not isinstance(strategy, dict) or not strategy:
            strategy = build_source_strategy(
                intent,
                max_files=max_files,
                allow_web_search=bool(state.get("research_web_search_enabled", True)),
                local_paths_present=local_paths_present,
            )
            state["deep_research_source_strategy"] = strategy
        state["deep_research_execution_plan"] = {
            "objective": objective,
            "summary": " ".join(
                part for part in [
                    str(intent.get("summary", "")).strip(),
                    str(strategy.get("summary", "")).strip(),
                ] if part
            ).strip(),
            "intent": intent,
            "source_strategy": strategy,
            "banned_actions": list(intent.get("banned_actions", []) or []),
            "max_files": max_files,
            "local_paths_present": local_paths_present,
            "phases": [
                {"id": "intent", "title": "Discover research intent"},
                {"id": "source_strategy", "title": "Plan source strategy"},
                {"id": "evidence", "title": "Collect prioritized evidence"},
                {"id": "draft", "title": "Draft grounded report"},
                {"id": "exports", "title": "Export report artifacts"},
            ],
        }
        if not record_trace or bool(state.get("_deep_research_bootstrap_trace_written", False)):
            return
        self._record_execution_trace(
            state,
            kind="intent",
            actor="runtime",
            status="completed",
            title="Research intent discovered",
            detail=str(intent.get("summary", "")).strip(),
            metadata={"phase": "intent", "intent": intent},
        )
        self._record_execution_trace(
            state,
            kind="source_strategy",
            actor="runtime",
            status="completed",
            title="Source strategy planned",
            detail=str(strategy.get("summary", "")).strip(),
            metadata={"phase": "source_strategy", "strategy": strategy},
        )
        state["_deep_research_bootstrap_trace_written"] = True

    _PROJECT_WORKBENCH_RE = re.compile(
        r"(?:"  # explicit codebase inspection / modification requests from the project workbench
        r"\breview\b|\binspect\b|\bdebug\b|\btrace\b|\bexplain\b|\bsummarize\b|\bsummarise\b"
        r"|\banaly[sz]e\b|\bfind\b|\bsearch\b|\bgrep\b|\bscan\b|\bfix\b|\bimplement\b"
        r"|\brefactor\b|\bedit\b|\bchange\b|\bupdate\b|\bcompare\b|\bwhy\b|\bhow\b"
        r"|\bwhat\s+does\b|\bwhere\s+is\b|\bfailing\b|\bbug\b|\bfeature\b"
        r")",
        re.IGNORECASE,
    )

    def _project_channel_name(self, state: dict) -> str:
        for value in (
            state.get("incoming_channel", ""),
            ((state.get("gateway_message") or {}) if isinstance(state.get("gateway_message"), dict) else {}).get("channel", ""),
            ((state.get("channel_session") or {}) if isinstance(state.get("channel_session"), dict) else {}).get("channel", ""),
        ):
            channel = str(value or "").strip().lower()
            if channel:
                return channel
        return ""

    def _is_project_workbench_request(self, state: dict) -> bool:
        channel = self._project_channel_name(state)
        if channel not in {"project_ui", "projectui", "project"}:
            return False

        project_root = str(state.get("project_root", "") or "").strip()
        working_directory = str(state.get("working_directory", "") or "").strip()
        if not project_root and not working_directory:
            return False

        if self._is_project_build_request(state):
            return False
        if self._is_github_request(state):
            return False
        if self._is_local_command_request(state):
            return False
        if self._is_research_request(state):
            return False
        if self._is_communication_summary_request(state):
            return False
        if self._is_document_generation_request(state):
            return False
        if self._is_superrag_request(state):
            return False
        if self._is_deep_research_workflow(state):
            return False

        text = " ".join(
            [
                str(state.get("user_query", "") or ""),
                str(state.get("current_objective", "") or ""),
            ]
        ).strip()
        if len(text.split()) < 3:
            return False
        return bool(self._PROJECT_WORKBENCH_RE.search(text))

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

    def _session_history_as_text(self, state: dict) -> str:
        history = state.get("session_history", [])
        summary_text = str(state.get("session_history_summary", "") or "").strip()
        lines: list[str] = []
        if isinstance(history, list):
            for item in history[-8:]:
                if not isinstance(item, dict):
                    continue
                role = str(item.get("role", "") or "").strip().lower()
                if role not in {"user", "assistant"}:
                    continue
                content = self._truncate(str(item.get("content", "") or ""), 280)
                if not content:
                    continue
                lines.append(f"- {role}: {content}")
        parts: list[str] = []
        if summary_text:
            parts.append("Persisted summary.md context:\n" + self._truncate(summary_text, 3200))
        if lines:
            parts.append("Recent raw chat turns:\n" + "\n".join(lines))
        return "\n\n".join(parts) if parts else "No prior chat history provided for this turn."

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

    def _recent_execution_trace(self, state: dict, limit: int = 8) -> list[dict]:
        events = state.get("execution_trace", [])
        if not isinstance(events, list) or not events:
            return []
        return [item for item in events[-limit:] if isinstance(item, dict)]

    def _record_execution_trace(
        self,
        state: dict,
        *,
        kind: str,
        actor: str,
        status: str,
        title: str,
        detail: str = "",
        command: str = "",
        cwd: str = "",
        started_at: str = "",
        completed_at: str = "",
        duration_ms: int | None = None,
        exit_code: int | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        active_agent = actor if kind == "agent" else str(state.get("last_agent", "") or actor)
        event = append_execution_event(
            state,
            kind=kind,
            actor=actor,
            status=status,
            title=title,
            detail=detail,
            command=command,
            cwd=cwd,
            started_at=started_at,
            completed_at=completed_at,
            duration_ms=duration_ms,
            exit_code=exit_code,
            metadata=metadata,
            persist=True,
            active_agent=active_agent,
        )
        summary_line = render_execution_event_line(event)
        if summary_line:
            append_session_event(state, actor, f"trace_{status}", summary_line)
        return event

    def _recent_a2a_messages(self, state: dict) -> str:
        ensure_a2a_state(state, state.get("available_agent_cards") or self._agent_cards())
        messages = state["a2a"]["messages"]
        if not messages:
            return "No A2A messages yet."
        return "\n".join(
            f"- {item['sender']} -> {item['recipient']} [{item['role']}]: {self._truncate(item['content'], 240)}"
            for item in messages[-8:]
        )

    def _append_history(
        self,
        state: dict,
        agent_name: str,
        status: str,
        reason: str,
        output_text: str,
        start_timestamp: str | None = None,
    ) -> dict:
        completed_at = datetime.now(timezone.utc).isoformat()
        timestamp = start_timestamp or completed_at
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
        if run_id and not bool(state.get("_suppress_agent_execution_persistence", False)):
            insert_agent_execution(
                run_id,
                timestamp,
                agent_name,
                status,
                reason,
                self._truncate(output_text),
                completed_at=completed_at,
            )
        if not bool(state.get("_suppress_session_record", False)):
            self._write_session_record(state, status="running", active_agent=agent_name)
        return state

    def _session_payload(self, state: RuntimeState, *, status: str, active_agent: str = "", completed_at: str = "") -> dict:
        channel_session = state.get("channel_session", {}) if isinstance(state.get("channel_session"), dict) else {}
        plan_summary = self._plan_step_summary(state)
        run_output_dir = str(state.get("run_output_dir", "") or "").strip()
        log_paths = self._run_log_paths(run_output_dir)
        return {
            # Persist task sessions by run_id so long-running chat threads keep per-run
            # execution history instead of overwriting one row per channel session.
            "session_id": str(state.get("run_id", "") or state.get("session_id", "")),
            "run_id": state.get("run_id", ""),
            "workflow_id": state.get("workflow_id", state.get("run_id", "")),
            "attempt_id": state.get("attempt_id", state.get("run_id", "")),
            "workflow_type": state.get("workflow_type", ""),
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
                "workflow_id": state.get("workflow_id", state.get("run_id", "")),
                "attempt_id": state.get("attempt_id", state.get("run_id", "")),
                "workflow_type": state.get("workflow_type", ""),
                "last_agent": state.get("last_agent", ""),
                "last_status": state.get("last_agent_status", ""),
                "last_error": state.get("last_error", ""),
                "active_task": self._active_task_summary(state),
                "awaiting_user_input": state_awaiting_user_input(state),
                "pending_user_input_kind": state.get("pending_user_input_kind", ""),
                "approval_pending_scope": state.get("approval_pending_scope", ""),
                "pending_user_question": state.get("pending_user_question", ""),
                "approval_request": normalize_approval_request(state.get("approval_request", {})),
                "plan_approval_status": state.get("plan_approval_status", ""),
                "plan_steps": plan_summary.get("plan_steps", []),
                "plan_step_index": plan_summary.get("plan_step_index", 0),
                "plan_step_total": plan_summary.get("plan_step_total", 0),
                "recent_events": self._recent_event_summary(state),
                "execution_trace": self._recent_execution_trace(state),
                "thread_session_id": state.get("session_id", ""),
                "working_directory": str(state.get("working_directory", "") or ""),
                "run_output_dir": run_output_dir,
                "log_paths": log_paths,
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
        run_output_dir = str(state.get("run_output_dir", "") or "").strip()
        log_paths = self._run_log_paths(run_output_dir)
        previous = get_channel_session(session_key) or {}
        previous_state = previous.get("state", {}) if isinstance(previous, dict) else {}
        if not isinstance(previous_state, dict):
            previous_state = {}
        report_artifacts = self._report_artifact_candidates(state)
        has_report_context = bool(report_artifacts)
        persisted_report_run_id = str(previous_state.get("last_report_run_id", "") or "")
        persisted_report_workflow_id = str(previous_state.get("last_report_workflow_id", "") or "")
        persisted_report_run_output_dir = str(previous_state.get("last_report_run_output_dir", "") or "")
        persisted_result_card = (
            previous_state.get("deep_research_result_card", {})
            if isinstance(previous_state.get("deep_research_result_card", {}), dict)
            else {}
        )
        persisted_artifact_files = (
            previous_state.get("artifact_files", [])
            if isinstance(previous_state.get("artifact_files", []), list)
            else []
        )
        persisted_long_document_exports = (
            previous_state.get("long_document_exports", [])
            if isinstance(previous_state.get("long_document_exports", []), list)
            else []
        )
        persisted_compiled_paths = {
            key: str(previous_state.get(key, "") or "")
            for key in (
                "long_document_compiled_path",
                "long_document_compiled_html_path",
                "long_document_compiled_docx_path",
                "long_document_compiled_pdf_path",
            )
        }
        if has_report_context:
            persisted_report_run_id = str(state.get("run_id", "") or "").strip()
            persisted_report_workflow_id = str(state.get("workflow_id", state.get("run_id", "")) or "").strip()
            persisted_report_run_output_dir = run_output_dir or persisted_report_run_output_dir
            if isinstance(state.get("deep_research_result_card", {}), dict) and state.get("deep_research_result_card", {}):
                persisted_result_card = dict(state.get("deep_research_result_card", {}))
            if isinstance(state.get("artifact_files", []), list) and state.get("artifact_files", []):
                persisted_artifact_files = list(state.get("artifact_files", []))
            if isinstance(state.get("long_document_exports", []), list) and state.get("long_document_exports", []):
                persisted_long_document_exports = list(state.get("long_document_exports", []))
            for key in persisted_compiled_paths:
                value = str(state.get(key, "") or "").strip()
                if value:
                    persisted_compiled_paths[key] = value
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
                "last_workflow_id": state.get("workflow_id", state.get("run_id", "")),
                "last_attempt_id": state.get("attempt_id", state.get("run_id", "")),
                "workflow_type": state.get("workflow_type", ""),
                "last_objective": state.get("current_objective", state.get("user_query", "")),
                "run_output_dir": run_output_dir,
                "log_paths": log_paths,
                "last_plan": state.get("plan", ""),
                "last_plan_data": state.get("plan_data", {}),
                "last_plan_steps": state.get("plan_steps", []),
                "last_plan_step_index": int(state.get("plan_step_index", 0) or 0),
                "plan_waiting_for_approval": bool(state.get("plan_waiting_for_approval", False)),
                "plan_approval_status": state.get("plan_approval_status", ""),
                "plan_revision_feedback": state.get("plan_revision_feedback", ""),
                "plan_revision_count": int(state.get("plan_revision_count", 0) or 0),
                "plan_version": int(state.get("plan_version", 0) or 0),
                "last_report_run_id": persisted_report_run_id,
                "last_report_workflow_id": persisted_report_workflow_id,
                "last_report_run_output_dir": persisted_report_run_output_dir,
                "deep_research_result_card": persisted_result_card,
                "artifact_files": persisted_artifact_files,
                "long_document_exports": persisted_long_document_exports,
                "long_document_compiled_path": persisted_compiled_paths["long_document_compiled_path"],
                "long_document_compiled_html_path": persisted_compiled_paths["long_document_compiled_html_path"],
                "long_document_compiled_docx_path": persisted_compiled_paths["long_document_compiled_docx_path"],
                "long_document_compiled_pdf_path": persisted_compiled_paths["long_document_compiled_pdf_path"],
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
                "approval_request": normalize_approval_request(state.get("approval_request", {})),
                "long_document_plan_waiting_for_approval": bool(state.get("long_document_plan_waiting_for_approval", False)),
                "long_document_plan_status": state.get("long_document_plan_status", ""),
                "long_document_plan_feedback": state.get("long_document_plan_feedback", ""),
                "long_document_plan_revision_count": int(state.get("long_document_plan_revision_count", 0) or 0),
                "long_document_plan_markdown": state.get("long_document_plan_markdown", ""),
                "long_document_plan_data": state.get("long_document_plan_data", {}),
                "long_document_plan_version": int(state.get("long_document_plan_version", 0) or 0),
                "long_document_outline": state.get("long_document_outline", {}),
                "superrag_active_session_id": state.get("superrag_active_session_id", ""),
                "research_kb_enabled": bool(state.get("research_kb_enabled", False)),
                "research_kb_id": str(state.get("research_kb_id", "") or ""),
                "research_kb_top_k": int(state.get("research_kb_top_k", 8) or 8),
                "execution_mode": str(state.get("execution_mode", "adaptive") or "adaptive").strip().lower(),
                "adaptive_agent_selection": _truthy(state.get("adaptive_agent_selection"), True),
                "planner_policy_mode": str(state.get("planner_policy_mode", "adaptive") or "adaptive").strip().lower(),
                "reviewer_policy_mode": str(state.get("reviewer_policy_mode", "adaptive") or "adaptive").strip().lower(),
                "planner_score_threshold": int(state.get("planner_score_threshold", 4) or 4),
                "reviewer_score_threshold": int(state.get("reviewer_score_threshold", 5) or 5),
                "history": history,
            },
        }
        upsert_channel_session(session_key, session_payload)
        state["channel_session"] = session_payload

    def _run_log_paths(self, run_output_dir: str) -> dict[str, str]:
        base = str(run_output_dir or "").strip()
        if not base:
            return {}
        resolved = str(Path(base).expanduser().resolve())
        return {
            "run_output_dir": resolved,
            "execution_log": str(Path(resolved) / "execution.log"),
            "agent_work_notes": str(Path(resolved) / "agent_work_notes.txt"),
            "final_output": str(Path(resolved) / "final_output.txt"),
            "privileged_audit": str(Path(resolved) / "privileged_audit.log"),
            "run_manifest": str(Path(resolved) / "run_manifest.json"),
            "checkpoint": str(Path(resolved) / "checkpoint.json"),
            "resume_summary": str(Path(resolved) / "resume_summary.json"),
            "heartbeat": str(Path(resolved) / "heartbeat.json"),
        }

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
            workflow_id=str(state.get("workflow_id", state.get("run_id", ""))).strip(),
            attempt_id=str(state.get("attempt_id", state.get("run_id", ""))).strip(),
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
        policy_blocked = set(state.get("_policy_blocked_agents", []) or [])
        if agent_name == "finish" or (agent_name not in policy_blocked and self._is_agent_available(state, agent_name)):
            return agent_name, reason
        if self._is_deep_research_workflow(dict(state)) and agent_name in _DEEP_RESEARCH_OUTPUT_ONLY_BLOCKED_AGENTS:
            deep_reason = (
                f"{reason} Deep research is output-only, so {agent_name} is blocked. "
                "Continue with long_document_agent and produce research artifacts instead of code or project scaffolding."
            )
            if self._is_agent_available(state, "long_document_agent"):
                return "long_document_agent", deep_reason
            return "finish", deep_reason
        if agent_name in policy_blocked:
            reason = f"{reason} Requested agent {agent_name} is currently gated by the adaptive policy."
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
        if str(state.get("workflow_type", "") or "").strip().lower() == "deep_research":
            return True
        if bool(state.get("deep_research_mode", False)):
            return True
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

    def _is_report_file_lookup_request(self, state: Mapping[str, Any]) -> bool:
        text = " ".join(
            [
                str(state.get("user_query", "") or ""),
                str(state.get("current_objective", "") or ""),
            ]
        ).strip().lower()
        if not text:
            return False
        artifact_markers = (
            "report",
            "pdf",
            "docx",
            "doc",
            "word",
            "html",
            "markdown",
            "document",
            "file",
            "artifact",
            "output",
            "result",
        )
        if not any(marker in text for marker in artifact_markers):
            return False
        location_markers = (
            "where is",
            "where's",
            "locate",
            "path to",
            "saved",
            "stored",
            "located",
            "which folder",
            "what folder",
            "output folder",
            "output path",
            "report path",
            "file path",
            "open the folder",
            "show the folder",
        )
        if any(marker in text for marker in location_markers):
            return True
        return bool(
            re.search(
                r"\b(find|locate|fetch|retrieve|show|open)\b.*\b(report|pdf|docx|doc|word|html|markdown|document|file|artifact|output|result)\b",
                text,
            )
        )

    def _report_lookup_requested_extensions(self, text: str) -> set[str]:
        lowered = str(text or "").strip().lower()
        requested: set[str] = set()
        if re.search(r"\bpdf\b", lowered):
            requested.add("pdf")
        if re.search(r"\b(docx|doc|word)\b", lowered):
            requested.add("docx")
        if re.search(r"\bhtml\b", lowered):
            requested.add("html")
        if re.search(r"\b(md|markdown)\b", lowered):
            requested.add("md")
        return requested

    def _resolve_report_artifact_path_for_hint(self, state: Mapping[str, Any], path_value: Any) -> str:
        candidate = str(path_value or "").strip()
        if not candidate:
            return ""
        if os.path.isabs(candidate):
            return str(Path(candidate).expanduser())
        base_dir = str(state.get("artifact_lookup_run_output_dir") or state.get("run_output_dir") or "").strip()
        normalized = candidate.replace("\\", "/")
        if normalized.startswith("output/"):
            normalized = normalized[len("output/"):]
        if not base_dir:
            return normalized
        return str((Path(base_dir).expanduser() / normalized).resolve())

    def _report_artifact_candidates(self, state: Mapping[str, Any]) -> list[dict[str, str]]:
        candidates: list[dict[str, str]] = []
        seen: set[tuple[str, str]] = set()

        def _add(name: Any, path_value: Any, kind: str = "") -> None:
            resolved_path = self._resolve_report_artifact_path_for_hint(state, path_value)
            if not resolved_path:
                return
            safe_name = str(name or os.path.basename(resolved_path) or "").strip()
            if not safe_name:
                safe_name = os.path.basename(resolved_path)
            ext = Path(safe_name).suffix.lower().lstrip(".")
            key = (safe_name.lower(), resolved_path)
            if key in seen:
                return
            seen.add(key)
            candidates.append(
                {
                    "name": safe_name,
                    "path": resolved_path,
                    "ext": ext,
                    "kind": str(kind or "").strip(),
                }
            )

        result_card = state.get("deep_research_result_card", {})
        if isinstance(result_card, dict):
            for key in (
                "report_pdf_path",
                "pdf_path",
                "report_docx_path",
                "docx_path",
                "report_html_path",
                "html_path",
                "report_path",
            ):
                _add("", result_card.get(key), key)

        for key in (
            "long_document_compiled_pdf_path",
            "long_document_compiled_docx_path",
            "long_document_compiled_html_path",
            "long_document_compiled_path",
        ):
            _add("", state.get(key), key)

        artifact_files = state.get("artifact_files", [])
        if isinstance(artifact_files, list):
            for item in artifact_files:
                if not isinstance(item, dict):
                    continue
                _add(item.get("name"), item.get("path"), str(item.get("kind") or "").strip())

        return candidates

    def _is_document_generation_request(self, state: dict) -> bool:
        """Return True when the user wants a researched document/report produced as a file.

        Only fires on strong explicit document-generation signals combined with research intent,
        or on very specific document phrases. Never fires on simple chat or coding questions.
        """
        text = " ".join(
            [
                str(state.get("user_query", "") or ""),
                str(state.get("current_objective", "") or ""),
            ]
        ).lower()
        if not text.strip():
            return False

        if self._is_project_build_request(state) or self._is_github_request(state):
            return False

        strong_doc_markers = (
            "complete document",
            "full document",
            "write a document",
            "prepare a document",
            "create a document",
            "generate a document",
            "give me a document",
            "write me a document",
            "write a report",
            "full report",
            "prepare a report",
            "create a report",
            "give me a report",
            "write me a report",
            "write a guide",
            "write a handbook",
            "write a manual",
            "write a whitepaper",
            "white paper",
            "farmer guide",
            "farmer handbook",
            "farmer document",
            "share with farmers",
        )
        if any(m in text for m in strong_doc_markers):
            return True

        soft_doc_markers = (
            "detailed document",
            "detailed report",
            "detailed guide",
        )
        research_markers = (
            "research",
            "investigate",
            "study",
            "look into",
            "gather information",
            "collect information",
        )
        has_soft_doc = any(m in text for m in soft_doc_markers)
        has_research = any(m in text for m in research_markers)
        return has_soft_doc and has_research

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

    # ------------------------------------------------------------------
    # Research intent classification
    # ------------------------------------------------------------------

    _RESEARCH_INTENT_RE = re.compile(
        r"(?:"
        r"\bresearch\s+(about|on|into|the|for|around|regarding)\b"
        r"|\bdo\s+(some\s+)?(research|investigation)\b"
        r"|\binvestigate\b|\blook\s+into\b|\blook\s+up\b"
        r"|\bfind\s+(out|information|data|details|facts)\s+(about|on|regarding)\b"
        r"|\bstudy\s+(about|on|the|of)\b"
        r"|\btell\s+me\s+(about|what|how|why|where|when)\b"
        r"|\bwhat\s+(is|are|was|were|does|do)\b"
        r"|\bhow\s+(does|do|did|to|can|should)\b"
        r"|\bwhy\s+(does|do|did|is|are|was|were)\b"
        r"|\bexplain\b"
        r"|\bdescribe\b"
        r"|\bsummarize\b|\bsummarise\b"
        r"|\bgive\s+me\s+(a\s+)?(summary|overview|introduction|explanation|brief)\b"
        r"|\boverview\s+of\b|\bintroduction\s+to\b|\bhistory\s+of\b"
        r"|\bcompare\b|\bpros\s+and\s+cons\b"
        r"|\badvantages?\s+(of|and)\b|\bdisadvantages?\s+(of|and)\b"
        r"|\bstate\s+of\s+(the\s+)?art\b|\bbest\s+practices\s+(for|in|of)\b"
        r"|\brecent\s+(news|developments|updates|advances|progress|research)\b"
        r"|\binformation\s+(about|on|regarding)\b|\bfacts\s+(about|on|regarding)\b"
        r"|\banalysis\s+(of|on)\b|\banalyze\b|\banalyse\b"
        r"|\bcurrent\s+(state|status|landscape)\s+(of|in)\b"
        r")",
        re.IGNORECASE,
    )

    # Signals that strongly indicate coding / building / git / shell — NOT information lookup.
    _ANTI_RESEARCH_RE = re.compile(
        r"\b("
        r"write\s+(code|a\s+(function|class|script|program|module|test|component|page|route|handler|service))"
        r"|write\s+me\s+(a|an)\s+(function|class|script|program|module|test|app|api|server|bot)"
        r"|implement\s+(a|an|the)?\s*(function|class|endpoint|feature|algorithm|interface|api|auth)"
        r"|create\s+(a|an)\s+(function|class|app|application|project|system|api|server|bot|endpoint|route)"
        r"|build\s+(a|an)\s+(app|application|project|system|api|server|bot|pipeline|workflow)"
        r"|generate\s+(code|a\s+(function|class|test|schema|migration|api))"
        r"|fix\s+(the\s+)?(bug|error|issue|crash|test|exception|failure)"
        r"|debug\s+(this|the|my)|refactor\s+(this|the|my)"
        r"|clone\s+(repo|repository|this|the\s+repo)|push\s+(to|the\s+repo)"
        r"|merge\s+(the\s+)?PR|open\s+(a\s+)?(PR|pull\s+request)"
        r"|run\s+(this\s+)?(command|script|test|pipeline)|execute\s+(this|the)"
        r"|deploy\s+(to|the|this|my)\s*(app|server|cloud|production|env|environment)"
        r"|install\s+(package|dependency|dependencies|module|library)"
        r")\b",
        re.IGNORECASE,
    )

    def _is_research_request(self, state: dict) -> bool:
        """Return True when the query is a clear information/research request that should
        bypass the planner and route directly to a research agent.

        Deliberately conservative: only fires on strong positive research signals AND
        absence of strong coding/build/git signals.
        """
        text = " ".join([
            str(state.get("user_query", "") or ""),
            str(state.get("current_objective", "") or ""),
        ]).strip()
        if not text or len(text.split()) < 3:
            return False
        if self._is_project_build_request(state):
            return False
        if self._is_github_request(state):
            return False
        # Filesystem/terminal requests often look like "what is..." but should
        # stay in local command routing instead of web research.
        if self._is_local_command_request(state):
            return False
        if self._ANTI_RESEARCH_RE.search(text):
            return False
        return bool(self._RESEARCH_INTENT_RE.search(text))

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
        if any(marker in text for marker in markers):
            return True
        if self._is_report_file_lookup_request(state):
            return True

        software_presence_intent = bool(
            re.search(
                r"\b(check|verify|confirm|see|tell\s+me\s+if|is|whether|find\s+out\s+if|do\s+i\s+have)\b.*\b(installed|available|present|exists|on\s+my\s+laptop|on\s+my\s+computer|on\s+my\s+pc|on\s+this\s+machine|on\s+this\s+system)\b",
                text,
            )
            or re.search(
                r"\b(installed|available|present)\b.*\b(on\s+my\s+laptop|on\s+my\s+computer|on\s+my\s+pc|on\s+this\s+machine|on\s+this\s+system)\b",
                text,
            )
            or re.search(
                r"\bdo\s+i\s+have\b.*\b(on\s+my\s+laptop|on\s+my\s+computer|on\s+my\s+pc|in\s+my\s+laptop|in\s+my\s+computer|in\s+my\s+pc|on\s+this\s+machine|on\s+this\s+system)\b",
                text,
            )
        )
        local_machine_markers = (
            "my laptop",
            "my computer",
            "my pc",
            "this machine",
            "this system",
            "on my laptop",
            "on my computer",
            "on my pc",
            "in my laptop",
            "in my computer",
            "in my pc",
        )
        software_target_markers = (
            "vs code",
            "visual studio code",
            "vscode",
            "docker",
            "git",
            "node",
            "nodejs",
            "python",
            "java",
            "kubectl",
            "terraform",
        )
        if software_presence_intent and (
            any(marker in text for marker in local_machine_markers)
            or any(marker in text for marker in software_target_markers)
        ):
            return True
        if (
            re.search(r"\b(sync|refresh|update|scan)\b.*\b(software|tools?|installed)\b", text)
            and re.search(r"\b(inventory|cache|memory|list)\b", text)
        ):
            return True
        if (
            re.search(r"\b(sync|scan|index|refresh|track)\b", text)
            and re.search(r"\b(machine|computer|laptop|files?|filesystem|file\s+changes|recent\s+changes)\b", text)
        ):
            return True

        listing_intent = any(
            marker in text
            for marker in (
                "which folders",
                "which directories",
                "list folders",
                "list directories",
                "show folders",
                "show directories",
                "folder names",
                "directory names",
                "what folders are",
                "what files are",
                "contents of",
                "what is in my",
                "what's in my",
            )
        )
        filesystem_analysis_intent = any(
            marker in text
            for marker in (
                "largest file",
                "biggest file",
                "largest files",
                "biggest files",
                "which file is largest",
                "largest in the folder",
                "largest in folder",
                "largest file in",
                "biggest file in",
                "top largest files",
                "files by size",
                "sort files by size",
                "heaviest file",
            )
        )
        filesystem_target = any(
            marker in text
            for marker in (
                "drive",
                "folder",
                "directory",
                "directories",
                "filesystem",
                "file system",
                "/mnt/",
                "c:",
                "d:",
                "e:",
                "f:",
            )
        )
        return filesystem_target and (listing_intent or filesystem_analysis_intent)

    def _is_shell_plan_request(self, state: dict) -> bool:
        text = " ".join(
            [
                str(state.get("user_query", "") or ""),
                str(state.get("current_objective", "") or ""),
            ]
        ).lower()
        if not text.strip():
            return False
        if self._is_project_build_request(state):
            return False
        install_markers = ("install", "setup", "configure", "provision", "bootstrap")
        runtime_markers = ("run", "start", "stop", "restart", "pull", "up", "down")
        multi_step_markers = (
            "if not installed",
            "if missing",
            "then",
            "after that",
            "step by step",
            "and then",
            "series of tasks",
            "end to end",
        )
        infra_targets = (
            "docker",
            "nginx",
            "redis",
            "postgres",
            "mysql",
            "mongodb",
            "kubernetes",
            "kubectl",
            "terraform",
            "ollama",
        )
        has_install = any(marker in text for marker in install_markers)
        has_runtime = any(marker in text for marker in runtime_markers)
        has_target = any(marker in text for marker in infra_targets)
        has_multi_step_signal = any(marker in text for marker in multi_step_markers)
        return bool(has_target and ((has_install and has_runtime) or has_multi_step_signal))

    def _derive_local_command_hint(self, state: Mapping[str, Any]) -> dict[str, Any]:
        query = " ".join(
            [
                str(state.get("user_query", "") or ""),
                str(state.get("current_objective", "") or ""),
            ]
        ).strip()
        lowered = query.lower()
        if not lowered:
            return {}

        drive_match = re.search(r"\b([a-z])\s*:?\\?\s*drive\b", lowered) or re.search(r"\b([a-z]):\b", lowered)
        drive_letter = drive_match.group(1).lower() if drive_match else ""
        folder_match = re.search(
            r"\b(?:folder|directory)\s+['\"]?([a-z0-9._\-\s]+?)['\"]?(?:[?.!,]|$)",
            lowered,
        )
        folder_name = ""
        if folder_match:
            folder_name = " ".join(folder_match.group(1).split()).strip(" .")
        listing_request = any(
            marker in lowered
            for marker in (
                "which folders",
                "which directories",
                "list folders",
                "list directories",
                "show folders",
                "show directories",
                "folder names",
                "directory names",
                "what folders are",
                "what files are",
                "contents of",
                "what is in my",
                "what's in my",
            )
        )
        largest_file_request = any(
            marker in lowered
            for marker in (
                "largest file",
                "biggest file",
                "which file is largest",
                "largest files",
                "biggest files",
                "heaviest file",
            )
        )

        software_presence_intent = bool(
            re.search(
                r"\b(check|verify|confirm|see|tell\s+me\s+if|is|whether|find\s+out\s+if|do\s+i\s+have)\b.*\b(installed|available|present|exists)\b",
                lowered,
            )
            or re.search(
                r"\bdo\s+i\s+have\b.*\b(on\s+my\s+laptop|on\s+my\s+computer|on\s+my\s+pc|in\s+my\s+laptop|in\s+my\s+computer|in\s+my\s+pc|on\s+this\s+machine|on\s+this\s+system)\b",
                lowered,
            )
        )
        vscode_markers = (
            "vs code",
            "visual studio code",
            "vscode",
            "code editor",
        )
        vscode_check_request = software_presence_intent and any(marker in lowered for marker in vscode_markers)
        inventory_sync_request = bool(
            re.search(r"\b(sync|refresh|update|scan)\b.*\b(software|tools?|installed)\b", lowered)
            and re.search(r"\b(inventory|cache|memory|list)\b", lowered)
        )
        machine_sync_request = bool(
            re.search(r"\b(sync|scan|index|refresh|track)\b", lowered)
            and re.search(r"\b(machine|computer|laptop)\b", lowered)
        )
        file_index_request = bool(
            re.search(r"\b(index|scan|sync|track)\b.*\b(files?|filesystem|file\s+changes|recent\s+changes)\b", lowered)
        )

        if machine_sync_request or file_index_request or inventory_sync_request:
            sync_scope = "machine"
            if file_index_request and not inventory_sync_request:
                sync_scope = "files"
            if inventory_sync_request and not file_index_request:
                sync_scope = "software"
            return {
                "os_command": "__KENDR_SYNC_MACHINE__",
                "machine_sync_scope": sync_scope,
            }

        if vscode_check_request:
            if os.name == "nt":
                return {
                    "os_command": (
                        "$cmd = Get-Command code -ErrorAction SilentlyContinue; "
                        "if ($cmd) { Write-Output ('installed:' + $cmd.Source) } "
                        "elseif (Test-Path \"$env:LOCALAPPDATA\\Programs\\Microsoft VS Code\\Code.exe\") "
                        "{ Write-Output ('installed:' + \"$env:LOCALAPPDATA\\Programs\\Microsoft VS Code\\Code.exe\") } "
                        "elseif (Test-Path \"$env:ProgramFiles\\Microsoft VS Code\\Code.exe\") "
                        "{ Write-Output ('installed:' + \"$env:ProgramFiles\\Microsoft VS Code\\Code.exe\") } "
                        "else { Write-Output 'not installed' }"
                    ),
                    "shell": "powershell",
                    "target_os": "windows",
                }
            return {
                "os_command": (
                    "if command -v code >/dev/null 2>&1; then "
                    "echo \"installed:$(command -v code)\"; "
                    "elif [ -d \"/Applications/Visual Studio Code.app\" ] || [ -d \"$HOME/Applications/Visual Studio Code.app\" ]; then "
                    "echo \"installed:Visual Studio Code.app\"; "
                    "else echo \"not installed\"; fi"
                )
            }

        if inventory_sync_request:
            if os.name == "nt":
                return {
                    "os_command": (
                        "$tools = @('docker','git','python','node','code','kubectl','terraform'); "
                        "foreach ($tool in $tools) { "
                        "$cmd = Get-Command $tool -ErrorAction SilentlyContinue; "
                        "if ($cmd) { Write-Output ($tool + '|installed|' + $cmd.Source) } "
                        "else { Write-Output ($tool + '|missing|') } }"
                    ),
                    "shell": "powershell",
                    "target_os": "windows",
                }
            return {
                "os_command": (
                    "for app in docker git python3 node code kubectl terraform; do "
                    "if command -v \"$app\" >/dev/null 2>&1; then echo \"$app|installed|$(command -v $app)\"; "
                    "else echo \"$app|missing|\"; fi; done"
                )
            }

        if self._is_report_file_lookup_request(state):
            requested_exts = self._report_lookup_requested_extensions(lowered)
            artifacts = self._report_artifact_candidates(state)
            if requested_exts:
                artifacts = [item for item in artifacts if str(item.get("ext") or "").lower() in requested_exts]
            if artifacts:
                paths = [str(item.get("path") or "").strip() for item in artifacts if str(item.get("path") or "").strip()]
                output_dir = str(state.get("artifact_lookup_run_output_dir") or state.get("run_output_dir") or "").strip()
                if os.name == "nt":
                    quoted_paths = []
                    for path in paths[:8]:
                        quoted_paths.append("'" + path.replace("'", "''") + "'")
                    quoted = ", ".join(quoted_paths)
                    hint: dict[str, Any] = {
                        "os_command": f"@({quoted}) | ForEach-Object {{ Write-Output $_ }}",
                        "shell": "powershell",
                        "target_os": "windows",
                    }
                    if output_dir:
                        hint["os_working_directory"] = output_dir
                    if state.get("artifact_lookup_run_id"):
                        hint["artifact_lookup_run_id"] = str(state.get("artifact_lookup_run_id"))
                    return hint
                hint = {
                    "os_command": "printf '%s\\n' " + " ".join(shlex.quote(path) for path in paths[:8]),
                }
                if output_dir:
                    hint["os_working_directory"] = output_dir
                if state.get("artifact_lookup_run_id"):
                    hint["artifact_lookup_run_id"] = str(state.get("artifact_lookup_run_id"))
                return hint

            search_root = str(
                state.get("artifact_lookup_run_output_dir")
                or state.get("run_output_dir")
                or state.get("working_directory")
                or "."
            ).strip() or "."
            if requested_exts:
                patterns = [f"*.{ext}" for ext in sorted(requested_exts)]
            else:
                patterns = [
                    "*report*.pdf",
                    "*report*.docx",
                    "*report*.html",
                    "*report*.md",
                    "*deep_research*.pdf",
                    "*deep_research*.docx",
                    "*deep_research*.html",
                    "*deep_research*.md",
                ]
            if os.name == "nt":
                safe_search_root = search_root.replace("'", "''")
                quoted_patterns = []
                for pattern in patterns:
                    quoted_patterns.append("$_.Name -like '" + pattern.replace("'", "''") + "'")
                where_clause = " -or ".join(quoted_patterns) or "$true"
                return {
                    "os_command": (
                        f"Get-ChildItem -Path '{safe_search_root}' -File -Recurse -ErrorAction SilentlyContinue | "
                        f"Where-Object {{ {where_clause} }} | Select-Object -First 20 -ExpandProperty FullName"
                    ),
                    "shell": "powershell",
                    "target_os": "windows",
                    "os_working_directory": search_root,
                }
            search_clause = " -o ".join(f"-iname {shlex.quote(pattern)}" for pattern in patterns)
            return {
                "os_command": (
                    f"find {shlex.quote(search_root)} -type f \\( {search_clause} \\) 2>/dev/null | sort | head -n 20"
                ),
                "os_working_directory": search_root,
            }

        if largest_file_request:
            if os.name == "nt":
                base_path = "."
                if drive_letter and folder_name:
                    base_path = f"{drive_letter.upper()}:\\{folder_name}"
                elif drive_letter:
                    base_path = f"{drive_letter.upper()}:\\"
                elif folder_name:
                    base_path = folder_name
                return {
                    "os_command": (
                        f"Get-ChildItem -Path {base_path} -File -Recurse -ErrorAction SilentlyContinue | "
                        "Sort-Object Length -Descending | Select-Object -First 1 FullName,Length"
                    ),
                    "shell": "powershell",
                    "target_os": "windows",
                }

            base_path = "."
            if drive_letter and folder_name:
                base_path = f"/mnt/{drive_letter}/{folder_name}"
            elif drive_letter:
                base_path = f"/mnt/{drive_letter}"
            elif folder_name:
                base_path = folder_name
            quoted_path = shlex.quote(base_path)
            return {
                "os_command": (
                    f"find {quoted_path} -type f -printf '%s\\t%p\\n' 2>/dev/null | "
                    "sort -nr | head -n 1"
                )
            }

        if not listing_request:
            return {}

        if drive_letter:
            if os.name == "nt":
                return {
                    "os_command": f"Get-ChildItem -Name -Directory {drive_letter.upper()}:\\",
                    "shell": "powershell",
                    "target_os": "windows",
                }
            return {"os_command": f"ls -1 /mnt/{drive_letter}"}

        if "current directory" in lowered or "this directory" in lowered:
            return {"os_command": "ls -1 ."}

        return {}

    def _is_communication_summary_request(self, state: dict) -> bool:
        # Do not route capability/skills inventory prompts into communication
        # inbox aggregation workflows.
        if self._is_registry_discovery_request(state):
            return False

        text = " ".join(
            [
                str(state.get("user_query", "")),
                str(state.get("current_objective", "")),
            ]
        ).lower()
        if not text.strip():
            return False

        markers = (
            "communication digest",
            "communication summary",
            "summarize my communications",
            "summarize my messages",
            "summarize my emails",
            "what did i miss",
            "what have i missed",
            "morning briefing",
            "message digest",
            "inbox digest",
            "check my messages",
            "check my emails",
            "check my slack",
            "check my gmail",
            "check my whatsapp",
            "check my telegram",
            "fetch my messages",
            "my unread messages",
            "across all channels",
            "all communication channels",
        )
        return any(marker in text for marker in markers)

    # ------------------------------------------------------------------
    # Conversational shortcut — intent classification
    # ------------------------------------------------------------------

    _GREETING_RE = re.compile(
        r"^(hi(\s+there)?|hello(\s+there)?|hey(\s+there)?|howdy|hiya|sup|yo|greetings|salut|aloha"
        r"|good\s+(morning|afternoon|evening|night|day)"
        r"|how([\s']*are[\s']*you(\s+doing)?|[\s']*r[\s']*u)?[\s!?]*"
        r"|what['\s]*s[\s]*(up|good|new)[\s!?]*"
        r"|how['\s]*s[\s]*(it\s+going|everything|things)[\s!?]*)[\s!?.]*$",
        re.IGNORECASE,
    )
    _FAREWELL_RE = re.compile(
        r"^(bye|goodbye|good[\s-]?bye|see\s+you|see\s+ya|later|cya|ta[\s-]?ta"
        r"|take\s+care|have\s+a\s+(good|great|nice)\s+(day|one)|cheers|until\s+next\s+time)[\s!.]*$",
        re.IGNORECASE,
    )
    _THANKS_RE = re.compile(
        r"^(thank(s|\s+you)(\s+so\s+much|\s+a\s+lot|\s+very\s+much)?|thx|ty|thnx|np|no\s+problem"
        r"|you['\s]*re\s+welcome|no\s+worries|not\s+at\s+all|anytime)[\s!.]*$",
        re.IGNORECASE,
    )
    _ACK_RE = re.compile(
        r"^(ok|okay|k|alright|sure|yep|yup|yeah|yes|noted|got\s+it|understood|roger"
        r"|makes\s+sense|sounds\s+good|great|perfect|nice|cool|good|awesome"
        r"|i\s+see|i\s+understand|fair\s+enough)[\s!.]*$",
        re.IGNORECASE,
    )
    _CAPABILITY_RE = re.compile(
        r"(what\s+can\s+you\s+do|what\s+are\s+(you|your\s+capabilities)|what\s+do\s+you\s+do"
        r"|tell\s+me\s+about\s+yourself|who\s+are\s+you|what\s+is\s+kendr|what['\s]*s\s+kendr"
        r"|^help[\s!?.]*$|how\s+can\s+you\s+help|what\s+features|what\s+(else\s+)?can\s+you\s+help)",
        re.IGNORECASE,
    )
    _SKILLS_RE = re.compile(
        r"(what(\s+all)?\s+skills\s+do\s+you\s+have"
        r"|which\s+skills\s+do\s+you\s+have"
        r"|show(\s+me)?\s+(your|available)\s+skills"
        r"|list(\s+your|\s+available)?\s+skills"
        r"|what\s+agents\s+do\s+you\s+have"
        r"|which\s+agents\s+are\s+available)",
        re.IGNORECASE,
    )
    _REGISTRY_DISCOVERY_RE = re.compile(
        r"(what(\s+all)?\s+(skills|agents|capabilities|mcp(\s+servers)?|apis?)\s+do\s+you\s+have"
        r"|list(\s+your|\s+available)?\s+(skills|agents|capabilities|mcp(\s+servers)?|apis?)"
        r"|show(\s+me)?\s+(your|available)\s+(skills|agents|capabilities|mcp(\s+servers)?|apis?)"
        r"|which\s+(skills|agents|capabilities|mcp(\s+servers)?|apis?)\s+are\s+available"
        r"|what\s+can\s+you\s+access)",
        re.IGNORECASE,
    )
    _MCP_QUERY_RE = re.compile(
        r"(what(\s+all)?\s+mcp(\s+servers?)?\s*(are\s*)?(connected|available|active|running|enabled|linked|configured)"
        r"|(which|what)\s+mcp\s+servers?"
        r"|mcp\s+servers?\s+(are\s+)?(connected|available|active|running|enabled)"
        r"|connected\s+mcp(\s+servers?)?"
        r"|list\s+(the\s+)?mcp(\s+servers?)?"
        r"|show\s+(the\s+)?mcp(\s+servers?)?)",
        re.IGNORECASE,
    )

    _KENDR_CAPABILITIES = (
        "Here's what I can help you with:\n\n"
        "- **Software development** — create projects, write and review code, fix bugs\n"
        "- **GitHub** — clone repos, create branches, commit, push, open pull requests\n"
        "- **Research** — web search, document analysis, summarisation\n"
        "- **File management** — read, write, organise files in your working directory\n"
        "- **Terminal commands** — run shell commands safely\n"
        "- **Data analysis** — process spreadsheets, CSVs, and structured data\n"
        "- **Email & calendar** — draft and send via Gmail, Outlook, or Slack\n"
        "- **System setup** — configure integrations and API connections\n\n"
        "Just describe what you want and I'll figure out the best way to help."
    )

    def _skills_overview(self, state: dict) -> str:
        cards = state.get("available_agent_cards")
        if not isinstance(cards, list) or not cards:
            cards = [card.to_dict() for card in self.agent_routing.get_active_cards()]

        total = len(cards)
        mcp_count = sum(
            1
            for card in cards
            if str(card.get("agent_name", "")).startswith("mcp_")
        )
        category_counts: dict[str, int] = {}
        for card in cards:
            category = str(card.get("category_label") or card.get("category") or "General").strip()
            if not category:
                category = "General"
            category_counts[category] = category_counts.get(category, 0) + 1

        top_categories = sorted(
            category_counts.items(),
            key=lambda item: (-item[1], item[0].lower()),
        )[:6]
        category_summary = ", ".join(f"{name}: {count}" for name, count in top_categories) or "No active categories."

        return (
            f"I currently have {total} active skills/agents available.\n"
            f"- MCP-backed agents: {mcp_count}\n"
            f"- Top categories: {category_summary}\n"
            "- Run `kendr agents list` for the full list\n"
            "- Run `kendr mcp list` to inspect connected MCP servers and tools\n"
            "- Open `GET /registry/skills` for structured skill cards (category, config hints, status)"
        )

    def _mcp_servers_overview(self) -> str:
        """Return a human-readable summary of connected MCP servers and their tools."""
        try:
            from kendr.mcp_manager import list_servers_safe
            servers = list_servers_safe()
        except Exception:
            servers = []
        if not servers:
            return "No MCP servers are currently registered. Add one via the MCP Servers panel or `kendr mcp add`."
        lines = [f"I have {len(servers)} MCP server(s) registered:\n"]
        for srv in servers:
            name = str(srv.get("name") or srv.get("id") or "unknown")
            status = str(srv.get("status") or "unknown")
            enabled = bool(srv.get("enabled", True))
            tools = srv.get("tools") or []
            tool_names = [str(t.get("name", "")) for t in tools if t.get("name")]
            status_label = "connected" if status == "connected" and enabled else ("disabled" if not enabled else status)
            line = f"• **{name}** — {status_label}"
            if tool_names:
                line += f"\n  Tools: {', '.join(tool_names)}"
            else:
                line += "\n  Tools: none discovered yet (click Re-discover in MCP panel)"
            lines.append(line)
        return "\n".join(lines)

    def _is_registry_discovery_request(self, state: dict) -> bool:
        text = " ".join(
            [
                str(state.get("user_query", "")),
                str(state.get("current_objective", "")),
            ]
        ).strip()
        if not text:
            return False
        if self._REGISTRY_DISCOVERY_RE.search(text):
            return True
        if self._MCP_QUERY_RE.search(text):
            return True
        lowered = text.lower()
        return "what all skills do you have" in lowered

    def _is_mcp_discovery_request(self, state: dict) -> bool:
        text = " ".join(
            [
                str(state.get("user_query", "")),
                str(state.get("current_objective", "")),
            ]
        ).strip()
        if not text:
            return False
        return bool(self._MCP_QUERY_RE.search(text))

    def _direct_response_if_conversational(
        self, text: str, state: dict
    ) -> str | None:
        """Return a direct plain-text reply when *text* is a simple social or
        meta message that does not require the planner or any agent.

        Returns ``None`` to let the orchestrator proceed normally.

        Safety guards — returns None when:
        - The message is longer than 120 characters (likely a real task)
        - There are active plan steps (mid-task context)
        - A pending user-input question is waiting for a reply
        """
        text = (text or "").strip()
        if not text or len(text) > 120:
            return None
        if state.get("plan_steps") or state.get("plan_needs_clarification"):
            return None
        if str(state.get("pending_user_input_kind", "")).strip():
            return None

        if self._GREETING_RE.match(text):
            return (
                "Hi! I'm kendr, your multi-agent assistant. "
                "I can help you with software development, research, GitHub, "
                "file management, data analysis, and more.\n\n"
                "What would you like to work on?"
            )
        if self._FAREWELL_RE.match(text):
            return "Goodbye! Feel free to come back whenever you need help."
        if self._THANKS_RE.match(text):
            return "You're welcome! Let me know if there's anything else I can help with."
        if self._ACK_RE.match(text):
            return "Got it! Let me know whenever you're ready to continue."
        if self._MCP_QUERY_RE.search(text):
            return self._mcp_servers_overview()
        if self._SKILLS_RE.search(text):
            return self._skills_overview(state)
        if self._CAPABILITY_RE.search(text):
            return self._KENDR_CAPABILITIES

        return None

    def _is_github_request(self, state: dict) -> bool:
        """Return True when the query is a clear GitHub / git repository intent.

        Checks explicit state keys first, then applies keyword matching against
        the user query and current objective.  Excludes generic project-build
        requests so they continue through the normal blueprint/dev-pipeline flow.
        """
        if any(state.get(k) for k in ("github_repo", "github_owner", "github_task")):
            return True

        text = " ".join(
            [
                str(state.get("user_query", "")),
                str(state.get("current_objective", "")),
            ]
        ).lower()
        if not text.strip():
            return False

        strong_markers = (
            "open a pr",
            "open a pull request",
            "create a pull request",
            "create a pr",
            "merge the pr",
            "merge pr",
            "clone the repo",
            "clone the repository",
            "git clone",
            "push to github",
            "push to the repo",
            "list github issues",
            "list open issues on",
            "github issues",
            "create github issue",
            "open github issue",
            "fork the repo",
            "fork repo",
            "create a branch",
            "create branch",
            "switch branch",
            "checkout branch",
            "git commit",
            "commit and push",
            "git diff",
            "git push",
        )
        if any(m in text for m in strong_markers):
            return True

        if "github.com/" in text and "/" in text.split("github.com/", 1)[-1]:
            return True

        return False

    def _is_long_document_request(self, state: dict) -> bool:
        workflow_type = str(state.get("workflow_type", "") or "").strip().lower()
        if workflow_type in {"deep_research", "long_document"}:
            return True
        if bool(state.get("deep_research_mode", False)):
            return True
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
            "deep research report",
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
        step_index = self._plan_step_index_for_id(
            state,
            str(state.get("planned_active_step_id", "")).strip(),
            default=int(state.get("plan_step_index", 0) or 0),
        )
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

    @staticmethod
    def _plan_step_id(step: Mapping[str, Any], index: int) -> str:
        return str(step.get("id", "")).strip() or f"step-{index + 1}"

    def _plan_step_index_for_id(self, state: Mapping[str, Any], step_id: str, *, default: int = 0) -> int:
        target = str(step_id or "").strip()
        steps = state.get("plan_steps", [])
        if not target or not isinstance(steps, list):
            return default
        for index, step in enumerate(steps):
            if isinstance(step, dict) and self._plan_step_id(step, index) == target:
                return index
        return default

    @staticmethod
    def _plan_depends_on(step: Mapping[str, Any]) -> list[str]:
        raw = step.get("depends_on", [])
        if not isinstance(raw, list):
            return []
        return [str(item).strip() for item in raw if str(item).strip()]

    def _plan_graph(self, state: dict) -> TaskGraph | None:
        steps = state.get("plan_steps", [])
        if not isinstance(steps, list) or not steps:
            return None
        ids = {
            self._plan_step_id(step, index)
            for index, step in enumerate(steps)
            if isinstance(step, dict)
        }
        tasks: dict[str, dict[str, Any]] = {}
        for index, step in enumerate(steps):
            if not isinstance(step, dict):
                continue
            step_id = self._plan_step_id(step, index)
            tasks[step_id] = {
                "agent": str(step.get("agent", "")).strip() or "worker_agent",
                "depends_on": [dep for dep in self._plan_depends_on(step) if dep in ids],
            }
        if not tasks:
            return None
        try:
            return TaskGraph(tasks)
        except (CycleError, ValueError):
            return None

    def _plan_status_snapshot(self, state: dict) -> dict[str, set[str]]:
        steps = state.get("plan_steps", [])
        snapshot = {
            "success": set(),
            "active": set(),
            "blocked": set(),
            "open": set(),
        }
        if not isinstance(steps, list):
            return snapshot
        for index, step in enumerate(steps):
            if not isinstance(step, dict):
                continue
            step_id = self._plan_step_id(step, index)
            status = str(step.get("status", "")).strip().lower()
            if status in self._PLAN_SUCCESS_STATUSES:
                snapshot["success"].add(step_id)
            elif status in self._PLAN_ACTIVE_STATUSES:
                snapshot["active"].add(step_id)
            elif status in self._PLAN_BLOCKED_STATUSES:
                snapshot["blocked"].add(step_id)
            else:
                snapshot["open"].add(step_id)
        return snapshot

    def _plan_agent_lookup(self) -> dict[str, dict[str, Any]]:
        lookup: dict[str, dict[str, Any]] = {}
        for name, spec in self.registry.agents.items():
            metadata = dict(getattr(spec, "metadata", {}) or {})
            if metadata.get("side_effect_level"):
                metadata["side_effect_level"] = str(metadata.get("side_effect_level", "")).strip().lower()
            lookup[name] = {
                "metadata": metadata,
                "output_keys": list(getattr(spec, "output_keys", []) or []),
                "input_keys": list(getattr(spec, "input_keys", []) or []),
                "side_effect_level": metadata.get("side_effect_level", ""),
                "read_only": bool(metadata.get("read_only", False)),
            }
        return lookup

    def _ensure_plan_safety_metadata(self, state: dict) -> list[dict]:
        steps = state.get("plan_steps", [])
        if not isinstance(steps, list) or not steps:
            return []
        annotated = annotate_plan_steps(steps, agent_lookup=self._plan_agent_lookup())
        if annotated != steps:
            state["plan_steps"] = annotated
            plan_data = state.get("plan_data")
            if isinstance(plan_data, dict) and isinstance(plan_data.get("execution_steps"), list):
                plan_data = dict(plan_data)
                plan_data["execution_steps"] = annotated
                state["plan_data"] = plan_data
        return state.get("plan_steps", [])

    def _plan_step_record(self, state: Mapping[str, Any], step_id: str) -> tuple[int, dict[str, Any] | None]:
        resolved_step_id = str(step_id or "").strip()
        steps = state.get("plan_steps", [])
        if not resolved_step_id or not isinstance(steps, list):
            return -1, None
        for index, step in enumerate(steps):
            if isinstance(step, dict) and self._plan_step_id(step, index) == resolved_step_id:
                return index, step
        return -1, None

    def _apply_plan_task_row(self, state: dict, row: Mapping[str, Any]) -> None:
        step_id = str(row.get("step_id", "")).strip()
        index, step = self._plan_step_record(state, step_id)
        if index < 0 or not isinstance(step, dict):
            return
        step["status"] = str(row.get("status", step.get("status", "")) or step.get("status", "")).strip()
        step["side_effect_level"] = str(row.get("side_effect_level", step.get("side_effect_level", "")) or step.get("side_effect_level", "")).strip()
        conflict_keys = row.get("conflict_keys", step.get("conflict_keys", []))
        if isinstance(conflict_keys, list):
            step["conflict_keys"] = [str(item).strip() for item in conflict_keys if str(item).strip()]
        step["lease_owner"] = str(row.get("lease_owner", step.get("lease_owner", "")) or step.get("lease_owner", "")).strip()
        step["lease_expires_at"] = row.get("lease_expires_at") or step.get("lease_expires_at")
        step["attempt_count"] = int(row.get("attempt_count", step.get("attempt_count", 0)) or step.get("attempt_count", 0) or 0)
        step["last_attempt_at"] = row.get("last_attempt_at") or step.get("last_attempt_at")
        step["started_at"] = row.get("started_at") or step.get("started_at")
        step["completed_at"] = row.get("completed_at") or step.get("completed_at")
        step["result_summary"] = row.get("result_summary") or step.get("result_summary")
        step["error"] = row.get("error") or step.get("error")

    def _claim_plan_step_lease(
        self,
        state: dict,
        step_id: str,
        *,
        lease_owner: str = "",
        lease_seconds: int = 300,
    ) -> dict[str, Any] | None:
        plan_id = str(state.get("orchestration_plan_id", "")).strip()
        resolved_step_id = str(step_id or "").strip()
        if not plan_id or not resolved_step_id:
            return None
        owner = lease_owner or f"{state.get('run_id', 'run')}:{resolved_step_id}:{uuid.uuid4().hex[:8]}"
        try:
            row = claim_plan_task(
                plan_id,
                resolved_step_id,
                lease_owner=owner,
                lease_seconds=lease_seconds,
                db_path=self._db_path(state),
            )
        except Exception:
            return None
        if isinstance(row, dict):
            self._apply_plan_task_row(state, row)
        return row

    def _release_plan_step_lease(self, state: dict, step_id: str, *, lease_owner: str = "") -> None:
        plan_id = str(state.get("orchestration_plan_id", "")).strip()
        resolved_step_id = str(step_id or "").strip()
        if plan_id and resolved_step_id:
            try:
                release_plan_task_lease(
                    plan_id,
                    resolved_step_id,
                    lease_owner=str(lease_owner or "").strip(),
                    db_path=self._db_path(state),
                )
            except Exception:
                pass
        index, step = self._plan_step_record(state, resolved_step_id)
        if index >= 0 and isinstance(step, dict):
            step["lease_owner"] = ""
            step["lease_expires_at"] = None

    def _parallel_read_budget(self, state: Mapping[str, Any]) -> int:
        return max(1, int(state.get("max_parallel_read_tasks", self._DEFAULT_MAX_PARALLEL_READ_TASKS) or self._DEFAULT_MAX_PARALLEL_READ_TASKS))

    def _should_parallelize_planned_batch(self, state: dict, batch: list[dict[str, Any]]) -> bool:
        if not bool(state.get("parallel_read_only_enabled", True)):
            return False
        if len(batch) < 2:
            return False
        annotated = annotate_plan_steps(batch, agent_lookup=self._plan_agent_lookup())
        return can_parallelize_step_batch(annotated, agent_lookup=self._plan_agent_lookup())

    def _merge_parallel_child_result(self, state: dict, result: Mapping[str, Any]) -> None:
        ensure_a2a_state(state, state.get("available_agent_cards") or self._agent_cards())
        a2a = state.get("a2a", {})
        for key in ("messages", "tasks", "artifacts"):
            additions = result.get(f"a2a_{key}", [])
            if not isinstance(additions, list) or not additions:
                continue
            current = a2a.setdefault(key, [])
            current.extend(deepcopy(additions))

        history = state.get("agent_history", [])
        additions = result.get("agent_history", [])
        if isinstance(history, list) and isinstance(additions, list) and additions:
            history.extend(deepcopy(additions))
            state["agent_history"] = history

        output_values = result.get("output_values", {})
        if isinstance(output_values, Mapping):
            for key, value in output_values.items():
                state[str(key)] = deepcopy(value)

        merged_surfaces = state.get("used_execution_surfaces", [])
        if not isinstance(merged_surfaces, list):
            merged_surfaces = []
        seen_labels = {
            str(item.get("label", "")).strip()
            for item in merged_surfaces
            if isinstance(item, dict) and str(item.get("label", "")).strip()
        }
        for entry in result.get("used_execution_surfaces", []):
            if not isinstance(entry, dict):
                continue
            label = str(entry.get("label", "")).strip()
            if label and label in seen_labels:
                continue
            if label:
                seen_labels.add(label)
            merged_surfaces.append(deepcopy(entry))
        state["used_execution_surfaces"] = merged_surfaces

        step_id = str(result.get("step_id", "")).strip()
        if step_id:
            parallel_results = state.get("parallel_step_results", {})
            if not isinstance(parallel_results, dict):
                parallel_results = {}
            parallel_results[step_id] = {
                "agent": str(result.get("agent", "")).strip(),
                "status": "completed" if bool(result.get("success", False)) else "failed",
                "output_excerpt": self._truncate(str(result.get("output_text", "") or "")),
                "error": self._truncate(str(result.get("error_text", "") or "")),
                "output_keys": sorted(str(key).strip() for key in (result.get("output_values", {}) or {}).keys() if str(key).strip()),
            }
            state["parallel_step_results"] = parallel_results

    def _run_parallel_plan_step(self, base_state: dict, step: dict[str, Any]) -> dict[str, Any]:
        child_state = deepcopy(base_state)
        ensure_a2a_state(child_state, child_state.get("available_agent_cards") or self._agent_cards())
        baseline_messages = len(child_state["a2a"].get("messages", []))
        baseline_tasks = len(child_state["a2a"].get("tasks", []))
        baseline_artifacts = len(child_state["a2a"].get("artifacts", []))
        baseline_history = len(child_state.get("agent_history", []) or [])

        step_id = str(step.get("id", "")).strip()
        agent_name = str(step.get("agent") or "worker_agent").strip()
        task_content = str(step.get("task") or child_state.get("current_objective") or child_state.get("user_query") or "").strip()
        success_criteria = str(step.get("success_criteria", "")).strip()
        reason = f"Execute parallel planned step {step_id}: {success_criteria or task_content}"

        child_state["_parallel_plan_step"] = True
        child_state["_skip_review_once"] = True
        child_state["_suppress_session_record"] = True
        child_state["orchestrator_reason"] = reason
        child_state["current_objective"] = task_content
        child_state["planned_active_agent"] = agent_name
        child_state["planned_active_step_id"] = step_id
        child_state["planned_active_step_title"] = str(step.get("title", "")).strip()
        child_state["planned_active_step_success_criteria"] = success_criteria
        child_state["current_plan_step_id"] = step_id
        child_state["current_plan_step_title"] = str(step.get("title", "")).strip()
        child_state["current_plan_step_success_criteria"] = success_criteria
        child_state = append_task(
            child_state,
            make_task(
                sender=self._PARALLEL_PLAN_EXECUTOR,
                recipient=agent_name,
                intent="planned-parallel-step",
                content=task_content,
                state_updates={
                    "current_objective": task_content,
                    "current_plan_step_id": step_id,
                    "current_plan_step_title": str(step.get("title", "")).strip(),
                    "current_plan_step_success_criteria": success_criteria,
                },
            ),
        )

        try:
            child_state = self._execute_agent(child_state, agent_name)
            error_text = ""
        except Exception as exc:
            error_text = str(exc)
            child_state["last_agent"] = agent_name
            child_state["last_agent_status"] = "error"
            child_state["last_agent_output"] = error_text

        agent_spec = self.registry.agents.get(agent_name)
        output_keys = list(getattr(agent_spec, "output_keys", []) or []) if agent_spec else []
        output_values = {
            key: deepcopy(child_state.get(key))
            for key in output_keys
            if key in child_state
        }
        last_status = str(child_state.get("last_agent_status", "")).strip().lower()
        output_text = str(child_state.get("last_agent_output", "") or error_text).strip()
        failure_checkpoint = child_state.get("failure_checkpoint", {}) if isinstance(child_state.get("failure_checkpoint"), dict) else {}
        return {
            "step_id": step_id,
            "agent": agent_name,
            "success": last_status == "success",
            "output_text": output_text,
            "error_text": error_text or str(child_state.get("last_error", "") or ""),
            "output_values": output_values,
            "a2a_messages": deepcopy(child_state["a2a"].get("messages", [])[baseline_messages:]),
            "a2a_tasks": deepcopy(child_state["a2a"].get("tasks", [])[baseline_tasks:]),
            "a2a_artifacts": deepcopy(child_state["a2a"].get("artifacts", [])[baseline_artifacts:]),
            "agent_history": deepcopy((child_state.get("agent_history", []) or [])[baseline_history:]),
            "used_execution_surfaces": deepcopy(child_state.get("used_execution_surfaces", [])),
            "failure_checkpoint": deepcopy(failure_checkpoint),
        }

    def _execute_parallel_plan_batch(self, state: dict) -> dict:
        batch_ids = state.get("parallel_plan_batch", [])
        if not isinstance(batch_ids, list) or not batch_ids:
            return state
        self._ensure_plan_safety_metadata(state)
        selected_steps: list[dict[str, Any]] = []
        for step_id in batch_ids:
            _, step = self._plan_step_record(state, str(step_id).strip())
            if isinstance(step, dict):
                selected_steps.append(dict(step))
        if not self._should_parallelize_planned_batch(state, selected_steps):
            state["parallel_plan_batch"] = []
            state["parallel_plan_batch_size"] = 0
            return state

        batch_owner = f"{state.get('run_id', 'run')}:parallel:{uuid.uuid4().hex[:8]}"
        runnable_steps: list[dict[str, Any]] = []
        for step in selected_steps:
            step_id = str(step.get("id", "")).strip()
            claimed = self._claim_plan_step_lease(state, step_id, lease_owner=batch_owner)
            if claimed is None:
                continue
            step_index = self._plan_step_index_for_id(state, step_id)
            self._mark_step_running(state, step_index)
            _, local_step = self._plan_step_record(state, step_id)
            if isinstance(local_step, dict):
                runnable_steps.append(dict(local_step))

        if not runnable_steps:
            state["parallel_plan_batch"] = []
            state["parallel_plan_batch_size"] = 0
            state["review_pending"] = False
            state["review_pending_reason"] = ""
            return state

        max_workers = min(self._parallel_read_budget(state), len(runnable_steps))
        base_state = deepcopy(state)
        success_count = 0
        failure_count = 0
        batch_lines: list[str] = []
        with ThreadPoolExecutor(max_workers=max_workers) as pool:
            futures = {
                pool.submit(self._run_parallel_plan_step, base_state, dict(step)): dict(step)
                for step in runnable_steps
            }
            for future in as_completed(futures):
                step = futures[future]
                step_id = str(step.get("id", "")).strip()
                step_title = str(step.get("title", "")).strip()
                agent_name = str(step.get("agent", "")).strip()
                state["planned_active_agent"] = agent_name
                state["planned_active_step_id"] = step_id
                state["planned_active_step_title"] = step_title
                state["planned_active_step_success_criteria"] = str(step.get("success_criteria", "")).strip()
                try:
                    result = future.result()
                except Exception as exc:
                    result = {
                        "step_id": step_id,
                        "agent": agent_name,
                        "success": False,
                        "output_text": "",
                        "error_text": str(exc),
                        "output_values": {},
                        "a2a_messages": [],
                        "a2a_tasks": [],
                        "a2a_artifacts": [],
                        "agent_history": [],
                        "used_execution_surfaces": [],
                        "failure_checkpoint": {},
                    }
                self._merge_parallel_child_result(state, result)
                if bool(result.get("success", False)):
                    success_count += 1
                    state["last_agent"] = agent_name
                    state["last_agent_status"] = "success"
                    state["last_agent_output"] = str(result.get("output_text", "") or "").strip()
                    self._mark_planned_step_complete(state, result_text=self._truncate(state["last_agent_output"], 300))
                    batch_lines.append(f"{step_id}: completed")
                else:
                    failure_count += 1
                    error_text = str(result.get("error_text", "") or "parallel planned step failed").strip()
                    state["last_error"] = error_text
                    self._mark_step_failed(state, self._plan_step_index_for_id(state, step_id), error_text)
                    if not state.get("failure_checkpoint") and isinstance(result.get("failure_checkpoint"), dict):
                        state["failure_checkpoint"] = dict(result.get("failure_checkpoint", {}))
                    batch_lines.append(f"{step_id}: failed")

        state["effective_steps"] = int(state.get("effective_steps", 0) or 0) + success_count
        state["planned_active_agent"] = ""
        state["planned_active_step_id"] = ""
        state["planned_active_step_title"] = ""
        state["planned_active_step_success_criteria"] = ""
        state["current_plan_step_id"] = ""
        state["current_plan_step_title"] = ""
        state["current_plan_step_success_criteria"] = ""
        state["parallel_plan_batch"] = []
        state["parallel_plan_batch_size"] = 0
        state["active_task"] = None
        state["active_agent_task"] = ""
        state["next_agent"] = ""
        state["review_pending"] = False
        state["review_pending_reason"] = ""

        batch_status = "completed" if failure_count == 0 else ("partial" if success_count else "failed")
        batch_summary = (
            f"Parallel batch finished with {success_count} completed and {failure_count} failed steps."
            + (f" Details: {', '.join(batch_lines)}." if batch_lines else "")
        )
        state["last_agent"] = self._PARALLEL_PLAN_EXECUTOR
        state["last_agent_status"] = "success" if failure_count == 0 else "error"
        state["last_agent_output"] = batch_summary
        log_task_update("Plan", batch_summary)
        self._record_orchestration_event(
            state,
            event_type="plan.parallel_batch.completed",
            subject_type="plan",
            subject_id=str(state.get("orchestration_plan_id", "")).strip() or str(state.get("run_id", "")).strip(),
            status=batch_status,
            payload={
                "step_ids": [str(step.get("id", "")).strip() for step in runnable_steps],
                "completed": success_count,
                "failed": failure_count,
            },
        )
        return state

    def _refresh_plan_readiness(self, state: dict, *, persist: bool = True) -> list[dict]:
        steps = self._ensure_plan_safety_metadata(state)
        if not isinstance(steps, list) or not steps:
            return []
        graph = self._plan_graph(state)
        if graph is None:
            return steps
        status_snapshot = self._plan_status_snapshot(state)
        completed = set(status_snapshot["success"])
        blocked = set(status_snapshot["blocked"])
        changed = False
        for index, step in enumerate(steps):
            if not isinstance(step, dict):
                continue
            step_id = self._plan_step_id(step, index)
            status = str(step.get("status", "")).strip().lower()
            if not status:
                status = "pending"
                step["status"] = status
                changed = True
            if status in self._PLAN_SUCCESS_STATUSES | self._PLAN_ACTIVE_STATUSES | self._PLAN_BLOCKED_STATUSES:
                continue
            deps = graph.dependencies(step_id)
            if any(dep in blocked for dep in deps):
                new_status = "blocked"
            elif all(dep in completed for dep in deps):
                new_status = "ready"
            else:
                new_status = "waiting"
            if status != new_status:
                step["status"] = new_status
                changed = True
                if persist and str(state.get("orchestration_plan_id", "")).strip():
                    try:
                        update_plan_task_state(
                            str(state.get("orchestration_plan_id", "")).strip(),
                            step_id,
                            status=new_status,
                            metadata={"step_index": index},
                            db_path=self._db_path(state),
                        )
                    except Exception:
                        pass
        if changed:
            state["plan_steps"] = steps
            self._flush_live_plan(state)
        return steps

    def _next_planned_agents(self, state: dict, *, ignore_active: bool = False) -> list[dict]:
        steps = self._refresh_plan_readiness(state)
        if not steps:
            return []
        if not ignore_active:
            if str(state.get("planned_active_agent", "")).strip() or str(state.get("planned_active_step_id", "")).strip():
                return []
            if any(
                isinstance(step, dict) and str(step.get("status", "")).strip().lower() in self._PLAN_ACTIVE_STATUSES
                for step in steps
            ):
                return []
        ready_steps: list[tuple[int, dict[str, Any]]] = []
        for index, step in enumerate(steps):
            if not isinstance(step, dict):
                continue
            status = str(step.get("status", "")).strip().lower()
            if status != "ready":
                continue
            ready_steps.append((index, step))
        if not ready_steps:
            if all(
                isinstance(step, dict)
                and str(step.get("status", "")).strip().lower() in self._PLAN_SUCCESS_STATUSES | self._PLAN_BLOCKED_STATUSES
                for step in steps
                if isinstance(step, dict)
            ):
                state["plan_step_index"] = len(steps)
            return []
        first_index, first_step = ready_steps[0]
        state["plan_step_index"] = first_index
        group = str(first_step.get("parallel_group") or "").strip()
        if not group:
            return [first_step]
        batch = [step for _, step in ready_steps if str(step.get("parallel_group") or "").strip() == group]
        return batch or [first_step]

    def _quality_gate_report(self, state: dict) -> tuple[bool, str]:
        lines: list[str] = []
        all_ok = True

        failure_checkpoint = state.get("failure_checkpoint", {})
        if isinstance(failure_checkpoint, dict) and failure_checkpoint:
            failed_agent = str(failure_checkpoint.get("agent", "")).strip() or "unknown"
            failed_error = str(
                failure_checkpoint.get("error")
                or state.get("last_error")
                or ""
            ).strip() or "unknown error"
            lines.extend(
                [
                    "Unresolved failure checkpoint:",
                    f"- agent: {failed_agent}",
                    f"- error: {failed_error}",
                ]
            )
            all_ok = False

        if not bool(state.get("project_build_mode", False)):
            return all_ok, "\n".join(lines).strip()
        if not bool(state.get("enforce_quality_gate", True)):
            return all_ok, "\n".join(lines).strip()

        checks = [
            ("tests", state.get("test_agent_status"), {"passed", "pass", "ok", "completed"}),
            ("security_scan", state.get("security_scan_status"), {"passed", "pass", "ok", "completed"}),
            ("verifier", state.get("verifier_status"), {"pass", "passed", "ok", "completed"}),
        ]
        lines.append("Quality gate checks:")
        for name, value, ok_values in checks:
            status = str(value or "missing").strip().lower() or "missing"
            ok = status in ok_values
            all_ok = all_ok and ok
            lines.append(f"- {name}: {status}")
        return all_ok, "\n".join(lines)

    def _no_progress_signature(self, state: Mapping[str, Any]) -> str:
        steps = state.get("plan_steps", [])
        ready_steps: list[str] = []
        waiting_steps: list[str] = []
        running_steps: list[str] = []
        if isinstance(steps, list):
            for index, step in enumerate(steps):
                if not isinstance(step, dict):
                    continue
                status = str(step.get("status", "")).strip().lower()
                step_id = self._plan_step_id(step, index)
                if status == "ready":
                    ready_steps.append(step_id)
                elif status == "waiting":
                    waiting_steps.append(step_id)
                elif status == "running":
                    running_steps.append(step_id)
        signature = {
            "ready_steps": ready_steps,
            "waiting_steps": waiting_steps,
            "running_steps": running_steps,
            "plan_step_index": int(state.get("plan_step_index", 0) or 0),
            "plan_ready": bool(state.get("plan_ready", False)),
            "plan_waiting_for_approval": bool(state.get("plan_waiting_for_approval", False)),
            "pending_user_input_kind": str(state.get("pending_user_input_kind", "")).strip(),
            "approval_pending_scope": str(state.get("approval_pending_scope", "")).strip(),
            "review_pending": bool(state.get("review_pending", False)),
            "review_target_agent": str(state.get("review_target_agent", "")).strip(),
            "last_agent": str(state.get("last_agent", "")).strip(),
            "last_agent_status": str(state.get("last_agent_status", "")).strip(),
            "parallel_plan_batch": [str(item).strip() for item in state.get("parallel_plan_batch", []) if str(item).strip()] if isinstance(state.get("parallel_plan_batch", []), list) else [],
            "next_agent": str(state.get("next_agent", "")).strip(),
        }
        return json.dumps(signature, sort_keys=True, ensure_ascii=False)

    def _dispatch_stalled_replan(self, state: dict, current_objective: str) -> dict:
        feedback = (
            "Executor detected repeated no-progress orchestration cycles. "
            "Regenerate a simpler plan, prefer direct capable agents, reduce unnecessary review hops, "
            "and keep read-only steps safely parallelizable when possible."
        )
        state["_stalled_replan_attempted"] = True
        state["plan_ready"] = False
        state["plan_waiting_for_approval"] = False
        state["plan_approval_status"] = "draft"
        state["approval_pending_scope"] = ""
        state["pending_user_question"] = ""
        state["pending_user_input_kind"] = ""
        state["review_pending"] = False
        state["review_pending_reason"] = ""
        state["plan_revision_feedback"] = feedback
        state["plan_revision_count"] = int(state.get("plan_revision_count", 0) or 0) + 1
        state["orchestrator_reason"] = "No forward progress was detected. Regenerate the execution plan."
        state["next_agent"] = "planner_agent"
        log_task_update("Orchestrator", "No-progress watchdog triggered; regenerating the plan.")
        return append_task(
            state,
            make_task(
                sender="orchestrator_agent",
                recipient="planner_agent",
                intent="stalled-replan",
                content=current_objective,
                state_updates={
                    "current_objective": current_objective,
                    "plan_revision_feedback": feedback,
                },
            ),
        )

    def _handle_no_progress_watchdog(self, state: dict, current_objective: str) -> dict | None:
        if not bool(state.get("no_progress_watchdog_enabled", True)):
            return None
        if self._awaiting_user_input(state):
            state["_no_progress_signature"] = ""
            state["_no_progress_repeats"] = 0
            return None

        completed_plan_steps = sum(
            1
            for step in state.get("plan_steps", [])
            if isinstance(step, dict)
            and str(step.get("status", "")).strip().lower() in self._PLAN_SUCCESS_STATUSES
        )
        effective_steps = int(state.get("effective_steps", 0) or 0)
        signature = self._no_progress_signature(state)
        previous_effective_steps = state.get("_no_progress_effective_steps", -1)
        previous_completed_plan_steps = state.get("_no_progress_completed_plan_steps", -1)
        try:
            previous_effective_steps = int(previous_effective_steps)
        except Exception:
            previous_effective_steps = -1
        try:
            previous_completed_plan_steps = int(previous_completed_plan_steps)
        except Exception:
            previous_completed_plan_steps = -1
        if (
            signature != str(state.get("_no_progress_signature", "") or "")
            or effective_steps != previous_effective_steps
            or completed_plan_steps != previous_completed_plan_steps
        ):
            state["_no_progress_signature"] = signature
            state["_no_progress_repeats"] = 0
            state["_no_progress_effective_steps"] = effective_steps
            state["_no_progress_completed_plan_steps"] = completed_plan_steps
            return None

        repeats = int(state.get("_no_progress_repeats", 0) or 0) + 1
        state["_no_progress_repeats"] = repeats
        threshold = max(2, int(state.get("max_no_progress_cycles", self._DEFAULT_MAX_NO_PROGRESS_CYCLES) or self._DEFAULT_MAX_NO_PROGRESS_CYCLES))
        if repeats < threshold:
            return None

        if (
            state.get("plan_steps")
            and not bool(state.get("_stalled_replan_attempted", False))
            and self._is_agent_available(state, "planner_agent")
        ):
            return self._dispatch_stalled_replan(state, current_objective)

        message = (
            "Execution stalled because the orchestrator stopped making forward progress. "
            "This run was terminated to avoid an infinite loop."
        )
        state["next_agent"] = "__finish__"
        state["final_output"] = message
        log_task_update("Orchestrator", "No-progress watchdog terminated the run to avoid a loop.")
        return append_message(state, make_message("orchestrator_agent", "user", "final", message))

    def _flush_live_plan(self, state: dict) -> None:
        try:
            plan_data = state.get("plan_data")
            if not isinstance(plan_data, dict):
                return
            steps = state.get("plan_steps")
            if isinstance(steps, list):
                plan_data = dict(plan_data)
                plan_data["execution_steps"] = steps
            import json as _json
            from tasks.utils import write_text_file as _wtf
            _wtf("planner_output.json", _json.dumps(plan_data, indent=2, ensure_ascii=False))
            self._live_plan_data = plan_data
        except Exception:
            pass

    def _mark_step_running(self, state: dict, step_index: int) -> None:
        from datetime import datetime, timezone
        steps = state.get("plan_steps")
        if not isinstance(steps, list) or step_index < 0 or step_index >= len(steps):
            return
        step = steps[step_index]
        if not isinstance(step, dict):
            return
        step["status"] = "running"
        step["started_at"] = datetime.now(timezone.utc).isoformat()
        step["completed_at"] = None
        step["result_summary"] = None
        step["error"] = None
        state["plan_steps"] = steps
        self._flush_live_plan(state)
        plan_id = str(state.get("orchestration_plan_id", "")).strip()
        step_id = str(step.get("id", "")).strip()
        if plan_id and step_id:
            try:
                update_plan_task_state(
                    plan_id,
                    step_id,
                    status="running",
                    started_at=str(step.get("started_at", "")).strip() or None,
                    completed_at=None,
                    result_summary=None,
                    error_text="",
                    metadata={"step_index": step_index},
                    db_path=self._db_path(state),
                )
                update_execution_plan_status(
                    plan_id,
                    status="executing",
                    approval_status=str(state.get("plan_approval_status", "")).strip() or "approved",
                    db_path=self._db_path(state),
                )
                state["_persisted_plan_status"] = "executing"
                self._record_orchestration_event(
                    state,
                    event_type="plan_task.started",
                    subject_type="plan_task",
                    subject_id=step_id,
                    status="running",
                    payload={"step_index": step_index, "agent": step.get("agent", "")},
                )
            except Exception:
                pass

    def _mark_planned_step_complete(self, state: dict, result_text: str = "") -> None:
        from datetime import datetime, timezone
        current_step_id = str(state.get("planned_active_step_id", "")).strip()
        current_index = self._plan_step_index_for_id(
            state,
            current_step_id,
            default=int(state.get("plan_step_index", 0) or 0),
        )
        total_steps = len(state.get("plan_steps", []) or [])
        completed_title = (
            state.get("last_completed_plan_step_title")
            or state.get("planned_active_step_title")
            or state.get("current_plan_step_title")
            or state.get("planned_active_step_id")
            or "planned step"
        )
        steps = state.get("plan_steps")
        completed_count = int(state.get("plan_execution_count", 0) or 0) + 1
        if isinstance(steps, list) and 0 <= current_index < len(steps):
            step = steps[current_index]
            if isinstance(step, dict):
                lease_owner = str(step.get("lease_owner", "")).strip()
                step["status"] = "completed"
                step["completed_at"] = datetime.now(timezone.utc).isoformat()
                if result_text:
                    step["result_summary"] = result_text[:300]
                step["error"] = None
                plan_id = str(state.get("orchestration_plan_id", "")).strip()
                step_id = str(step.get("id", "")).strip()
                if plan_id and step_id:
                    try:
                        update_plan_task_state(
                            plan_id,
                            step_id,
                            status="completed",
                            completed_at=str(step.get("completed_at", "")).strip() or None,
                            result_summary=str(step.get("result_summary", "")).strip() or None,
                            error_text="",
                            metadata={"step_index": current_index},
                            db_path=self._db_path(state),
                        )
                        self._refresh_plan_readiness(state)
                        remaining_batch = self._next_planned_agents(state, ignore_active=True)
                        plan_status = "completed" if not remaining_batch else "executing"
                        update_execution_plan_status(
                            plan_id,
                            status=plan_status,
                            approval_status=str(state.get("plan_approval_status", "")).strip() or "approved",
                            db_path=self._db_path(state),
                        )
                        state["_persisted_plan_status"] = plan_status
                        self._record_orchestration_event(
                            state,
                            event_type="plan_task.completed",
                            subject_type="plan_task",
                            subject_id=step_id,
                            status="completed",
                            payload={
                                "step_index": current_index,
                                "result_summary": str(step.get("result_summary", "")).strip(),
                            },
                        )
                    except Exception:
                        pass
                self._release_plan_step_lease(state, step_id, lease_owner=lease_owner)
            state["plan_steps"] = steps
            completed_count = sum(
                1
                for item in steps
                if isinstance(item, dict)
                and str(item.get("status", "")).strip().lower() in self._PLAN_SUCCESS_STATUSES
            )
        remaining_batch = self._next_planned_agents(state, ignore_active=True)
        next_index = self._plan_step_index_for_id(
            state,
            self._plan_step_id(remaining_batch[0], 0) if remaining_batch and isinstance(remaining_batch[0], dict) else "",
            default=len(steps) if isinstance(steps, list) else 0,
        )
        self._flush_live_plan(state)
        log_task_update("Plan", f"Completed step {completed_count}/{total_steps}: {completed_title}.")
        state["plan_step_index"] = next_index
        state["plan_execution_count"] = completed_count
        update_planning_file(
            state,
            status="executing" if remaining_batch else "completed",
            objective=state.get("current_objective", state.get("user_query", "")),
            plan_text=state.get("plan", ""),
            clarifications=state.get("plan_clarification_questions", []),
            execution_note=(
                f"Executed step index {state.get('plan_step_index', 0)} "
                f"via agent {state.get('last_agent', '')}."
            ),
        )

    def _mark_step_failed(self, state: dict, step_index: int, error_message: str) -> None:
        from datetime import datetime, timezone
        steps = state.get("plan_steps")
        if not isinstance(steps, list) or step_index < 0 or step_index >= len(steps):
            return
        step = steps[step_index]
        if not isinstance(step, dict):
            return
        lease_owner = str(step.get("lease_owner", "")).strip()
        step["status"] = "failed"
        step["completed_at"] = datetime.now(timezone.utc).isoformat()
        step["error"] = error_message[:300]
        state["plan_step_index"] = step_index
        state["plan_steps"] = steps
        self._flush_live_plan(state)
        plan_id = str(state.get("orchestration_plan_id", "")).strip()
        step_id = str(step.get("id", "")).strip()
        if plan_id and step_id:
            try:
                update_plan_task_state(
                    plan_id,
                    step_id,
                    status="failed",
                    completed_at=str(step.get("completed_at", "")).strip() or None,
                    error_text=str(step.get("error", "")).strip() or error_message[:300],
                    metadata={"step_index": step_index},
                    db_path=self._db_path(state),
                )
                update_execution_plan_status(
                    plan_id,
                    status="failed",
                    approval_status=str(state.get("plan_approval_status", "")).strip() or "approved",
                    db_path=self._db_path(state),
                )
                state["_persisted_plan_status"] = "failed"
                self._record_orchestration_event(
                    state,
                    event_type="plan_task.failed",
                    subject_type="plan_task",
                    subject_id=step_id,
                    status="failed",
                    payload={"step_index": step_index, "error": error_message[:300]},
                )
            except Exception:
                pass
        self._release_plan_step_lease(state, step_id, lease_owner=lease_owner)

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
        requested_agent_name = str(agent_name or "").strip()
        workflow_type = str(state.get("workflow_type", "") or "").strip().lower()
        if (
            requested_agent_name == "deep_research_agent"
            and self._is_agent_available(state, "long_document_agent")
            and (
                workflow_type in {"deep_research", "long_document"}
                or bool(state.get("deep_research_mode", False))
                or bool(state.get("long_document_mode", False))
                or bool(state.get("local_drive_force_long_document", False))
            )
        ):
            agent_name = "long_document_agent"
            active_task = state.get("active_task")
            active_task_id = ""
            if isinstance(active_task, dict) and str(active_task.get("recipient", "")).strip() == requested_agent_name:
                active_task["recipient"] = agent_name
                state["active_task"] = active_task
                active_task_id = str(active_task.get("task_id", "") or "").strip()
            ensure_a2a_state(state, state.get("available_agent_cards") or self._agent_cards())
            for task in state.get("a2a", {}).get("tasks", []):
                if not isinstance(task, dict):
                    continue
                if active_task_id and str(task.get("task_id", "")).strip() != active_task_id:
                    continue
                if str(task.get("recipient", "")).strip() == requested_agent_name and str(task.get("status", "pending")).strip() == "pending":
                    task["recipient"] = agent_name
                    break
            if str(state.get("review_target_agent", "") or "").strip() == requested_agent_name:
                state["review_target_agent"] = agent_name
            if str(state.get("review_subject_agent", "") or "").strip() == requested_agent_name:
                state["review_subject_agent"] = agent_name
            log_task_update(
                "System",
                "Redirecting deep_research_agent to long_document_agent for the canonical deep research pipeline.",
            )
        parallel_plan_step = bool(state.get("_parallel_plan_step", False))
        if not self._is_agent_available(state, agent_name):
            unavailable_reason = (
                f"{agent_name} is not configured in the current environment. "
                f"Missing setup: {json.dumps(state.get('disabled_agents', {}).get(agent_name, {}), ensure_ascii=False)}"
            )
            state["last_error"] = unavailable_reason
            state["review_pending"] = False
            state["review_pending_reason"] = ""
            state["failure_checkpoint"] = self._build_failure_checkpoint(state, agent_name, unavailable_reason, state.get("active_task"))
            return self._append_history(state, agent_name, "skipped", state.get("orchestrator_reason", ""), unavailable_reason)

        spec = self.registry.agents[agent_name]
        log_task_update("System", f"Dispatching to {agent_name}.")
        if not console_logging_suppressed():
            try:
                from kendr.cli_output import step_start as _cli_step_start
                _cli_step_start(agent_name)
            except Exception:
                pass
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
        if not parallel_plan_step:
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
        if not bool(state.get("_suppress_session_record", False)):
            self._write_session_record(state, status="running", active_agent=agent_name)

        before_state = {k: v for k, v in state.items() if k != "a2a"}
        _agent_start_mono = time.monotonic()
        _agent_start_ts = datetime.now(timezone.utc).isoformat()
        self._record_execution_trace(
            state,
            kind="agent",
            actor=agent_name,
            status="running",
            title=f"{agent_name} started",
            detail=self._active_task_summary(state, active_task),
            started_at=_agent_start_ts,
            metadata={
                "task_id": active_task["task_id"],
                "intent": active_task.get("intent", ""),
            },
        )
        _spinner_ctx = None
        try:
            from kendr.cli_output import make_spinner as _make_spinner
            import sys as _sys
            if getattr(_sys.stdout, "isatty", lambda: False)():
                _spinner = _make_spinner(description=f"{agent_name}")
                _spinner_task = _spinner.add_task(agent_name)
                _spinner.start()
                _spinner_ctx = _spinner
        except Exception:
            pass
        try:
            multi_model_override = self._multi_model_override_for_agent(state, agent_name)
            if multi_model_override:
                state["multi_model_last_selection"] = {
                    "agent": agent_name,
                    **multi_model_override,
                }
            else:
                state["multi_model_last_selection"] = {}
            override_ctx = (
                runtime_model_override(
                    str(multi_model_override.get("provider") or "").strip().lower(),
                    str(multi_model_override.get("model") or "").strip(),
                )
                if multi_model_override
                else nullcontext()
            )
            with agent_model_context(agent_name):
                with override_ctx:
                    state = spec.handler(state)
            if _spinner_ctx is not None:
                try:
                    _spinner_ctx.stop()
                except Exception:
                    pass
                _spinner_ctx = None
            _agent_elapsed = time.monotonic() - _agent_start_mono
            output_text = self._infer_agent_output(before_state, state)
            self._clear_agent_failures(state, agent_name)
            failure_checkpoint = state.get("failure_checkpoint", {})
            if isinstance(failure_checkpoint, dict):
                failed_agent = str(failure_checkpoint.get("agent", "")).strip()
                if failed_agent and failed_agent == str(agent_name).strip():
                    state["failure_checkpoint"] = {}
                    if str(state.get("last_error", "")).strip() == str(failure_checkpoint.get("error", "")).strip():
                        state["last_error"] = ""
            # Clear stale deterministic-block markers once an agent completes successfully.
            if isinstance(state.get("deterministic_failure"), dict):
                state.pop("deterministic_failure", None)
            state["effective_steps"] = int(state.get("effective_steps", 0)) + 1
            if active_task.get("status") == "pending":
                state = complete_task(state, active_task["task_id"], "completed")
            skip_review = bool(state.pop("_skip_review_once", False))
            hold_step_completion = bool(state.pop("_hold_planned_step_completion_once", False))
            requires_review, review_reason, review_meta = self._should_request_review(
                state,
                agent_name=agent_name,
                output_text=output_text,
                skip_review_once=skip_review,
            )
            state["review_pending"] = requires_review
            state["review_pending_reason"] = review_reason if requires_review else ""
            state["review_policy_last"] = {
                "run": bool(requires_review),
                "reason": review_reason,
                "signals": review_meta,
                "agent": agent_name,
            }
            state = self._append_history(state, agent_name, "success", state.get("orchestrator_reason", ""), output_text, start_timestamp=_agent_start_ts)
            self._record_execution_trace(
                state,
                kind="agent",
                actor=agent_name,
                status="completed",
                title=f"{agent_name} completed",
                detail=self._truncate(output_text, 240),
                started_at=_agent_start_ts,
                completed_at=datetime.now(timezone.utc).isoformat(),
                duration_ms=int(_agent_elapsed * 1000),
                metadata={
                    "task_id": active_task["task_id"],
                    "intent": active_task.get("intent", ""),
                },
            )
            if not console_logging_suppressed():
                try:
                    from kendr.cli_output import step_done as _cli_step_done
                    _cli_step_done(agent_name, duration=_agent_elapsed)
                except Exception:
                    pass
            if not parallel_plan_step:
                append_daily_memory_note(state, agent_name, "completed", self._truncate(output_text, 1000))
                append_session_event(state, agent_name, "completed", self._truncate(output_text, 600))
            if parallel_plan_step:
                state["review_pending"] = False
                state["review_pending_reason"] = ""
            if agent_name == str(state.get("planned_active_agent", "")).strip():
                state["last_completed_plan_step_id"] = str(state.get("planned_active_step_id", "")).strip()
                state["last_completed_plan_step_title"] = str(state.get("planned_active_step_title", "")).strip()
                state["last_completed_plan_step_success_criteria"] = str(state.get("planned_active_step_success_criteria", "")).strip()
                state["last_completed_plan_step_agent"] = str(agent_name).strip()
                if not parallel_plan_step and not hold_step_completion:
                    self._mark_planned_step_complete(state, result_text=self._truncate(output_text, 300))
                state["planned_active_agent"] = ""
                state["planned_active_step_id"] = ""
                state["planned_active_step_title"] = ""
                state["planned_active_step_success_criteria"] = ""
        except Exception as exc:
            if _spinner_ctx is not None:
                try:
                    _spinner_ctx.stop()
                except Exception:
                    pass
            error_message = str(exc)
            state["last_error"] = error_message
            self._record_agent_failure(state, agent_name, error_message)
            if not parallel_plan_step and agent_name == str(state.get("planned_active_agent", "")).strip():
                failed_index = self._plan_step_index_for_id(
                    state,
                    str(state.get("planned_active_step_id", "")).strip(),
                    default=int(state.get("plan_step_index", 0) or 0),
                )
                self._mark_step_failed(state, failed_index, error_message)
            state = complete_task(state, active_task["task_id"], "failed")
            state["review_pending"] = False
            state["review_pending_reason"] = ""
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
            state = self._append_history(state, agent_name, "error", state.get("orchestrator_reason", ""), error_message, start_timestamp=_agent_start_ts)
            self._record_execution_trace(
                state,
                kind="agent",
                actor=agent_name,
                status="failed",
                title=f"{agent_name} failed",
                detail=self._truncate(error_message, 240),
                started_at=_agent_start_ts,
                completed_at=datetime.now(timezone.utc).isoformat(),
                duration_ms=int((time.monotonic() - _agent_start_mono) * 1000),
                metadata={
                    "task_id": active_task["task_id"],
                    "intent": active_task.get("intent", ""),
                },
            )
            if not console_logging_suppressed():
                try:
                    from kendr.cli_output import step_error as _cli_step_error
                    _cli_step_error(agent_name, error_message)
                except Exception:
                    pass
            if not parallel_plan_step:
                append_daily_memory_note(state, agent_name, "failed", self._truncate(error_message, 1000))
                append_session_event(state, agent_name, "failed", self._truncate(error_message, 600))
                record_work_note(state, agent_name, "failed", f"task_id={active_task['task_id']}\nerror={error_message}")
            log_task_update("System", f"{agent_name} failed.", error_message)
            state["failure_checkpoint"] = self._build_failure_checkpoint(state, agent_name, error_message, active_task)
        return state

    def orchestrator_agent(self, state: dict) -> dict:
        self._ensure_workflow_type(state)
        state["orchestrator_calls"] = state.get("orchestrator_calls", 0) + 1
        max_steps = state.get("max_steps", 20)
        # effective_steps counts only successful agent completions (the real work budget).
        # orchestrator_calls counts every orchestrator invocation including retries/failures.
        # max_steps gates on effective_steps so retries don't eat the user's budget.
        # A hard safety ceiling (3x max_steps) prevents infinite loops even if nothing succeeds.
        effective_steps = int(state.get("effective_steps", 0))
        hard_ceiling = max_steps * 3
        state = self.apply_runtime_setup(state)
        state = self._refresh_intent_projection(state)
        state = self._sync_orchestration_plan_record(state)
        state["_policy_blocked_agents"] = []
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

        shell_plan_steps = state.get("shell_plan_steps")
        if (
            str(state.get("last_agent", "")).strip() == "shell_plan_agent"
            and isinstance(shell_plan_steps, list)
            and shell_plan_steps
            and all(
                str((step or {}).get("status", "")).strip().lower()
                in {"completed", "skipped", "failed", "blocked"}
                for step in shell_plan_steps
                if isinstance(step, dict)
            )
        ):
            state["next_agent"] = "__finish__"
            state["final_output"] = (
                state.get("final_output")
                or state.get("shell_plan_result")
                or state.get("draft_response")
                or state.get("last_agent_output")
                or "Shell plan completed."
            )
            state = append_message(state, make_message("orchestrator_agent", "user", "final", state["final_output"]))
            return state

        deterministic = state.get("deterministic_failure")
        if isinstance(deterministic, dict):
            agent = str(deterministic.get("agent", "agent") or "agent").strip()
            kind = str(deterministic.get("kind", "") or "").strip()
            reason = str(deterministic.get("reason", "") or "").strip()
            if kind == "policy_blocked_outside_scope":
                wd = str(deterministic.get("working_directory", "") or "").strip()
                message = (
                    f"{agent} blocked by command policy: {reason}. "
                    "This is deterministic, so the run was stopped to prevent a dispatch loop. "
                    "Fix by setting Project Root/working directory inside an allowed path, then retry."
                )
                if wd:
                    message += f" Blocked working directory: {wd}."
                state["next_agent"] = "__finish__"
                state["final_output"] = message
                state = append_message(state, make_message("orchestrator_agent", "user", "final", message))
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

        watchdog_result = self._handle_no_progress_watchdog(state, str(current_objective or ""))
        if watchdog_result is not None:
            return watchdog_result

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

        in_task_phase = (
            not state.get("incoming_payload")
            or (state.get("gateway_message") and state.get("channel_session"))
        )
        policy_result = self._dispatch_workflow_execution_policies(
            state,
            current_objective=current_objective,
            in_task_phase=in_task_phase,
        )
        if policy_result is not None:
            return policy_result

        state["_policy_blocked_agents"] = sorted(self._policy_blocked_agents(state))
        execution_mode = self._resolve_execution_mode(state, default="adaptive")
        direct_tool_rule = (
            "- Direct tool mode is enabled: prefer specialized `mcp_*` and `skill_*` agents (or other domain-specific agents) over `worker_agent` when a match exists."
            if execution_mode == "direct_tools"
            else ""
        )
        router_stage_toon = self._build_router_stage_toon(state, current_objective=str(current_objective or ""))
        state["router_stage_toon"] = router_stage_toon
        state["router_prompt_estimated_tokens"] = int(((router_stage_toon.get("budget_gate") or {}) if isinstance(router_stage_toon.get("budget_gate"), dict) else {}).get("estimated_tokens", 0) or 0)

        prompt = f"""
You are the orchestration agent for a plugin-driven multi-agent AI system.

Your job is to decide which agent should run next, or whether the workflow should finish.
Use the compact router stage context JSON below. It is intentionally budgeted and omits large raw state dumps.
Prefer the listed candidate agents first. If none fit, choose another value from `available_agent_names`.

Rules:
- Only choose `finish` or an agent that appears in `available_agent_names`.
- Use the description of each agent as the source of truth for what it does.
- If incoming_channel or incoming_payload is present and gateway_message has not been created yet, prefer channel_gateway_agent first.
- If gateway_message exists but channel_session is missing, prefer session_router_agent before other work.
- If the user asks for an unavailable integration, use worker_agent to explain the missing setup unless agent_factory_agent is better suited.
- For end-to-end software build requests that need detailed architecture, project planning, and delegated implementation/setup, prefer master_coding_agent first.
- For GitHub / git repository operations (clone, PR, issue, push, branch, commit, fork, diff), prefer github_agent directly — do not route through the generic planner.
- Finish when the current state already contains a good final answer.
- Never use any agent for exploitation, credential attacks, service disruption, or unauthorized access.
- If the reviewer already requested a retry, follow that instruction rather than inventing a different reroute.
- Avoid repeating the same failing agent unless the inputs changed.
- Put only useful state updates for the chosen agent in `state_updates`.
- Missing raw details can be fetched later by the selected agent. Route from the compact context you have.
{direct_tool_rule}

Router stage context (JSON):
{json.dumps(router_stage_toon, indent=2, ensure_ascii=False)}

Return ONLY valid JSON in this exact schema:
{{
  "agent": "agent name from available_agent_names or finish",
  "reason": "short reason",
  "state_updates": {{}},
  "task_content": "short task content for the chosen agent",
  "final_response": "required only when agent is finish"
}}
""".strip()

        _MAX_RETRIES = 2
        _RETRY_DELAY = 1.0
        raw_output = None
        last_llm_exc = None
        for _attempt in range(_MAX_RETRIES + 1):
            try:
                orchestrator_override = self._multi_model_override_for_agent(state, "orchestrator_agent")
                override_ctx = (
                    runtime_model_override(
                        str(orchestrator_override.get("provider") or "").strip().lower(),
                        str(orchestrator_override.get("model") or "").strip(),
                    )
                    if orchestrator_override
                    else nullcontext()
                )
                with agent_model_context("orchestrator_agent"):
                    with override_ctx:
                        response = llm.invoke(prompt)
                raw_output = response.content.strip() if hasattr(response, "content") else str(response).strip()
                last_llm_exc = None
                break
            except Exception as llm_exc:
                last_llm_exc = llm_exc
                exc_name = type(llm_exc).__name__.lower()
                is_transient = any(kw in exc_name for kw in ("connection", "timeout", "network", "unavailable"))
                if is_transient and _attempt < _MAX_RETRIES:
                    _delay = _RETRY_DELAY * (2 ** _attempt)
                    logger.warning(
                        "Orchestrator LLM call failed (attempt %d/%d): %s — retrying in %.1fs",
                        _attempt + 1, _MAX_RETRIES + 1, llm_exc, _delay,
                    )
                    time.sleep(_delay)
                else:
                    logger.warning("Orchestrator LLM call failed: %s", llm_exc)
                    break

        if last_llm_exc is not None:
            decision = {
                "agent": "finish",
                "reason": f"Orchestrator LLM call failed ({type(last_llm_exc).__name__}: {last_llm_exc}). "
                          "This is likely a network or API provider issue.",
                "state_updates": {},
                "final_response": (
                    state.get("draft_response")
                    or state.get("last_agent_output")
                    or f"The orchestrator could not reach the LLM provider: {last_llm_exc}. "
                       "Check your network connection and API keys, then retry."
                ),
            }
            state["last_error"] = f"orchestrator_llm_failed: {last_llm_exc}"
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
            final_response = str(decision.get("final_response") or "").strip()
            if final_response == "No final response was generated.":
                final_response = ""
            state["final_output"] = (
                final_response
                or state.get("draft_response")
                or state.get("last_agent_output")
                or "No final response was generated."
            )
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
        workflow.add_node(self._PARALLEL_PLAN_EXECUTOR, self._execute_parallel_plan_batch)
        for agent_name in self.registry.agents:
            workflow.add_node(agent_name, lambda state, name=agent_name: self._execute_agent(state, name))
        workflow.set_entry_point("orchestrator_agent")
        edge_map = {agent_name: agent_name for agent_name in self.registry.agents}
        edge_map[self._PARALLEL_PLAN_EXECUTOR] = self._PARALLEL_PLAN_EXECUTOR
        edge_map["__finish__"] = END
        workflow.add_conditional_edges("orchestrator_agent", self.orchestrator_router, edge_map)
        for agent_name in self.registry.agents:
            workflow.add_edge(agent_name, "orchestrator_agent")
        workflow.add_edge(self._PARALLEL_PLAN_EXECUTOR, "orchestrator_agent")
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
        restore_pending_user_input(self, initial_state, prior_channel_state, user_query)

    def _seed_resumed_plan_step_statuses(self, state: RuntimeState, *, resume_index: int) -> None:
        steps = state.get("plan_steps", [])
        if not isinstance(steps, list) or not steps:
            return
        if any(str(step.get("status", "")).strip() for step in steps if isinstance(step, dict)):
            return

        resolved_index = max(0, min(int(resume_index or 0), len(steps) - 1))
        completed_count = 0
        for index, step in enumerate(steps):
            if not isinstance(step, dict):
                continue
            step["started_at"] = None
            step["completed_at"] = None
            step["result_summary"] = None
            step["error"] = None
            if index < resolved_index:
                step["status"] = "completed"
                completed_count += 1
            elif index == resolved_index:
                step["status"] = "ready"
            else:
                step["status"] = "waiting"

        if resolved_index > 0 and not str(state.get("last_completed_plan_step_id", "")).strip():
            previous_step = steps[resolved_index - 1]
            if isinstance(previous_step, dict):
                previous_id = self._plan_step_id(previous_step, resolved_index - 1)
                state["last_completed_plan_step_id"] = previous_id
                state["last_completed_plan_step_title"] = str(
                    previous_step.get("title")
                    or previous_step.get("task")
                    or previous_id
                ).strip()
        state["plan_execution_count"] = max(int(state.get("plan_execution_count", 0) or 0), completed_count)

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
            initial_state["review_pending_reason"] = ""
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
        if (
            bool(summary.get("awaiting_user_input", False))
            or str(snapshot.get("pending_user_input_kind", "")).strip()
            or state_awaiting_user_input(snapshot)
        ):
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
                self._seed_resumed_plan_step_statuses(
                    initial_state,
                    resume_index=int(initial_state.get("plan_step_index", 0) or 0),
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
        resolved_workflow_id = overrides.get("workflow_id", resolved_run_id)
        resolved_attempt_id = overrides.get("attempt_id", resolved_run_id)
        session_started_at = overrides.get("session_started_at") or datetime.now(timezone.utc).isoformat()
        communication_authorized = _truthy(
            overrides.get("communication_authorized"),
            default=_truthy(os.getenv("KENDR_COMMUNICATION_AUTHORIZED"), True),
        )
        initial_state: RuntimeState = {
            "db_path": str(overrides.get("db_path") or resolve_db_path()),
            "run_id": resolved_run_id,
            "workflow_id": resolved_workflow_id,
            "attempt_id": resolved_attempt_id,
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
            "parallel_plan_batch": [],
            "parallel_plan_batch_size": 0,
            "parallel_step_results": {},
            "orchestration_plan_id": "",
            "orchestration_plan_version": 0,
            "current_plan_step_id": "",
            "current_plan_step_title": "",
            "current_plan_step_success_criteria": "",
            "last_completed_plan_step_id": "",
            "last_completed_plan_step_title": "",
            "last_completed_plan_step_success_criteria": "",
            "last_completed_plan_step_agent": "",
            "intent_signature": "",
            "selected_intent_id": "",
            "selected_intent_type": "",
            "selected_intent": {},
            "intent_candidates": [],
            "parallel_read_only_enabled": _truthy(overrides.get("parallel_read_only_enabled"), True),
            "max_parallel_read_tasks": int(overrides.get("max_parallel_read_tasks", self._DEFAULT_MAX_PARALLEL_READ_TASKS) or self._DEFAULT_MAX_PARALLEL_READ_TASKS),
            "auto_approve_read_only_plans": _truthy(overrides.get("auto_approve_read_only_plans"), True),
            "no_progress_watchdog_enabled": _truthy(overrides.get("no_progress_watchdog_enabled"), True),
            "max_no_progress_cycles": int(overrides.get("max_no_progress_cycles", self._DEFAULT_MAX_NO_PROGRESS_CYCLES) or self._DEFAULT_MAX_NO_PROGRESS_CYCLES),
            "_no_progress_signature": "",
            "_no_progress_repeats": 0,
            "_no_progress_effective_steps": -1,
            "_no_progress_completed_plan_steps": -1,
            "_stalled_replan_attempted": False,
            "active_agent_task": "",
            "pending_user_question": "",
            "pending_user_input_kind": "",
            "approval_pending_scope": "",
            "approval_request": {},
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
            "deep_research_mode": False,
            "deep_research_tier": 0,
            "deep_research_confirmed": False,
            "deep_research_analysis": {},
            "deep_research_intent": {},
            "deep_research_source_strategy": {},
            "deep_research_execution_plan": {},
            "deep_research_result_card": {},
            "artifact_files": [],
            "artifact_lookup_run_id": "",
            "artifact_lookup_workflow_id": "",
            "artifact_lookup_run_output_dir": "",
            "deep_research_source_urls": [],
            "workflow_type": "",
            "multi_model_enabled": _truthy(overrides.get("multi_model_enabled"), False),
            "multi_model_strategy": str(overrides.get("multi_model_strategy", "best") or "best").strip().lower() or "best",
            "multi_model_stage_overrides": {},
            "multi_model_recommendations": {},
            "multi_model_active_workflow": "",
            "multi_model_plan": {},
            "research_output_formats": ["pdf", "docx", "html", "md"],
            "research_citation_style": "apa",
            "research_enable_plagiarism_check": True,
            "research_web_search_enabled": True,
            "research_search_backend": "auto",
            "research_date_range": "all_time",
            "research_max_sources": 0,
            "research_checkpoint_enabled": False,
            "research_kb_enabled": False,
            "research_kb_id": "",
            "research_kb_top_k": 8,
            "long_document_compiled_path": "",
            "long_document_compiled_html_path": "",
            "long_document_compiled_docx_path": "",
            "long_document_compiled_pdf_path": "",
            "long_document_exports": [],
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
            "review_pending_reason": "",
            "review_subject_step_id": "",
            "review_subject_agent": "",
            "review_revision_counts": {},
            "direct_tool_loop_attempted": False,
            "direct_tool_trace": [],
            "direct_tool_last_result": {},
            "direct_tool_fallback_reason": "",
            "direct_tool_native_fallback_reason": "",
            "adaptive_agent_selection": _truthy(overrides.get("adaptive_agent_selection"), True),
            "execution_mode": str(overrides.get("execution_mode", "adaptive") or "adaptive").strip().lower() or "adaptive",
            "planner_policy_mode": str(
                overrides.get("planner_policy_mode", overrides.get("planner_mode", "adaptive")) or "adaptive"
            ).strip().lower() or "adaptive",
            "reviewer_policy_mode": str(
                overrides.get("reviewer_policy_mode", overrides.get("reviewer_mode", "adaptive")) or "adaptive"
            ).strip().lower() or "adaptive",
            "planner_score_threshold": int(overrides.get("planner_score_threshold", 4) or 4),
            "reviewer_score_threshold": int(overrides.get("reviewer_score_threshold", 5) or 5),
            "planner_policy_last": {},
            "review_policy_last": {},
            "enforce_quality_gate": bool(overrides.get("enforce_quality_gate", True)),
            "quality_gate_passed": False,
            "quality_gate_report": "",
            "github_write_authorized": _truthy(overrides.get("github_write_authorized"), False),
            "github_local_git_authorized": _truthy(overrides.get("github_local_git_authorized"), False),
            "github_remote_git_authorized": _truthy(overrides.get("github_remote_git_authorized"), False),
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
            "communication_authorized": communication_authorized,
            "local_drive_auto_generate_extension_handlers": False,
            "local_drive_unknown_extensions": [],
            "local_drive_handler_registry": {},
            "local_drive_handler_routes": {},
            "extension_handler_generation_requested": False,
            "extension_handler_generation_dispatched": False,
            "extension_handler_generation_signature": "",
            "agent_factory_request": "",
            # Project context (kendr.md)
            "project_context_md": "",
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
            "software_inventory": {},
            "software_inventory_last_synced": "",
            "software_inventory_stale": True,
            "file_index_last_synced": "",
            "indexed_files": 0,
            "recent_file_changes_24h": 0,
            "machine_sync_stale": True,
        }
        initial_state.update(overrides)
        working_directory = str(initial_state.get("working_directory", "") or "").strip()
        if working_directory:
            inventory_snapshot = load_inventory_snapshot(working_directory)
            initial_state["software_inventory"] = dict(inventory_snapshot.get("software", {}) or {})
            initial_state["software_inventory_last_synced"] = str(inventory_snapshot.get("last_synced_at", "") or "")
            initial_state["software_inventory_stale"] = is_inventory_stale(inventory_snapshot)
            sync_status = machine_sync_status(working_directory)
            initial_state["file_index_last_synced"] = str(sync_status.get("file_index_last_synced", "") or "")
            initial_state["indexed_files"] = int(sync_status.get("indexed_files", 0) or 0)
            initial_state["recent_file_changes_24h"] = int(sync_status.get("recent_changes_24h", 0) or 0)
            file_last = str(sync_status.get("file_index_last_synced", "") or "")
            if file_last:
                try:
                    file_last_dt = datetime.fromisoformat(file_last.replace("Z", "+00:00"))
                    if file_last_dt.tzinfo is None:
                        file_last_dt = file_last_dt.replace(tzinfo=timezone.utc)
                    initial_state["machine_sync_stale"] = (
                        datetime.now(timezone.utc) - file_last_dt
                    ) > timedelta(days=7)
                except Exception:
                    initial_state["machine_sync_stale"] = True
            else:
                initial_state["machine_sync_stale"] = True
        initial_state["adaptive_agent_selection"] = _truthy(initial_state.get("adaptive_agent_selection"), True)
        initial_state["planner_policy_mode"] = self._resolve_policy_mode(
            initial_state,
            primary_key="planner_policy_mode",
            aliases=("planner_mode",),
            default="adaptive",
        )
        initial_state["execution_mode"] = self._resolve_execution_mode(initial_state, default="adaptive")
        if initial_state["execution_mode"] == "direct_tools":
            initial_state["planner_policy_mode"] = "never"
        elif initial_state["execution_mode"] == "plan":
            initial_state["planner_policy_mode"] = "always"
        initial_state["reviewer_policy_mode"] = self._resolve_policy_mode(
            initial_state,
            primary_key="reviewer_policy_mode",
            aliases=("reviewer_mode",),
            default="adaptive",
        )
        initial_state["planner_score_threshold"] = max(1, int(initial_state.get("planner_score_threshold", 4) or 4))
        initial_state["reviewer_score_threshold"] = max(1, int(initial_state.get("reviewer_score_threshold", 5) or 5))
        prior_channel_session = initial_state.get("channel_session", {})
        prior_channel_state = prior_channel_session.get("state", {}) if isinstance(prior_channel_session, dict) else {}
        resume_requested = self._looks_like_resume_request(user_query)
        has_pending_session_input = state_awaiting_user_input(prior_channel_state) if isinstance(prior_channel_state, dict) else False
        reuse_session_plan = resume_requested or has_pending_session_input
        if isinstance(prior_channel_state, dict):
            if "adaptive_agent_selection" not in overrides and "adaptive_agent_selection" in prior_channel_state:
                initial_state["adaptive_agent_selection"] = _truthy(
                    prior_channel_state.get("adaptive_agent_selection"),
                    bool(initial_state.get("adaptive_agent_selection", True)),
                )
            if "planner_policy_mode" not in overrides and "planner_mode" not in overrides:
                persisted_planner_mode = str(
                    prior_channel_state.get("planner_policy_mode", prior_channel_state.get("planner_mode", ""))
                    or ""
                ).strip().lower()
                if persisted_planner_mode:
                    initial_state["planner_policy_mode"] = persisted_planner_mode
            if "execution_mode" not in overrides:
                persisted_execution_mode = str(prior_channel_state.get("execution_mode", "") or "").strip().lower()
                if persisted_execution_mode:
                    initial_state["execution_mode"] = persisted_execution_mode
            if "reviewer_policy_mode" not in overrides and "reviewer_mode" not in overrides:
                persisted_reviewer_mode = str(
                    prior_channel_state.get("reviewer_policy_mode", prior_channel_state.get("reviewer_mode", ""))
                    or ""
                ).strip().lower()
                if persisted_reviewer_mode:
                    initial_state["reviewer_policy_mode"] = persisted_reviewer_mode
            if "planner_score_threshold" not in overrides and prior_channel_state.get("planner_score_threshold") is not None:
                initial_state["planner_score_threshold"] = int(prior_channel_state.get("planner_score_threshold", 4) or 4)
            if "reviewer_score_threshold" not in overrides and prior_channel_state.get("reviewer_score_threshold") is not None:
                initial_state["reviewer_score_threshold"] = int(prior_channel_state.get("reviewer_score_threshold", 5) or 5)
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
                initial_state["orchestration_plan_id"] = str(prior_channel_state.get("orchestration_plan_id", "") or "")
                initial_state["orchestration_plan_version"] = int(
                    prior_channel_state.get("orchestration_plan_version", initial_state.get("orchestration_plan_version", 0))
                    or initial_state.get("orchestration_plan_version", 0)
                    or 0
                )
                initial_state["intent_signature"] = str(prior_channel_state.get("intent_signature", "") or "")
                initial_state["selected_intent_id"] = str(prior_channel_state.get("selected_intent_id", "") or "")
                initial_state["selected_intent_type"] = str(prior_channel_state.get("selected_intent_type", "") or "")
                initial_state["selected_intent"] = (
                    prior_channel_state.get("selected_intent", {})
                    if isinstance(prior_channel_state.get("selected_intent", {}), dict)
                    else {}
                )
                initial_state["intent_candidates"] = (
                    prior_channel_state.get("intent_candidates", [])
                    if isinstance(prior_channel_state.get("intent_candidates", []), list)
                    else []
                )
                initial_state["planning_notes"] = prior_channel_state.get("planning_notes", [])
                initial_state["review_revision_counts"] = prior_channel_state.get("review_revision_counts", {})
                initial_state["pending_user_input_kind"] = str(prior_channel_state.get("pending_user_input_kind", "") or "")
                initial_state["approval_pending_scope"] = str(prior_channel_state.get("approval_pending_scope", "") or "")
                initial_state["pending_user_question"] = str(prior_channel_state.get("pending_user_question", "") or "")
                initial_state["approval_request"] = normalize_approval_request(prior_channel_state.get("approval_request", {}))
                initial_state["long_document_plan_waiting_for_approval"] = bool(prior_channel_state.get("long_document_plan_waiting_for_approval", False))
                initial_state["long_document_plan_status"] = str(prior_channel_state.get("long_document_plan_status", "") or "")
                initial_state["long_document_plan_feedback"] = str(prior_channel_state.get("long_document_plan_feedback", "") or "")
                initial_state["long_document_plan_revision_count"] = int(prior_channel_state.get("long_document_plan_revision_count", 0) or 0)
                initial_state["long_document_plan_markdown"] = str(prior_channel_state.get("long_document_plan_markdown", "") or "")
                initial_state["long_document_plan_data"] = prior_channel_state.get("long_document_plan_data", {})
                initial_state["long_document_plan_version"] = int(prior_channel_state.get("long_document_plan_version", 0) or 0)
                initial_state["deep_research_mode"] = bool(prior_channel_state.get("deep_research_mode", False))
                initial_state["deep_research_tier"] = int(prior_channel_state.get("deep_research_tier", 0) or 0)
                initial_state["deep_research_confirmed"] = bool(prior_channel_state.get("deep_research_confirmed", False))
                initial_state["deep_research_analysis"] = prior_channel_state.get("deep_research_analysis", {})
                initial_state["deep_research_intent"] = (
                    prior_channel_state.get("deep_research_intent", {})
                    if isinstance(prior_channel_state.get("deep_research_intent", {}), dict)
                    else {}
                )
                initial_state["deep_research_source_strategy"] = (
                    prior_channel_state.get("deep_research_source_strategy", {})
                    if isinstance(prior_channel_state.get("deep_research_source_strategy", {}), dict)
                    else {}
                )
                initial_state["deep_research_execution_plan"] = (
                    prior_channel_state.get("deep_research_execution_plan", {})
                    if isinstance(prior_channel_state.get("deep_research_execution_plan", {}), dict)
                    else {}
                )
                initial_state["deep_research_result_card"] = prior_channel_state.get("deep_research_result_card", {})
                initial_state["deep_research_source_urls"] = list(prior_channel_state.get("deep_research_source_urls", []) or [])
                initial_state["research_output_formats"] = list(prior_channel_state.get("research_output_formats", initial_state.get("research_output_formats", [])) or initial_state.get("research_output_formats", []))
                initial_state["research_citation_style"] = str(prior_channel_state.get("research_citation_style", initial_state.get("research_citation_style", "")) or initial_state.get("research_citation_style", ""))
                initial_state["research_enable_plagiarism_check"] = bool(prior_channel_state.get("research_enable_plagiarism_check", initial_state.get("research_enable_plagiarism_check", True)))
                initial_state["research_web_search_enabled"] = bool(prior_channel_state.get("research_web_search_enabled", initial_state.get("research_web_search_enabled", True)))
                initial_state["research_search_backend"] = str(prior_channel_state.get("research_search_backend", initial_state.get("research_search_backend", "")) or initial_state.get("research_search_backend", ""))
                initial_state["research_date_range"] = str(prior_channel_state.get("research_date_range", initial_state.get("research_date_range", "")) or initial_state.get("research_date_range", ""))
                initial_state["research_max_sources"] = int(prior_channel_state.get("research_max_sources", 0) or 0)
                initial_state["research_checkpoint_enabled"] = bool(prior_channel_state.get("research_checkpoint_enabled", False))
                initial_state["research_kb_enabled"] = bool(prior_channel_state.get("research_kb_enabled", initial_state.get("research_kb_enabled", False)))
                initial_state["research_kb_id"] = str(prior_channel_state.get("research_kb_id", initial_state.get("research_kb_id", "")) or initial_state.get("research_kb_id", ""))
                initial_state["research_kb_top_k"] = int(prior_channel_state.get("research_kb_top_k", initial_state.get("research_kb_top_k", 8)) or initial_state.get("research_kb_top_k", 8))
                initial_state["workflow_type"] = str(prior_channel_state.get("workflow_type", initial_state.get("workflow_type", "")) or initial_state.get("workflow_type", ""))
                if "multi_model_enabled" not in overrides:
                    initial_state["multi_model_enabled"] = bool(prior_channel_state.get("multi_model_enabled", initial_state.get("multi_model_enabled", False)))
                if "multi_model_strategy" not in overrides:
                    initial_state["multi_model_strategy"] = str(
                        prior_channel_state.get("multi_model_strategy", initial_state.get("multi_model_strategy", "best"))
                        or initial_state.get("multi_model_strategy", "best")
                    ).strip().lower() or "best"
                if "multi_model_stage_overrides" not in overrides:
                    prior_stage_overrides = prior_channel_state.get("multi_model_stage_overrides", {})
                    initial_state["multi_model_stage_overrides"] = (
                        dict(prior_stage_overrides)
                        if isinstance(prior_stage_overrides, dict)
                        else {}
                    )
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
            if prior_channel_state.get("deep_research_result_card"):
                initial_state["deep_research_result_card"] = (
                    prior_channel_state.get("deep_research_result_card", {})
                    if isinstance(prior_channel_state.get("deep_research_result_card", {}), dict)
                    else {}
                )
            if prior_channel_state.get("artifact_files"):
                initial_state["artifact_files"] = (
                    prior_channel_state.get("artifact_files", [])
                    if isinstance(prior_channel_state.get("artifact_files", []), list)
                    else []
                )
            if prior_channel_state.get("long_document_exports"):
                initial_state["long_document_exports"] = (
                    prior_channel_state.get("long_document_exports", [])
                    if isinstance(prior_channel_state.get("long_document_exports", []), list)
                    else []
                )
            for key in (
                "long_document_compiled_path",
                "long_document_compiled_html_path",
                "long_document_compiled_docx_path",
                "long_document_compiled_pdf_path",
            ):
                if prior_channel_state.get(key):
                    initial_state[key] = str(prior_channel_state.get(key, "") or "")
            if prior_channel_state.get("last_report_run_id"):
                initial_state["artifact_lookup_run_id"] = str(prior_channel_state.get("last_report_run_id", "") or "")
            elif prior_channel_state.get("last_run_id"):
                initial_state["artifact_lookup_run_id"] = str(prior_channel_state.get("last_run_id", "") or "")
            if prior_channel_state.get("last_report_workflow_id"):
                initial_state["artifact_lookup_workflow_id"] = str(prior_channel_state.get("last_report_workflow_id", "") or "")
            elif prior_channel_state.get("last_workflow_id"):
                initial_state["artifact_lookup_workflow_id"] = str(prior_channel_state.get("last_workflow_id", "") or "")
            if prior_channel_state.get("last_report_run_output_dir"):
                initial_state["artifact_lookup_run_output_dir"] = str(prior_channel_state.get("last_report_run_output_dir", "") or "")
            elif prior_channel_state.get("run_output_dir"):
                initial_state["artifact_lookup_run_output_dir"] = str(prior_channel_state.get("run_output_dir", "") or "")
            if prior_channel_state.get("session_id"):
                initial_state["session_id"] = str(prior_channel_state.get("session_id", "") or "").strip() or initial_state.get("session_id", "")
            if prior_channel_state.get("superrag_active_session_id"):
                initial_state["superrag_active_session_id"] = str(prior_channel_state.get("superrag_active_session_id", "")).strip()
            if prior_channel_state.get("last_objective"):
                initial_state["session_previous_objective"] = str(prior_channel_state.get("last_objective", ""))
            if prior_channel_state.get("chat_history_messages"):
                initial_state["session_history"] = prior_channel_state.get("chat_history_messages", [])
            elif prior_channel_state.get("history"):
                initial_state["session_history"] = prior_channel_state.get("history", [])
            if prior_channel_state.get("chat_summary_text"):
                initial_state["session_history_summary"] = str(prior_channel_state.get("chat_summary_text", "") or "")
            if prior_channel_state.get("chat_summary_file"):
                initial_state["session_history_summary_file"] = str(prior_channel_state.get("chat_summary_file", "") or "")
            if prior_channel_state.get("failure_checkpoint"):
                initial_state["failure_checkpoint"] = prior_channel_state.get("failure_checkpoint", {})
            if state_awaiting_user_input(prior_channel_state):
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
        initial_state["adaptive_agent_selection"] = _truthy(initial_state.get("adaptive_agent_selection"), True)
        initial_state["planner_policy_mode"] = self._resolve_policy_mode(
            initial_state,
            primary_key="planner_policy_mode",
            aliases=("planner_mode",),
            default="adaptive",
        )
        initial_state["execution_mode"] = self._resolve_execution_mode(initial_state, default="adaptive")
        if initial_state["execution_mode"] == "direct_tools":
            initial_state["planner_policy_mode"] = "never"
        elif initial_state["execution_mode"] == "plan":
            initial_state["planner_policy_mode"] = "always"
        initial_state["reviewer_policy_mode"] = self._resolve_policy_mode(
            initial_state,
            primary_key="reviewer_policy_mode",
            aliases=("reviewer_mode",),
            default="adaptive",
        )
        initial_state["planner_score_threshold"] = max(1, int(initial_state.get("planner_score_threshold", 4) or 4))
        initial_state["reviewer_score_threshold"] = max(1, int(initial_state.get("reviewer_score_threshold", 5) or 5))
        resume_checkpoint_payload = initial_state.get("resume_checkpoint_payload", {})
        if isinstance(resume_checkpoint_payload, dict) and resume_checkpoint_payload:
            self._restore_from_resume_checkpoint(initial_state, resume_checkpoint_payload, user_query)
        initial_state["adaptive_agent_selection"] = _truthy(initial_state.get("adaptive_agent_selection"), True)
        initial_state["planner_policy_mode"] = self._resolve_policy_mode(
            initial_state,
            primary_key="planner_policy_mode",
            aliases=("planner_mode",),
            default="adaptive",
        )
        initial_state["execution_mode"] = self._resolve_execution_mode(initial_state, default="adaptive")
        if initial_state["execution_mode"] == "direct_tools":
            initial_state["planner_policy_mode"] = "never"
        elif initial_state["execution_mode"] == "plan":
            initial_state["planner_policy_mode"] = "always"
        initial_state["reviewer_policy_mode"] = self._resolve_policy_mode(
            initial_state,
            primary_key="reviewer_policy_mode",
            aliases=("reviewer_mode",),
            default="adaptive",
        )
        initial_state["planner_score_threshold"] = max(1, int(initial_state.get("planner_score_threshold", 4) or 4))
        initial_state["reviewer_score_threshold"] = max(1, int(initial_state.get("reviewer_score_threshold", 5) or 5))
        initial_state = self.apply_runtime_setup(initial_state)
        if initial_state.get("plan_steps"):
            self._refresh_plan_readiness(initial_state, persist=False)
            self._next_planned_agents(initial_state, ignore_active=True)
        initial_state["privileged_policy"] = build_privileged_policy(initial_state)
        # Inject project context (kendr.md) for every session with a project root
        project_root = str(initial_state.get("project_root", "")).strip()
        if project_root:
            try:
                from kendr.project_context import get_project_context_blob
                project_name = str(initial_state.get("project_name", "")).strip()
                ctx = get_project_context_blob(project_root, project_name)
                if ctx:
                    initial_state["project_context_md"] = ctx
            except Exception:
                pass
        # Repo scan: run for audit/codebase requests, or whenever project_root is set
        do_scan = (
            self._is_project_audit_request(initial_state)
            or bool(initial_state.get("codebase_mode", False))
            or bool(project_root)
        )
        self._ensure_workflow_type(initial_state)
        if self._use_deep_research_capability_profile(initial_state):
            initial_state = self._apply_deep_research_capability_profile(initial_state)
        self._prime_multi_model_plan(initial_state)
        if do_scan:
            try:
                scan_dir = project_root or str(initial_state.get("working_directory", "")).strip()
                if scan_dir:
                    initial_state["repo_scan_summary"] = self._build_repo_scan_summary(scan_dir)
            except Exception as exc:
                initial_state["repo_scan_summary"] = f"Repository scan failed: {exc}"
        ensure_a2a_state(initial_state, initial_state.get("available_agent_cards") or self._agent_cards())
        initial_state = bootstrap_file_memory(initial_state)
        self._prime_deep_research_plan(initial_state, record_trace=True)
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

    def _refresh_skill_agents(self) -> None:
        """Refresh skill-backed agents from the current database state.

        Called at the start of each run_query so skills installed after
        gateway startup are available for routing without a restart.
        """
        try:
            from kendr.discovery import _register_skill_agents
            from kendr.agent_routing import build_agent_routing_index as _build_ar
            # Remove stale skill agents and plugin entry
            for name in list(self.registry.agents.keys()):
                if name.startswith("skill_") and name.endswith("_agent"):
                    del self.registry.agents[name]
            self.registry.plugins.pop("builtin.skills", None)
            # Re-register from current DB state
            _register_skill_agents(self.registry)
            # Rebuild routing index so new agents are routable
            self.agent_routing = _build_ar(self.registry)
        except Exception:
            pass

    def _refresh_mcp_agents(self) -> None:
        """Refresh MCP-backed agents from the current database state.

        Called at the start of each run_query so servers added or discovered
        after gateway startup are available for routing without a restart.
        Also triggers a background tool-discovery pass for any enabled server
        that has never had its tools fetched (last_discovered is empty).
        """
        # Background-discover any server whose tools have never been fetched.
        # This fires-and-forgets so it doesn't block the current run; the *next*
        # run will pick up the newly saved tools via the re-registration below.
        try:
            from kendr.mcp_manager import list_servers as _mcp_list_servers, discover_tools as _mcp_discover
            _undiscovered = [
                s for s in _mcp_list_servers()
                if s.get("enabled", True) and not str(s.get("last_discovered") or "").strip()
            ]
            if _undiscovered:
                import threading as _threading
                def _discover_bg():
                    for _s in _undiscovered:
                        try:
                            _mcp_discover(str(_s.get("id", "")))
                        except Exception:
                            pass
                _threading.Thread(target=_discover_bg, daemon=True).start()
        except Exception:
            pass

        try:
            from kendr.discovery import _register_mcp_tools
            from kendr.agent_routing import build_agent_routing_index as _build_ar
            # Remove stale MCP agents and plugin entry
            for name in list(self.registry.agents.keys()):
                if name.startswith("mcp_"):
                    del self.registry.agents[name]
            self.registry.plugins.pop("builtin.mcp", None)
            # Re-register from current DB state
            _register_mcp_tools(self.registry)
            # Rebuild routing index so new agents are routable
            self.agent_routing = _build_ar(self.registry)
        except Exception:
            pass

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
            workflow_id=str(overrides.get("workflow_id", "")).strip() or run_id,
            attempt_id=str(overrides.get("attempt_id", "")).strip() or run_id,
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
        initial_state_overrides["workflow_id"] = str(overrides.get("workflow_id", "")).strip() or run_id
        initial_state_overrides["attempt_id"] = str(overrides.get("attempt_id", "")).strip() or run_id
        initial_state_overrides["run_output_dir"] = run_output_dir
        initial_state_overrides["working_directory"] = working_directory
        initial_state = self.build_initial_state(
            user_query,
            **initial_state_overrides,
        )
        self._record_orchestration_event(
            initial_state,
            event_type="run.started",
            subject_type="run",
            subject_id=run_id,
            status="running",
            payload={"user_query": user_query},
        )
        if self._kill_switch_triggered(initial_state):
            raise RuntimeError("Kill switch triggered. Remove kill-switch file to continue.")
        if not self._is_agent_available(initial_state, "worker_agent"):
            raise RuntimeError("Core LLM setup is incomplete. Configure at least one ready provider and model before the agent system can run.")
        initial_state = append_message(initial_state, make_message("user", "orchestrator_agent", "request", user_query))
        record_work_note(initial_state, "user", "request", user_query)
        append_daily_memory_note(initial_state, "user", "request", user_query)
        self._write_session_record(initial_state, status="running")
        provider_override = str(initial_state.get("provider") or "").strip().lower()
        model_override = str(initial_state.get("model") or "").strip()
        self._refresh_mcp_agents()
        self._refresh_skill_agents()
        try:
            with runtime_model_override(provider_override, model_override):
                app = self.build_workflow()
                self.save_graph(app)
                result = app.invoke(initial_state)
            _fo_raw = result.get("final_output") or result.get("draft_response", "")
            final_output = _fo_raw if isinstance(_fo_raw, str) else (
                "\n".join(
                    (b.get("text", "") if isinstance(b, dict) else str(b))
                    for b in _fo_raw
                ) if isinstance(_fo_raw, list) else str(_fo_raw or "")
            )
            final_output = self._with_execution_surface_note(final_output, result)
            result["final_output"] = final_output
            if create_outputs:
                write_text_file(str(Path(run_output_dir) / "final_output.txt"), final_output)
            completed_at = datetime.now(timezone.utc).isoformat()
            final_status = "awaiting_user_input" if self._awaiting_user_input(result) else "completed"
            result = self._sync_orchestration_plan_record(result, final_status=final_status if final_status != "awaiting_user_input" else "")
            update_run(run_id, status=final_status, completed_at=completed_at, final_output=final_output)
            self._record_orchestration_event(
                result,
                event_type=f"run.{final_status}",
                subject_type="run",
                subject_id=run_id,
                status=final_status,
                payload={"final_output_excerpt": self._truncate(final_output, 240)},
            )
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
        except Exception as exc:
            error_text = str(initial_state.get("last_error", "") or str(exc) or "")
            cancelled = bool(initial_state.get("user_cancelled", False)) or "kill switch triggered" in error_text.lower()
            final_status = "cancelled" if cancelled else "failed"
            final_output = "Run stopped by user." if cancelled else "workflow failed"
            completed_at = datetime.now(timezone.utc).isoformat()
            initial_state = self._sync_orchestration_plan_record(initial_state, final_status=final_status)
            update_run(run_id, status=final_status, completed_at=completed_at, final_output=final_output)
            self._record_orchestration_event(
                initial_state,
                event_type=f"run.{final_status}",
                subject_type="run",
                subject_id=run_id,
                status=final_status,
                payload={"error": self._truncate(error_text or final_output, 240)},
            )
            if not initial_state.get("failure_checkpoint"):
                fallback_error = initial_state.get("last_error", "workflow failed")
                initial_state["failure_checkpoint"] = self._build_failure_checkpoint(
                    initial_state,
                    agent_name=initial_state.get("last_agent", "runtime"),
                    error_message=fallback_error,
                    active_task=initial_state.get("active_task"),
                )
            append_daily_memory_note(
                initial_state,
                "system",
                "run_cancelled" if cancelled else "run_failed",
                initial_state.get("last_error", final_output),
            )
            self._write_session_record(initial_state, status=final_status, completed_at=completed_at)
            update_planning_file(
                initial_state,
                status=final_status,
                objective=initial_state.get("current_objective", initial_state.get("user_query", "")),
                plan_text=initial_state.get("plan", ""),
                clarifications=initial_state.get("plan_clarification_questions", []),
                execution_note=(
                    "Run stopped by user."
                    if cancelled
                    else f"Run failed: {initial_state.get('last_error', 'workflow failed')}"
                ),
            )
            close_session_memory(initial_state, status=final_status, final_output=initial_state.get("last_error", final_output))
            append_privileged_audit_event(
                initial_state,
                actor="runtime",
                action="run_cancelled" if cancelled else "run_failed",
                status="ok" if cancelled else "error",
                detail={"run_id": run_id, "error": initial_state.get("last_error", final_output)},
            )
            raise
        finally:
            set_active_output_dir(OUTPUT_DIR)
