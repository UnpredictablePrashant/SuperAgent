from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from kendr.orchestration import state_awaiting_user_input
from kendr.workflow_contract import approval_request_to_text, normalize_approval_request
from kendr.workflow_registry import match_explicit_workflow

from tasks.a2a_protocol import append_message, append_task, make_message, make_task
from tasks.file_memory import update_planning_file
from tasks.utils import log_task_update, record_work_note


@dataclass(slots=True)
class WorkflowPolicyContext:
    current_objective: str
    in_task_phase: bool


def dispatch_workflow_execution_policies(
    runtime: Any,
    state: dict[str, Any],
    *,
    current_objective: str,
    in_task_phase: bool,
) -> dict[str, Any] | None:
    context = WorkflowPolicyContext(
        current_objective=current_objective,
        in_task_phase=in_task_phase,
    )
    handlers = (
        _handle_channel_bootstrap,
        _handle_pending_user_input_gate,
        _handle_resume_workflow_dispatch,
        _handle_review_flow,
        _handle_conversational_shortcut,
        _handle_capability_inventory_shortcut,
        _handle_direct_tool_runtime,
        _handle_skill_route,
        _handle_successful_local_command_completion,
        _handle_dev_pipeline_completion,
        _handle_dev_pipeline_dispatch,
        _handle_early_explicit_workflow,
        _handle_blueprint_approval_gate,
    )
    for handler in handlers:
        handled = handler(runtime, state, context)
        if handled is not None:
            return handled

    _normalize_long_document_execution_state(runtime, state)

    handlers = (
        _handle_codebase_ingestion,
        _handle_pre_planner_explicit_workflow,
        _handle_planner_dispatch,
        _handle_plan_clarification_gate,
        _handle_plan_approval_gate,
        _handle_pending_input_without_subplan_gate,
        _handle_long_document_subplan_gate,
        _handle_local_drive_ingestion,
        _handle_post_approval_explicit_workflow,
        _handle_extension_handler_generation,
        _handle_planned_batch_dispatch,
        _handle_dynamic_agent_runner_dispatch,
        _handle_master_coding_delegation,
        _handle_late_explicit_workflow,
        _handle_continuation_explicit_workflow,
    )
    for handler in handlers:
        handled = handler(runtime, state, context)
        if handled is not None:
            return handled
    return None


def _finish_with_message(state: dict[str, Any], *, role: str, text: str) -> dict[str, Any]:
    state["next_agent"] = "__finish__"
    state["final_output"] = text
    return append_message(state, make_message("orchestrator_agent", "user", role, text))


def _extract_report_section(report: str, header: str, next_header: str | None = None) -> str:
    text = str(report or "")
    marker = f"{header}:"
    start = text.find(marker)
    if start == -1:
        return ""
    start += len(marker)
    end = len(text)
    if next_header:
        next_marker = f"\n{next_header}:"
        next_idx = text.find(next_marker, start)
        if next_idx != -1:
            end = next_idx
    return text[start:end].strip()


def _summarize_successful_local_command(state: dict[str, Any]) -> str:
    query = str(state.get("user_query", "") or "").strip()
    lowered = query.lower()
    report = str(state.get("os_result") or state.get("draft_response") or state.get("last_agent_output") or "").strip()
    stdout = _extract_report_section(report, "STDOUT", "STDERR")
    stderr = _extract_report_section(report, "STDERR", "Error")
    stdout_first = next((line.strip() for line in stdout.splitlines() if line.strip()), "")
    stderr_first = next((line.strip() for line in stderr.splitlines() if line.strip() and line.strip() != "<empty>"), "")
    direct_output = report if report and "\n" not in report and "STDOUT:" not in report else ""
    primary_output = stdout_first or direct_output

    if any(marker in lowered for marker in ("vs code", "visual studio code", "vscode")):
        if primary_output.lower().startswith("installed:"):
            path = primary_output.split(":", 1)[1].strip()
            return f"yes. vscode installed at `{path}`."
        if primary_output.lower() == "not installed":
            return "no. vscode not installed."

    if primary_output:
        if stderr_first:
            return f"done. stdout: `{primary_output}`. stderr: `{stderr_first}`."
        return primary_output

    if stderr_first:
        return f"command failed: `{stderr_first}`."

    command = str(state.get("last_shell_command", "") or "").strip()
    if command:
        return f"done. command ran: `{command}`."
    return report


