from __future__ import annotations

from collections.abc import Mapping
from typing import Protocol

from kendr.orchestration import RuntimeState
from kendr.workflow_contract import normalize_approval_request


class PendingUserInputRuntime(Protocol):
    def _interpret_user_input_response(self, text: str) -> dict[str, str]:
        ...


_SCOPE_TO_KIND = {
    "deep_research_confirmation": "deep_research_confirmation",
    "long_document_plan": "subplan_approval",
    "root_plan": "plan_approval",
    "project_blueprint": "blueprint_approval",
}

_INTEGRATION_APPROVALS = {
    "integration_communication_access": ("communication_authorized", "Integration access cancelled by user."),
    "integration_aws_access": ("aws_authorized", "AWS access cancelled by user."),
    "integration_github_write_access": ("github_write_authorized", "GitHub write access cancelled by user."),
    "integration_github_local_git_access": ("github_local_git_authorized", "Local git mutation access cancelled by user."),
    "integration_github_remote_git_access": ("github_remote_git_authorized", "Remote git access cancelled by user."),
}


def restore_pending_user_input(
    runtime: PendingUserInputRuntime,
    initial_state: RuntimeState,
    prior_channel_state: Mapping[str, object],
    user_query: str,
) -> None:
    pending_kind = str(prior_channel_state.get("pending_user_input_kind", "") or "").strip()
    scope = str(prior_channel_state.get("approval_pending_scope", "") or "").strip()
    approval_request = normalize_approval_request(prior_channel_state.get("approval_request", {}))
    request_scope = str(approval_request.get("scope", "") or "").strip()
    resolved_scope = scope or request_scope
    if not pending_kind and resolved_scope:
        pending_kind = _SCOPE_TO_KIND.get(str(resolved_scope).strip().lower(), "approval")
    if not pending_kind and prior_channel_state.get("awaiting_user_input"):
        pending_kind = "clarification"
    if not pending_kind:
        return

    _hydrate_saved_plan_context(initial_state, prior_channel_state)

    previous_objective = str(prior_channel_state.get("last_objective", "") or "").strip()
    if pending_kind == "clarification":
        if previous_objective:
            initial_state["current_objective"] = f"{previous_objective}\n\nUser clarification: {user_query}"
        initial_state["plan_needs_clarification"] = False
        initial_state["pending_user_input_kind"] = ""
        initial_state["pending_user_question"] = ""
        initial_state["plan_ready"] = False
        return

    prompt = str(prior_channel_state.get("pending_user_question", "") or "").strip()
    scope = resolved_scope
    if previous_objective:
        initial_state["current_objective"] = previous_objective
    response = runtime._interpret_user_input_response(user_query)

    if _handle_drive_data_sufficiency(initial_state, scope, response):
        return
    if _handle_integration_approval(initial_state, scope, response):
        return
    if _handle_shell_approval(initial_state, prior_channel_state, approval_request, scope, response):
        return
    if _handle_deep_research_confirmation(initial_state, previous_objective, user_query, scope, response):
        return
    if _handle_generic_approval(initial_state, scope, response):
        return
    if _handle_generic_cancellation(initial_state, previous_objective, scope, response):
        return
    if _handle_generic_revision(initial_state, previous_objective, scope, response):
        return

    explicit_instruction = "Reply `approve` to continue, or describe the changes you want."
    if scope == "deep_research_confirmation":
        explicit_instruction = (
            "Reply `approve` to start deep research, `quick summary` to avoid the full run, "
            "or describe the scope changes you want."
        )
    _restore_pending_prompt(
        initial_state,
        pending_kind=pending_kind,
        scope=scope,
        approval_request=approval_request,
        prompt=prompt,
        explicit_instruction=explicit_instruction,
    )


def _hydrate_saved_plan_context(initial_state: RuntimeState, prior_channel_state: Mapping[str, object]) -> None:
    if initial_state.get("plan_steps") or not isinstance(prior_channel_state.get("plan_steps"), list):
        return
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


