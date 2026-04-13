from __future__ import annotations

import json
import os
import re
import shlex
import time
import uuid
from collections.abc import Mapping
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from langgraph.graph import END, StateGraph
from kendr.approval_resume_handlers import restore_pending_user_input
from kendr.orchestration import ResumeStateOverrides, RuntimeState, state_awaiting_user_input
from kendr.execution_trace import append_execution_event, render_execution_event_line
from kendr.direct_tools import run_direct_tool_loop
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
from kendr.path_utils import normalize_host_path_str
from kendr.machine_index import machine_sync_status
from kendr.software_inventory import is_inventory_stale, load_inventory_snapshot
from kendr.setup import build_setup_snapshot
from kendr.agent_routing import build_agent_routing_index, AgentRoutingIndex
from kendr.workflow_contract import is_deep_research_workflow_type, normalize_approval_request
from kendr.workflow_execution_policies import dispatch_workflow_execution_policies
from kendr.workflow_registry import WorkflowDispatchPlan

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
    runtime_model_override,
    set_active_output_dir,
    write_text_file,
)
from .recovery import write_recovery_files

from .registry import Registry


def _truthy(value: Any, default: bool = False) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


class AgentRuntime:
    def __init__(self, registry: Registry):
        self.registry = registry
        self.agent_routing: AgentRoutingIndex = build_agent_routing_index(registry)
        self._live_plan_data: dict = {}
        _ar_summary = self.agent_routing.summary()
        print(
            f"[kendr] Agent routing index ready: "
            f"{_ar_summary['active']} active / {_ar_summary['total']} total agents across "
            f"{len(_ar_summary.get('by_category', {}))} categories."
        )

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
        ensure_a2a_state(state, filtered_cards)
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
        quick_summary_markers = (
            "quick summary",
            "summary only",
            "brief summary",
            "just summarize",
            "quick answer",
        )
        cleaned = lowered.strip(" \n\t.!?")
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
        if run_id:
            insert_agent_execution(
                run_id,
                timestamp,
                agent_name,
                status,
                reason,
                self._truncate(output_text),
                completed_at=completed_at,
            )
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

    def _mark_planned_step_complete(self, state: dict, result_text: str = "") -> None:
        from datetime import datetime, timezone
        current_index = int(state.get("plan_step_index", 0) or 0)
        completed_index = current_index + 1
        total_steps = len(state.get("plan_steps", []) or [])
        completed_title = (
            state.get("last_completed_plan_step_title")
            or state.get("planned_active_step_title")
            or state.get("current_plan_step_title")
            or state.get("planned_active_step_id")
            or "planned step"
        )
        steps = state.get("plan_steps")
        if isinstance(steps, list) and 0 <= current_index < len(steps):
            step = steps[current_index]
            if isinstance(step, dict):
                step["status"] = "completed"
                step["completed_at"] = datetime.now(timezone.utc).isoformat()
                if result_text:
                    step["result_summary"] = result_text[:300]
                step["error"] = None
            state["plan_steps"] = steps
        self._flush_live_plan(state)
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

    def _mark_step_failed(self, state: dict, step_index: int, error_message: str) -> None:
        from datetime import datetime, timezone
        steps = state.get("plan_steps")
        if not isinstance(steps, list) or step_index < 0 or step_index >= len(steps):
            return
        step = steps[step_index]
        if not isinstance(step, dict):
            return
        step["status"] = "failed"
        step["completed_at"] = datetime.now(timezone.utc).isoformat()
        step["error"] = error_message[:300]
        state["plan_steps"] = steps
        self._flush_live_plan(state)

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
            state["review_pending_reason"] = ""
            state["failure_checkpoint"] = self._build_failure_checkpoint(state, agent_name, unavailable_reason, state.get("active_task"))
            return self._append_history(state, agent_name, "skipped", state.get("orchestrator_reason", ""), unavailable_reason)

        spec = self.registry.agents[agent_name]
        log_task_update("System", f"Dispatching to {agent_name}.")
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
            with agent_model_context(agent_name):
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
            try:
                from kendr.cli_output import step_done as _cli_step_done
                _cli_step_done(agent_name, duration=_agent_elapsed)
            except Exception:
                pass
            append_daily_memory_note(state, agent_name, "completed", self._truncate(output_text, 1000))
            append_session_event(state, agent_name, "completed", self._truncate(output_text, 600))
            if agent_name == str(state.get("planned_active_agent", "")).strip():
                state["last_completed_plan_step_id"] = str(state.get("planned_active_step_id", "")).strip()
                state["last_completed_plan_step_title"] = str(state.get("planned_active_step_title", "")).strip()
                state["last_completed_plan_step_success_criteria"] = str(state.get("planned_active_step_success_criteria", "")).strip()
                state["last_completed_plan_step_agent"] = str(agent_name).strip()
                if not hold_step_completion:
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
            if agent_name == str(state.get("planned_active_agent", "")).strip():
                self._mark_step_failed(state, int(state.get("plan_step_index", 0) or 0), error_message)
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
            try:
                from kendr.cli_output import step_error as _cli_step_error
                _cli_step_error(agent_name, error_message)
            except Exception:
                pass
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

        prompt = f"""
You are the orchestration agent for a plugin-driven multi-agent AI system.

Your job is to decide which agent should run next, or whether the workflow should finish.
Choose from exactly these currently available agents:
{json.dumps(self._available_agent_descriptions(state), indent=2)}

Policy-gated agents for this turn (treat as unavailable):
{json.dumps(state.get("_policy_blocked_agents", []), ensure_ascii=False)}

Rules:
- Only choose agents that appear in the available-agent list above.
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
{direct_tool_rule}

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

{state.get("connector_catalog_prompt", "")}

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

Recent user/assistant chat history:
{self._session_history_as_text(state)}

Return ONLY valid JSON in this exact schema:
{{
  "agent": "{self._agent_enum(state, include_finish=True)}",
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
                with agent_model_context("orchestrator_agent"):
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
        restore_pending_user_input(self, initial_state, prior_channel_state, user_query)

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
            "deep_research_result_card": {},
            "deep_research_source_urls": [],
            "workflow_type": "",
            "research_output_formats": ["pdf", "docx", "html", "md"],
            "research_citation_style": "apa",
            "research_enable_plagiarism_check": True,
            "research_web_search_enabled": True,
            "research_date_range": "all_time",
            "research_max_sources": 0,
            "research_checkpoint_enabled": False,
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
                initial_state["deep_research_result_card"] = prior_channel_state.get("deep_research_result_card", {})
                initial_state["deep_research_source_urls"] = list(prior_channel_state.get("deep_research_source_urls", []) or [])
                initial_state["research_output_formats"] = list(prior_channel_state.get("research_output_formats", initial_state.get("research_output_formats", [])) or initial_state.get("research_output_formats", []))
                initial_state["research_citation_style"] = str(prior_channel_state.get("research_citation_style", initial_state.get("research_citation_style", "")) or initial_state.get("research_citation_style", ""))
                initial_state["research_enable_plagiarism_check"] = bool(prior_channel_state.get("research_enable_plagiarism_check", initial_state.get("research_enable_plagiarism_check", True)))
                initial_state["research_web_search_enabled"] = bool(prior_channel_state.get("research_web_search_enabled", initial_state.get("research_web_search_enabled", True)))
                initial_state["research_date_range"] = str(prior_channel_state.get("research_date_range", initial_state.get("research_date_range", "")) or initial_state.get("research_date_range", ""))
                initial_state["research_max_sources"] = int(prior_channel_state.get("research_max_sources", 0) or 0)
                initial_state["research_checkpoint_enabled"] = bool(prior_channel_state.get("research_checkpoint_enabled", False))
                initial_state["workflow_type"] = str(prior_channel_state.get("workflow_type", initial_state.get("workflow_type", "")) or initial_state.get("workflow_type", ""))
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
        if do_scan:
            try:
                scan_dir = project_root or str(initial_state.get("working_directory", "")).strip()
                if scan_dir:
                    initial_state["repo_scan_summary"] = self._build_repo_scan_summary(scan_dir)
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
        if self._kill_switch_triggered(initial_state):
            raise RuntimeError("Kill switch triggered. Remove kill-switch file to continue.")
        if not self._is_agent_available(initial_state, "worker_agent"):
            raise RuntimeError("Core LLM setup is incomplete. OPENAI_API_KEY is required before the agent system can run.")
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
        except Exception as exc:
            error_text = str(initial_state.get("last_error", "") or str(exc) or "")
            cancelled = bool(initial_state.get("user_cancelled", False)) or "kill switch triggered" in error_text.lower()
            final_status = "cancelled" if cancelled else "failed"
            final_output = "Run stopped by user." if cancelled else "workflow failed"
            completed_at = datetime.now(timezone.utc).isoformat()
            update_run(run_id, status=final_status, completed_at=completed_at, final_output=final_output)
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