def _dispatch_task(
    state: dict[str, Any],
    *,
    recipient: str,
    intent: str,
    content: str,
    reason: str,
    sender: str = "orchestrator_agent",
    state_updates: dict[str, Any] | None = None,
) -> dict[str, Any]:
    updates = dict(state_updates or {})
    state["orchestrator_reason"] = reason
    state["next_agent"] = recipient
    return append_task(
        state,
        make_task(
            sender=sender,
            recipient=recipient,
            intent=intent,
            content=content,
            state_updates=updates,
        ),
    )


def _pending_message_role(state: dict[str, Any]) -> str:
    pending_scope = str(state.get("approval_pending_scope", "") or "").strip().lower()
    pending_kind = str(state.get("pending_user_input_kind", "") or "").strip().lower()
    if bool(state.get("plan_needs_clarification", False)):
        return "clarification"
    if pending_scope == "project_blueprint" or bool(state.get("blueprint_waiting_for_approval", False)):
        return "blueprint-approval"
    if pending_scope == "root_plan" or bool(state.get("plan_waiting_for_approval", False)):
        return "plan-approval"
    if (
        pending_scope == "long_document_plan"
        or pending_kind == "subplan_approval"
        or bool(state.get("long_document_plan_waiting_for_approval", False))
    ):
        return "subplan-approval"
    if pending_scope == "deep_research_confirmation" or pending_kind == "deep_research_confirmation":
        return "deep-research-approval"
    return "approval"


def _pending_message_text(state: dict[str, Any], default: str) -> str:
    return (
        state.get("pending_user_question")
        or approval_request_to_text(normalize_approval_request(state.get("approval_request", {})))
        or default
    )


def _handle_channel_bootstrap(runtime: Any, state: dict[str, Any], context: WorkflowPolicyContext) -> dict[str, Any] | None:
    if state.get("incoming_payload") and not state.get("gateway_message") and runtime._is_agent_available(state, "channel_gateway_agent"):
        return _dispatch_task(
            state,
            recipient="channel_gateway_agent",
            intent="channel-ingest-normalization",
            content=state.get("user_query", ""),
            reason="Normalize the incoming channel payload before orchestration.",
        )
    if state.get("gateway_message") and not state.get("channel_session") and runtime._is_agent_available(state, "session_router_agent"):
        return _dispatch_task(
            state,
            recipient="session_router_agent",
            intent="session-routing",
            content=state.get("user_query", ""),
            reason="Resolve or create a channel session before task execution.",
        )
    return None


def _handle_pending_user_input_gate(runtime: Any, state: dict[str, Any], context: WorkflowPolicyContext) -> dict[str, Any] | None:
    if not runtime._awaiting_user_input(state):
        return None
    approval_message = _pending_message_text(state, "Review the pending approval request before execution can continue.")
    return _finish_with_message(state, role=_pending_message_role(state), text=approval_message)


def _handle_resume_workflow_dispatch(runtime: Any, state: dict[str, Any], context: WorkflowPolicyContext) -> dict[str, Any] | None:
    explicit_workflow = match_explicit_workflow(runtime, state, stage="resume")
    if explicit_workflow is not None:
        return runtime._apply_workflow_dispatch_plan(state, explicit_workflow)
    return None


def _handle_conversational_shortcut(runtime: Any, state: dict[str, Any], context: WorkflowPolicyContext) -> dict[str, Any] | None:
    if not context.in_task_phase or state["orchestrator_calls"] > 5:
        return None
    direct = runtime._direct_response_if_conversational(context.current_objective, state)
    if direct is None:
        return None
    log_task_update("Orchestrator", "Conversational shortcut - skipping planner.")
    return _finish_with_message(state, role="final", text=direct)