def _clear_pending_user_input(initial_state: RuntimeState) -> None:
    initial_state["pending_user_input_kind"] = ""
    initial_state["approval_pending_scope"] = ""
    initial_state["pending_user_question"] = ""
    initial_state["approval_request"] = {}


def _looks_like_document_only_feedback(initial_state: RuntimeState, previous_objective: str, feedback: str) -> bool:
    workflow_type = str(initial_state.get("workflow_type", "") or "").strip().lower()
    if workflow_type in {"deep_research", "long_document", "research_pipeline"}:
        return True
    if bool(initial_state.get("deep_research_mode", False)) or bool(initial_state.get("long_document_mode", False)):
        return True
    formats = {str(item or "").strip().lower() for item in (initial_state.get("research_output_formats") or [])}
    if formats & {"pdf", "docx", "html", "md", "markdown"}:
        return True
    combined = f"{previous_objective}\n{feedback}".lower()
    build_reject_markers = (
        "dont create",
        "don't create",
        "do not create",
        "dont build",
        "don't build",
        "do not build",
        "dont implement",
        "don't implement",
        "do not implement",
        "no existing files need to be changed",
        "only in the logs",
    )
    document_markers = (
        "deep research",
        "research report",
        "report",
        "document",
        "docx",
        "doc",
        "pdf",
        "markdown",
        "md",
        "citations",
        "output as files",
    )
    return any(marker in combined for marker in build_reject_markers) and any(marker in combined for marker in document_markers)


def _recover_blueprint_into_deep_research(
    initial_state: RuntimeState,
    previous_objective: str,
    feedback: str,
    *,
    cancelled: bool,
) -> None:
    _clear_pending_user_input(initial_state)
    initial_state["project_build_mode"] = False
    initial_state["blueprint_waiting_for_approval"] = False
    initial_state["blueprint_status"] = "cancelled" if cancelled else "revision_requested"
    initial_state["blueprint_json"] = {}
    initial_state["blueprint_summary"] = ""
    initial_state["plan_ready"] = False
    initial_state["user_cancelled"] = False
    initial_state["final_output"] = ""
    initial_state["deep_research_confirmed"] = True
    initial_state["deep_research_mode"] = True
    initial_state["long_document_mode"] = True
    initial_state["long_document_job_started"] = False
    initial_state["workflow_type"] = "deep_research"
    if previous_objective and feedback:
        initial_state["current_objective"] = (
            f"{previous_objective}\n\nDocument-only research instructions from the user:\n{feedback}"
        )
    elif previous_objective:
        initial_state["current_objective"] = previous_objective
    elif feedback:
        initial_state["current_objective"] = feedback


def _handle_drive_data_sufficiency(initial_state: RuntimeState, scope: str, response: Mapping[str, str]) -> bool:
    if scope != "drive_data_sufficiency":
        return False
    action = response.get("action")
    if action == "approve":
        _clear_pending_user_input(initial_state)
        initial_state["local_drive_insufficient_approved"] = True
        initial_state["local_drive_insufficient_response"] = response.get("feedback", "")
        return True
    if action in {"revise", "cancel"}:
        _clear_pending_user_input(initial_state)
        initial_state["user_cancelled"] = True
        initial_state["final_output"] = (
            "Run cancelled per your response. Add more source files and re-run when ready, "
            "or reply with updated instructions to proceed."
        )
        return True
    return False


def _handle_integration_approval(
    initial_state: RuntimeState,
    scope: str,
    response: Mapping[str, str],
) -> bool:
    approval = _INTEGRATION_APPROVALS.get(scope)
    if approval is None:
        return False
    state_key, cancel_message = approval
    action = response.get("action")
    if action == "approve":
        _clear_pending_user_input(initial_state)
        initial_state[state_key] = True
        return True
    if action in {"revise", "cancel"}:
        _clear_pending_user_input(initial_state)
        initial_state["user_cancelled"] = True
        initial_state["final_output"] = cancel_message
        return True
    return False


