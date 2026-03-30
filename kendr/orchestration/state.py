from __future__ import annotations

from typing import Any, Mapping, NotRequired, TypedDict


class PlanStep(TypedDict, total=False):
    id: str
    agent: str
    title: str
    task: str
    success: str
    success_criteria: str
    rationale: str


class FailureCheckpoint(TypedDict, total=False):
    can_resume: bool
    step_index: int
    task_content: str
    block_reason: str


class RuntimeState(TypedDict, total=False):
    run_id: str
    session_id: str
    session_started_at: str
    working_directory: str
    run_output_dir: str
    user_query: str
    current_objective: str
    last_agent: str
    plan_steps: list[PlanStep]
    plan_step_index: int
    current_plan_step_id: str
    current_plan_step_title: str
    last_completed_plan_step_id: str
    last_completed_plan_step_title: str
    plan_needs_clarification: bool
    plan_waiting_for_approval: bool
    plan_approval_status: str
    long_document_plan_waiting_for_approval: bool
    pending_user_input_kind: str
    pending_user_question: str
    approval_pending_scope: str
    failure_checkpoint: FailureCheckpoint
    recent_events: list[dict[str, Any]]
    channel_session_key: str
    parent_run_id: str
    last_error: str
    # Project builder state
    project_build_mode: bool
    blueprint_json: dict[str, Any]
    blueprint_status: str
    blueprint_version: int
    blueprint_waiting_for_approval: bool
    project_name: str
    project_root: str
    project_stack: str
    enforce_quality_gate: bool
    quality_gate_passed: bool
    quality_gate_report: str
    test_agent_status: str
    security_scan_status: str
    verifier_status: str
    codebase_mode: bool
    local_drive_auto_generate_extension_handlers: bool
    local_drive_unknown_extensions: list[str]
    local_drive_handler_registry: dict[str, str]
    local_drive_handler_routes: dict[str, list[str]]
    local_drive_min_files_for_long_document: int
    local_drive_sufficiency_threshold: int
    local_drive_selected_file_count: int
    local_drive_insufficient: bool
    local_drive_insufficient_approved: bool
    local_drive_insufficient_prompted: bool
    local_drive_insufficient_response: str
    local_drive_insufficient_files_preview: list[str]
    extension_handler_generation_requested: bool
    extension_handler_generation_dispatched: bool
    extension_handler_generation_signature: str
    agent_factory_request: str
    long_document_collect_sources_first: bool
    long_document_disable_visuals: bool
    long_document_section_references: bool
    long_document_section_search: bool
    long_document_section_search_results: int
    long_document_sources_collected: bool
    long_document_evidence_bank_path: str
    long_document_evidence_bank_json_path: str
    long_document_evidence_bank_excerpt: str
    long_document_evidence_sources: list[dict[str, Any]]
    long_document_addendum_on_review: bool
    long_document_addendum_requested: bool
    long_document_addendum_instructions: str
    long_document_addendum_attempts: int
    long_document_addendum_max_attempts: int
    long_document_addendum_path: str
    long_document_addendum_completed: bool
    long_document_compiled_html_path: str
    long_document_compiled_docx_path: str
    long_document_compiled_pdf_path: str
    research_heartbeat_seconds: int
    user_cancelled: bool


class ResumeCandidate(TypedDict, total=False):
    run_id: str
    session_id: str
    status: str
    resume_status: str
    resumable: bool
    branchable: bool
    resume_strategy: str
    working_directory: str
    run_output_dir: str
    updated_at: str
    completed_at: str
    objective: str
    user_query: str
    active_agent: str
    last_agent: str
    last_error: str
    pending_user_input_kind: str
    pending_user_question: str
    approval_pending_scope: str
    plan_step_index: int
    plan_step_count: int
    current_plan_step_id: str
    current_plan_step_title: str
    last_completed_plan_step_id: str
    last_completed_plan_step_title: str
    failure_checkpoint: FailureCheckpoint
    channel_session_key: str
    parent_run_id: str
    requires_takeover: bool
    checkpoint: dict[str, Any]
    manifest: dict[str, Any]


class ResumeStateOverrides(TypedDict, total=False):
    working_directory: str
    resume_checkpoint_payload: dict[str, Any]
    resume_mode: str
    parent_run_id: str
    incoming_channel: str
    incoming_workspace_id: str
    incoming_sender_id: str
    incoming_chat_id: str
    incoming_is_group: bool
    memory_force_new_session: bool
    run_id: str
    session_id: str
    resume_output_dir: str
    channel_session_key: str
    max_steps: int
    incoming_text: str
    incoming_mentions_assistant: bool
    incoming_payload: dict[str, Any]
    run_output_dir: str
    user_query: NotRequired[str]


def state_awaiting_user_input(state: Mapping[str, Any]) -> bool:
    return bool(
        state.get("plan_needs_clarification", False)
        or state.get("plan_waiting_for_approval", False)
        or state.get("long_document_plan_waiting_for_approval", False)
        or state.get("blueprint_waiting_for_approval", False)
        or str(state.get("pending_user_input_kind", "")).strip()
    )