def _handle_capability_inventory_shortcut(runtime: Any, state: dict[str, Any], context: WorkflowPolicyContext) -> dict[str, Any] | None:
    if not context.in_task_phase or not runtime._is_registry_discovery_request(state):
        return None
    direct = runtime._mcp_servers_overview() if runtime._is_mcp_discovery_request(state) else runtime._skills_overview(state)
    log_task_update("Orchestrator", "Capability discovery shortcut - returning inventory directly.")
    return _finish_with_message(state, role="final", text=direct)


def _handle_direct_tool_runtime(runtime: Any, state: dict[str, Any], context: WorkflowPolicyContext) -> dict[str, Any] | None:
    if not runtime._should_attempt_direct_tool_loop(state, in_task_phase=context.in_task_phase):
        return None
    direct_result = runtime._run_direct_tool_loop(state)
    state["direct_tool_loop_attempted"] = True
    direct_status = str(direct_result.get("status", "") or "").strip().lower()
    if direct_status in {"final", "awaiting_input"}:
        final_text = str(direct_result.get("response", "") or state.get("pending_user_question", "") or "").strip()
        if not final_text:
            final_text = state.get("draft_response") or state.get("last_agent_output") or "Direct tool execution completed."
        state["orchestrator_reason"] = str(direct_result.get("reason", "") or "Handled by the direct tool runtime.").strip()
        state["draft_response"] = final_text
        role = "approval" if state_awaiting_user_input(state) else "final"
        log_task_update("Orchestrator", f"Direct tool runtime handled the request ({direct_status}).")
        return _finish_with_message(state, role=role, text=final_text)
    fallback_reason = str(direct_result.get("reason", "") or "").strip()
    if fallback_reason:
        state["direct_tool_fallback_reason"] = fallback_reason
        log_task_update("Orchestrator", f"Direct tool runtime fallback: {fallback_reason}")
    return None


def _handle_skill_route(runtime: Any, state: dict[str, Any], context: WorkflowPolicyContext) -> dict[str, Any] | None:
    eligible = (
        context.in_task_phase
        and state["orchestrator_calls"] <= 1
        and not state.get("plan_steps")
        and not state.get("dev_pipeline_mode")
        and not state.get("long_document_mode")
        and context.current_objective
    )
    if not eligible or runtime._is_superrag_request(state):
        return None
    if runtime._is_local_command_request(state) or runtime._is_shell_plan_request(state):
        return None
    routed_agent = runtime.agent_routing.top_match(context.current_objective)
    if routed_agent and runtime._is_agent_available(state, routed_agent):
        log_task_update("Orchestrator", f"Agent route -> {routed_agent} (bypassing planner).")
        return _dispatch_task(
            state,
            recipient=routed_agent,
            intent="agent-routed",
            content=context.current_objective,
            reason=f"Agent routing matched '{routed_agent}' as the dominant handler - skipping planner.",
        )
    hints = runtime.agent_routing.hint_agents(context.current_objective, n=4)
    if hints:
        state["plan_agent_hints"] = hints
    return None


def _handle_successful_local_command_completion(runtime: Any, state: dict[str, Any], context: WorkflowPolicyContext) -> dict[str, Any] | None:
    if not context.in_task_phase:
        return None
    if str(state.get("last_agent", "") or "").strip() != "os_agent":
        return None
    if not bool(state.get("os_success", False)):
        return None
    if runtime._awaiting_user_input(state):
        return None
    if runtime._is_shell_plan_request(state):
        return None
    if not runtime._is_local_command_request(state):
        return None
    final_text = _summarize_successful_local_command(state)
    if not final_text:
        return None
    log_task_update("Orchestrator", "Successful local command workflow completed; returning os_agent result.")
    state["orchestrator_reason"] = "One-shot local command workflow completed successfully."
    return _finish_with_message(state, role="final", text=final_text)