def _handle_shell_approval(
    initial_state: RuntimeState,
    prior_channel_state: Mapping[str, object],
    approval_request: Mapping[str, object],
    scope: str,
    response: Mapping[str, str],
) -> bool:
    if scope not in {"shell_command", "shell_plan_step"}:
        return False
    action = response.get("action")
    if action == "approve":
        _clear_pending_user_input(initial_state)
        initial_state["privileged_mode"] = True
        initial_state["privileged_approved"] = True
        approval_note = response.get("feedback", "") or "Approved by user for shell execution."
        initial_state["privileged_approval_note"] = str(approval_note).strip()
        metadata = approval_request.get("metadata", {}) if isinstance(approval_request, dict) else {}
        approval_mode = str(
            (metadata if isinstance(metadata, dict) else {}).get("approval_mode", "")
            or prior_channel_state.get("privileged_approval_mode", "")
            or "per_command"
        ).strip()
        initial_state["privileged_approval_mode"] = approval_mode
        return True
    if action in {"revise", "cancel"}:
        _clear_pending_user_input(initial_state)
        initial_state["user_cancelled"] = True
        initial_state["final_output"] = "Shell execution cancelled by user."
        return True
    return False


def _handle_deep_research_confirmation(
    initial_state: RuntimeState,
    previous_objective: str,
    user_query: str,
    scope: str,
    response: Mapping[str, str],
) -> bool:
    if scope != "deep_research_confirmation":
        return False
    action = response.get("action")
    if action == "approve":
        _clear_pending_user_input(initial_state)
        initial_state["deep_research_confirmed"] = True
        initial_state["deep_research_mode"] = True
        initial_state["long_document_mode"] = True
        initial_state["long_document_job_started"] = False
        initial_state["workflow_type"] = "deep_research"
        return True
    if action == "quick_summary":
        _clear_pending_user_input(initial_state)
        initial_state["deep_research_confirmed"] = True
        initial_state["deep_research_mode"] = False
        initial_state["long_document_mode"] = False
        initial_state["workflow_type"] = "research_pipeline"
        initial_state["research_pipeline_enabled"] = True
        initial_state["research_pipeline_completed"] = False
        initial_state["research_query"] = previous_objective or user_query
        return True
    if action == "cancel":
        _clear_pending_user_input(initial_state)
        initial_state["user_cancelled"] = True
        initial_state["final_output"] = "Deep research run cancelled by user."
        return True
    if action == "revise":
        _clear_pending_user_input(initial_state)
        initial_state["deep_research_confirmed"] = False
        initial_state["deep_research_analysis"] = {}
        if previous_objective:
            initial_state["current_objective"] = (
                f"{previous_objective}\n\nDeep research scope adjustments from the user:\n{response['feedback']}"
            )
        return True
    return False


def _handle_generic_approval(initial_state: RuntimeState, scope: str, response: Mapping[str, str]) -> bool:
    if response.get("action") != "approve":
        return False
    _clear_pending_user_input(initial_state)
    if scope == "project_blueprint":
        initial_state["blueprint_waiting_for_approval"] = False
        initial_state["blueprint_status"] = "approved"
        initial_state["plan_ready"] = False
    elif scope == "root_plan":
        initial_state["plan_waiting_for_approval"] = False
        initial_state["plan_approval_status"] = "approved"
        initial_state["plan_ready"] = bool(initial_state.get("plan_steps"))
        initial_state["plan_needs_clarification"] = False
    elif scope == "long_document_plan":
        _approve_long_document_subplan(initial_state)
    return True


def _approve_long_document_subplan(initial_state: RuntimeState) -> None:
    initial_state["long_document_plan_waiting_for_approval"] = False
    initial_state["long_document_plan_status"] = "approved"
    initial_state["long_document_execute_from_saved_outline"] = True
    initial_state["plan_ready"] = bool(initial_state.get("plan_steps")) and initial_state.get("plan_approval_status") == "approved"