def _handle_dev_pipeline_completion(runtime: Any, state: dict[str, Any], context: WorkflowPolicyContext) -> dict[str, Any] | None:
    dev_pipeline_status = str(state.get("dev_pipeline_status", "")).strip().lower()
    blueprint_just_approved = (
        str(state.get("blueprint_status", "")).strip() == "approved"
        and not bool(state.get("blueprint_waiting_for_approval", False))
    )
    if not bool(state.get("dev_pipeline_mode", False)):
        return None
    if dev_pipeline_status not in ("complete", "partial", "error", "cancelled", "waiting_for_approval"):
        return None
    if dev_pipeline_status == "waiting_for_approval" and blueprint_just_approved:
        state["dev_pipeline_status"] = ""
        log_task_update(
            "Orchestrator",
            "Blueprint approved; resuming dev pipeline - re-dispatching dev_pipeline_agent.",
        )
        return None
    final_output = (
        state.get("draft_response")
        or state.get("final_output")
        or state.get("dev_pipeline_error")
        or f"Dev pipeline finished with status: {dev_pipeline_status}."
    )
    log_task_update("Orchestrator", f"Dev pipeline completed with status={dev_pipeline_status}; routing to __finish__.")
    state["orchestrator_reason"] = f"Dev pipeline completed with status={dev_pipeline_status}."
    return _finish_with_message(state, role="final", text=final_output)


def _handle_dev_pipeline_dispatch(runtime: Any, state: dict[str, Any], context: WorkflowPolicyContext) -> dict[str, Any] | None:
    dev_pipeline_status = str(state.get("dev_pipeline_status", "")).strip().lower()
    if not bool(state.get("dev_pipeline_mode", False)) or dev_pipeline_status or not runtime._is_agent_available(state, "dev_pipeline_agent"):
        return None
    state["project_build_mode"] = True
    return _dispatch_task(
        state,
        recipient="dev_pipeline_agent",
        intent="dev-pipeline-dispatch",
        content=context.current_objective,
        reason=(
            "dev_pipeline_mode is set. Routing to dev_pipeline_agent for end-to-end "
            "project generation: blueprint -> scaffold -> build -> test -> verify -> zip."
        ),
        state_updates={"dev_pipeline_mode": True, "project_build_mode": True},
    )


def _handle_early_explicit_workflow(runtime: Any, state: dict[str, Any], context: WorkflowPolicyContext) -> dict[str, Any] | None:
    explicit_workflow = match_explicit_workflow(runtime, state, stage="early")
    if explicit_workflow is not None:
        return runtime._apply_workflow_dispatch_plan(state, explicit_workflow)
    return None


def _handle_blueprint_approval_gate(runtime: Any, state: dict[str, Any], context: WorkflowPolicyContext) -> dict[str, Any] | None:
    if not bool(state.get("blueprint_waiting_for_approval", False)):
        return None
    msg = state.get("pending_user_question") or "Review and approve the project blueprint before planning."
    return _finish_with_message(state, role="blueprint-approval", text=msg)


def _normalize_long_document_execution_state(runtime: Any, state: dict[str, Any]) -> None:
    if not runtime._is_long_document_request(state):
        return
    state["workflow_type"] = state.get("workflow_type") or ("deep_research" if runtime._is_deep_research_request(state) else "long_document")
    if state.get("plan_steps"):
        state["plan_steps"] = []
        state["plan_step_index"] = 0
        state["plan_execution_count"] = 0
    state["plan_ready"] = True
    state["plan_waiting_for_approval"] = False
    if state.get("plan_approval_status") == "approved":
        state["plan_approval_status"] = "not_started"


def _handle_codebase_ingestion(runtime: Any, state: dict[str, Any], context: WorkflowPolicyContext) -> dict[str, Any] | None:
    if not (
        bool(state.get("codebase_mode", False))
        and not state.get("plan_steps")
        and runtime._has_local_drive_request(state)
        and runtime._is_agent_available(state, "local_drive_agent")
        and state.get("last_agent") != "local_drive_agent"
        and int(state.get("local_drive_calls", 0) or 0) == 0
    ):
        return None
    updates = {"current_objective": context.current_objective}
    if not str(state.get("local_drive_working_directory", "")).strip():
        updates["local_drive_working_directory"] = state.get("working_directory", "")
    return _dispatch_task(
        state,
        recipient="local_drive_agent",
        intent="codebase-ingestion",
        content=context.current_objective,
        reason="Codebase mode enabled. Scan and summarize the repository before planning.",
        state_updates=updates,
    )


def _handle_pre_planner_explicit_workflow(runtime: Any, state: dict[str, Any], context: WorkflowPolicyContext) -> dict[str, Any] | None:
    explicit_workflow = match_explicit_workflow(runtime, state, stage="pre_planner")
    if explicit_workflow is not None:
        return runtime._apply_workflow_dispatch_plan(state, explicit_workflow)
    return None


def _handle_planner_dispatch(runtime: Any, state: dict[str, Any], context: WorkflowPolicyContext) -> dict[str, Any] | None:
    research_needs_synthesis = (
        state.get("last_agent") in {"research_pipeline_agent", "deep_research_agent"}
        and not state.get("research_synthesis_done")
        and not state.get("plan_steps")
    )
    research_synthesis_complete = bool(state.get("research_synthesis_done")) and not state.get("plan_steps")
    if (
        state.get("plan_ready", False)
        or not runtime._is_agent_available(state, "planner_agent")
        or research_needs_synthesis
        or research_synthesis_complete
    ):
        return None
    should_run_planner, planner_reason, planner_signals = runtime._should_run_planner(state)
    state["planner_policy_last"] = {
        "run": bool(should_run_planner),
        "reason": planner_reason,
        "signals": planner_signals,
    }
    if not should_run_planner or state.get("last_agent") == "planner_agent":
        return None
    reason = planner_reason or "Create a detailed step-by-step plan before execution."
    return _dispatch_task(
        state,
        recipient="planner_agent",
        intent="planning",
        content=context.current_objective,
        reason=reason,
    )


def _handle_plan_clarification_gate(runtime: Any, state: dict[str, Any], context: WorkflowPolicyContext) -> dict[str, Any] | None:
    if not bool(state.get("plan_needs_clarification", False)):
        return None
    clarification = state.get("pending_user_question") or "I need more detail before executing the plan."
    return _finish_with_message(state, role="clarification", text=clarification)


def _handle_plan_approval_gate(runtime: Any, state: dict[str, Any], context: WorkflowPolicyContext) -> dict[str, Any] | None:
    if not bool(state.get("plan_waiting_for_approval", False)):
        return None
    approval_message = state.get("pending_user_question") or "Review and approve the plan before execution."
    return _finish_with_message(state, role="plan-approval", text=approval_message)


def _handle_pending_input_without_subplan_gate(runtime: Any, state: dict[str, Any], context: WorkflowPolicyContext) -> dict[str, Any] | None:
    pending_input_kind = str(state.get("pending_user_input_kind", "") or "").strip().lower()
    if not pending_input_kind or bool(state.get("long_document_plan_waiting_for_approval", False)):
        return None
    approval_message = _pending_message_text(state, "Review the pending approval request before execution can continue.")
    role = "deep-research-approval" if pending_input_kind == "deep_research_confirmation" else "approval"
    return _finish_with_message(state, role=role, text=approval_message)


def _handle_long_document_subplan_gate(runtime: Any, state: dict[str, Any], context: WorkflowPolicyContext) -> dict[str, Any] | None:
    if not bool(state.get("long_document_plan_waiting_for_approval", False)):
        return None
    approval_message = state.get("pending_user_question") or "Review and approve the deep research section plan before execution."
    return _finish_with_message(state, role="subplan-approval", text=approval_message)


def _handle_local_drive_ingestion(runtime: Any, state: dict[str, Any], context: WorkflowPolicyContext) -> dict[str, Any] | None:
    if not (
        not state.get("plan_steps")
        and not runtime._is_long_document_request(state)
        and runtime._has_local_drive_request(state)
        and runtime._is_agent_available(state, "local_drive_agent")
        and state.get("last_agent") != "local_drive_agent"
        and int(state.get("local_drive_calls", 0) or 0) == 0
    ):
        return None
    updates = {"current_objective": context.current_objective}
    if not str(state.get("local_drive_working_directory", "")).strip():
        updates["local_drive_working_directory"] = state.get("working_directory", "")
    return _dispatch_task(
        state,
        recipient="local_drive_agent",
        intent="local-drive-ingestion",
        content=context.current_objective,
        reason="Ingest and summarize configured local-drive files before broader orchestration.",
        state_updates=updates,
    )