def _handle_generic_cancellation(
    initial_state: RuntimeState,
    previous_objective: str,
    scope: str,
    response: Mapping[str, str],
) -> bool:
    if response.get("action") != "cancel":
        return False
    feedback = response.get("feedback", "")
    if scope == "project_blueprint" and _looks_like_document_only_feedback(initial_state, previous_objective, feedback):
        _recover_blueprint_into_deep_research(initial_state, previous_objective, feedback, cancelled=True)
        return True
    _clear_pending_user_input(initial_state)
    if scope == "project_blueprint":
        initial_state["blueprint_waiting_for_approval"] = False
        initial_state["blueprint_status"] = "cancelled"
        initial_state["blueprint_json"] = {}
    elif scope == "root_plan":
        initial_state["plan_waiting_for_approval"] = False
        initial_state["plan_approval_status"] = "cancelled"
        initial_state["plan_ready"] = False
    elif scope == "long_document_plan":
        initial_state["long_document_plan_waiting_for_approval"] = False
        initial_state["long_document_plan_status"] = "cancelled"
    initial_state["user_cancelled"] = True
    initial_state["final_output"] = "Run cancelled by user."
    return True


def _handle_generic_revision(
    initial_state: RuntimeState,
    previous_objective: str,
    scope: str,
    response: Mapping[str, str],
) -> bool:
    if response.get("action") != "revise":
        return False
    _clear_pending_user_input(initial_state)
    if scope == "project_blueprint":
        if _looks_like_document_only_feedback(initial_state, previous_objective, response.get("feedback", "")):
            _recover_blueprint_into_deep_research(
                initial_state,
                previous_objective,
                response.get("feedback", ""),
                cancelled=False,
            )
            return True
        initial_state["blueprint_waiting_for_approval"] = False
        initial_state["blueprint_status"] = "revision_requested"
        initial_state["blueprint_json"] = {}
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
        _request_long_document_subplan_revision(initial_state, previous_objective, response.get("feedback", ""))
    return True


def _request_long_document_subplan_revision(initial_state: RuntimeState, previous_objective: str, feedback: str) -> None:
    initial_state["long_document_plan_waiting_for_approval"] = False
    initial_state["long_document_plan_status"] = "revision_requested"
    initial_state["long_document_plan_feedback"] = feedback
    initial_state["long_document_plan_revision_count"] = int(initial_state.get("long_document_plan_revision_count", 0) or 0) + 1
    initial_state["long_document_replan_requested"] = True
    initial_state["plan_ready"] = bool(initial_state.get("plan_steps")) and initial_state.get("plan_approval_status") == "approved"
    if previous_objective:
        initial_state["current_objective"] = previous_objective


def _restore_pending_prompt(
    initial_state: RuntimeState,
    *,
    pending_kind: str,
    scope: str,
    approval_request: Mapping[str, object],
    prompt: str,
    explicit_instruction: str,
) -> None:
    initial_state["pending_user_input_kind"] = pending_kind
    initial_state["approval_pending_scope"] = scope
    initial_state["approval_request"] = dict(approval_request)
    if prompt:
        initial_state["pending_user_question"] = prompt if explicit_instruction in prompt else f"{prompt}\n\n{explicit_instruction}"
    else:
        initial_state["pending_user_question"] = explicit_instruction
    if scope == "deep_research_confirmation":
        initial_state["plan_ready"] = False
    elif scope == "project_blueprint":
        initial_state["blueprint_waiting_for_approval"] = True
        initial_state["plan_ready"] = False
    elif scope == "root_plan":
        initial_state["plan_waiting_for_approval"] = True
        initial_state["plan_ready"] = False
    elif scope == "long_document_plan":
        initial_state["long_document_plan_waiting_for_approval"] = True
        initial_state["plan_ready"] = bool(initial_state.get("plan_steps")) and initial_state.get("plan_approval_status") == "approved"