def _handle_post_approval_explicit_workflow(runtime: Any, state: dict[str, Any], context: WorkflowPolicyContext) -> dict[str, Any] | None:
    explicit_workflow = match_explicit_workflow(runtime, state, stage="post_approval")
    if explicit_workflow is not None:
        return runtime._apply_workflow_dispatch_plan(state, explicit_workflow)
    return None


def _handle_review_flow(runtime: Any, state: dict[str, Any], context: WorkflowPolicyContext) -> dict[str, Any] | None:
    for handler in (_handle_review_dispatch, _handle_review_revision, _handle_review_approval):
        handled = handler(runtime, state, context)
        if handled is not None:
            return handled
    return None


def _handle_review_dispatch(runtime: Any, state: dict[str, Any], context: WorkflowPolicyContext) -> dict[str, Any] | None:
    if not (
        state.get("last_agent")
        and state.get("last_agent") != "reviewer_agent"
        and state.get("review_pending")
        and runtime._is_agent_available(state, "reviewer_agent")
    ):
        return None
    reason = str(state.get("review_pending_reason", "")).strip() or f"Review the completed step from {state['last_agent']} before continuing."
    state["orchestrator_reason"] = reason
    state["next_agent"] = "reviewer_agent"
    state = append_task(
        state,
        make_task(sender="orchestrator_agent", recipient="reviewer_agent", intent="step-review", content=reason, state_updates={}),
    )
    record_work_note(state, "orchestrator_agent", "decision", f"next_agent=reviewer_agent\nreason={reason}\nstate_updates={{}}")
    return state


def _handle_review_revision(runtime: Any, state: dict[str, Any], context: WorkflowPolicyContext) -> dict[str, Any] | None:
    if not (state.get("last_agent") == "reviewer_agent" and state.get("review_decision") == "revise"):
        return None
    next_agent = state.get("review_target_agent") or "worker_agent"
    reason = state.get("review_reason", "Reviewer requested a corrected retry.")
    next_agent, reason = runtime._handle_unavailable_agent_choice(state, next_agent, reason)
    corrected_values = state.get("review_corrected_values", {})
    if not isinstance(corrected_values, dict):
        corrected_values = {}
    revised_objective = state.get("review_revised_objective") or context.current_objective
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
            state["review_pending_reason"] = ""
            update_planning_file(
                state,
                status="executing" if runtime._next_planned_agents(state) else "completed",
                objective=context.current_objective,
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
            return _dispatch_task(
                state,
                sender="reviewer_agent",
                recipient="long_document_agent",
                intent="correction",
                content=revised_objective,
                reason=reason,
                state_updates=corrected_values,
            )
    revision_attempt = runtime._record_review_revision(
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
        state["review_pending_reason"] = ""
        runtime._clear_review_revision(state, step_id=subject_step_id, agent_name=subject_agent)
        update_planning_file(
            state,
            status="executing" if runtime._next_planned_agents(state) else "completed",
            objective=context.current_objective,
            plan_text=state.get("plan", ""),
            clarifications=state.get("plan_clarification_questions", []),
            execution_note=forced_reason,
        )
        raise RuntimeError(forced_reason)
    corrected_values = {**corrected_values, "current_objective": revised_objective}
    return _dispatch_task(
        state,
        sender="reviewer_agent",
        recipient=next_agent,
        intent="correction",
        content=revised_objective,
        reason=reason,
        state_updates=corrected_values,
    )


def _handle_review_approval(runtime: Any, state: dict[str, Any], context: WorkflowPolicyContext) -> dict[str, Any] | None:
    if not (state.get("last_agent") == "reviewer_agent" and state.get("review_decision") == "approve"):
        return None
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
        runtime._clear_review_revision(state, step_id=approved_step_id, agent_name=approved_agent)
    update_planning_file(
        state,
        status="executing" if runtime._next_planned_agents(state) else "completed",
        objective=context.current_objective,
        plan_text=state.get("plan", ""),
        clarifications=state.get("plan_clarification_questions", []),
        execution_note=(
            f"Reviewer approved the latest step from {state.get('review_target_agent') or state.get('last_agent', '')}."
        ),
    )
    if runtime._next_planned_agents(state):
        state["review_pending"] = False
        state["review_pending_reason"] = ""
        return None
    gate_ok, gate_report = runtime._quality_gate_report(state)
    state["quality_gate_passed"] = gate_ok
    state["quality_gate_report"] = gate_report
    if not gate_ok:
        return _finish_with_message(
            state,
            role="final",
            text="Quality gate failed. The run is blocked until checks pass.\n\n" + gate_report,
        )
    final_text = state.get("draft_response") or state.get("last_agent_output") or "Completed."
    return _finish_with_message(state, role="final", text=final_text)


def _handle_extension_handler_generation(runtime: Any, state: dict[str, Any], context: WorkflowPolicyContext) -> dict[str, Any] | None:
    if not (
        bool(state.get("extension_handler_generation_requested", False))
        and not bool(state.get("extension_handler_generation_dispatched", False))
        and runtime._is_agent_available(state, "agent_factory_agent")
        and state.get("last_agent") != "agent_factory_agent"
    ):
        return None
    unsupported = state.get("local_drive_unknown_extensions", [])
    unsupported_text = ", ".join(str(item) for item in unsupported if str(item).strip()) or "unknown"
    request_text = str(state.get("agent_factory_request", "")).strip() or (
        "Create file-extension ingestion capability for unsupported local-drive formats: "
        f"{unsupported_text}."
    )
    state["extension_handler_generation_dispatched"] = True
    state["missing_capability"] = str(state.get("missing_capability", "")).strip() or f"File extension handling: {unsupported_text}"
    return _dispatch_task(
        state,
        recipient="agent_factory_agent",
        intent="extension-handler-generation",
        content=request_text,
        reason="Unsupported file extensions were detected and optional extension-agent generation is enabled.",
        state_updates={
            "agent_factory_request": request_text,
            "missing_capability": state["missing_capability"],
            "requested_missing_capability": state.get("requested_missing_capability", ""),
        },
    )


def _handle_planned_batch_dispatch(runtime: Any, state: dict[str, Any], context: WorkflowPolicyContext) -> dict[str, Any] | None:
    planned_batch = runtime._next_planned_agents(state)
    if not planned_batch:
        return None
    if runtime._should_parallelize_planned_batch(state, planned_batch):
        step_ids = [str(step.get("id", "")).strip() for step in planned_batch if isinstance(step, dict) and str(step.get("id", "")).strip()]
        if not step_ids:
            return None
        state["parallel_plan_batch"] = step_ids
        state["parallel_plan_batch_size"] = len(step_ids)
        log_task_update("Plan", f"Starting parallel read-only batch with {len(step_ids)} steps.")
        return _dispatch_task(
            state,
            recipient=runtime._PARALLEL_PLAN_EXECUTOR,
            intent="planned-parallel-batch",
            content=f"Execute planned steps in parallel: {', '.join(step_ids)}",
            reason="Execute safe read-only planned steps in parallel.",
            state_updates={
                "parallel_plan_batch": step_ids,
                "parallel_plan_batch_size": len(step_ids),
            },
        )
    next_step = planned_batch[0]
    state["parallel_plan_batch"] = []
    state["parallel_plan_batch_size"] = 0
    next_agent = str(next_step.get("agent") or "worker_agent").strip()
    task_content = str(next_step.get("task") or context.current_objective)
    if len(planned_batch) > 1:
        task_content = (
            f"{task_content}\n\nParallel batch hint: execute independently from other steps in group "
            f"'{next_step.get('parallel_group')}'."
        )
    next_agent, reason = runtime._handle_unavailable_agent_choice(
        state,
        next_agent,
        f"Execute planned step {next_step.get('id', '')}: {next_step.get('success_criteria', '')}",
    )
    state["planned_active_agent"] = next_agent
    state["planned_active_step_id"] = str(next_step.get("id", "")).strip()
    state["planned_active_step_title"] = str(next_step.get("title", "")).strip()
    state["planned_active_step_success_criteria"] = str(next_step.get("success_criteria", "")).strip()
    if state.get("orchestration_plan_id") and state["planned_active_step_id"]:
        claimed = runtime._claim_plan_step_lease(state, state["planned_active_step_id"])
        if claimed is None:
            log_task_update("Plan", f"Step {state['planned_active_step_id']} is already leased; waiting for the active worker.")
            state["planned_active_agent"] = ""
            state["planned_active_step_id"] = ""
            state["planned_active_step_title"] = ""
            state["planned_active_step_success_criteria"] = ""
            return None
    step_index = int(state.get("plan_step_index", 0) or 0)
    total_steps = len(state.get("plan_steps", []) or [])
    step_title = state.get("planned_active_step_title") or state.get("planned_active_step_id") or "planned step"
    log_task_update("Plan", f"Starting step {step_index + 1}/{total_steps}: {step_title} -> {next_agent}.")
    runtime._mark_step_running(state, step_index)
    return _dispatch_task(
        state,
        recipient=next_agent,
        intent="planned-step",
        content=task_content,
        reason=reason,
        state_updates={
            "current_objective": task_content,
            "current_plan_step_id": str(next_step.get("id", "")).strip(),
            "current_plan_step_title": str(next_step.get("title", "")).strip(),
            "current_plan_step_success_criteria": str(next_step.get("success_criteria", "")).strip(),
        },
    )


def _handle_dynamic_agent_runner_dispatch(runtime: Any, state: dict[str, Any], context: WorkflowPolicyContext) -> dict[str, Any] | None:
    if not (
        state.get("last_agent") == "agent_factory_agent"
        and state.get("dynamic_agent_ready")
        and runtime._is_agent_available(state, "dynamic_agent_runner")
    ):
        return None
    return _dispatch_task(
        state,
        recipient="dynamic_agent_runner",
        intent="run-generated-agent",
        content=state.get("generated_agent_task") or context.current_objective,
        reason="A generated agent is ready. Execute it through the dynamic agent runner.",
        state_updates={
            "generated_agent_name": state.get("generated_agent_name", ""),
            "generated_agent_function": state.get("generated_agent_function", ""),
            "generated_agent_module_path": state.get("generated_agent_module_path", ""),
            "generated_agent_task": state.get("generated_agent_task") or context.current_objective,
        },
    )


def _handle_master_coding_delegation(runtime: Any, state: dict[str, Any], context: WorkflowPolicyContext) -> dict[str, Any] | None:
    if state.get("last_agent") != "master_coding_agent":
        return None
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
        final_output = state.get("draft_response") or state.get("last_agent_output") or "Master coding workflow completed."
        return _finish_with_message(state, role="final", text=final_output)
    if not delegated_agent:
        return None
    delegated_agent, delegated_reason = runtime._handle_unavailable_agent_choice(state, delegated_agent, delegated_reason)
    if delegated_agent == "finish":
        state["orchestrator_reason"] = delegated_reason
        final_output = state.get("draft_response") or state.get("last_agent_output") or "Master coding workflow stopped."
        return _finish_with_message(state, role="final", text=final_output)
    return _dispatch_task(
        state,
        sender="master_coding_agent",
        recipient=delegated_agent,
        intent="master-coding-delegation",
        content=delegated_task,
        reason=delegated_reason,
        state_updates=delegated_updates,
    )


def _handle_late_explicit_workflow(runtime: Any, state: dict[str, Any], context: WorkflowPolicyContext) -> dict[str, Any] | None:
    explicit_workflow = match_explicit_workflow(runtime, state, stage="late")
    if explicit_workflow is not None:
        return runtime._apply_workflow_dispatch_plan(state, explicit_workflow)
    return None


def _handle_continuation_explicit_workflow(runtime: Any, state: dict[str, Any], context: WorkflowPolicyContext) -> dict[str, Any] | None:
    explicit_workflow = match_explicit_workflow(runtime, state, stage="continuation")
    if explicit_workflow is not None:
        return runtime._apply_workflow_dispatch_plan(state, explicit_workflow)
    return None
