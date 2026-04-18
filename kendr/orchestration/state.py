from __future__ import annotations

from typing import Any, Mapping, TypedDict
try:
    from typing import NotRequired
except ImportError:
    from typing_extensions import NotRequired

from kendr.workflow_contract import approval_request_to_text, normalize_approval_request


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
    db_path: str
    run_id: str
    workflow_id: str
    attempt_id: str
    workflow_type: str
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
    orchestration_plan_id: str
    orchestration_plan_version: int
    last_completed_plan_step_id: str
    last_completed_plan_step_title: str
    intent_signature: str
    selected_intent_id: str
    selected_intent_type: str
    selected_intent: dict[str, Any]
    intent_candidates: list[dict[str, Any]]
    plan_needs_clarification: bool
    plan_waiting_for_approval: bool
    plan_approval_status: str
    long_document_plan_waiting_for_approval: bool
    pending_user_input_kind: str
    pending_user_question: str
    approval_pending_scope: str
    approval_request: dict[str, Any]
    failure_checkpoint: FailureCheckpoint
    recent_events: list[dict[str, Any]]
    channel_session_key: str
    parent_run_id: str
    last_error: str
    # Project context (kendr.md)
    project_context_md: str
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
    adaptive_agent_selection: bool
    direct_tool_loop_attempted: bool
    direct_tool_trace: list[dict[str, Any]]
    direct_tool_last_result: dict[str, Any]
    direct_tool_fallback_reason: str
    direct_tool_native_fallback_reason: str
    planner_policy_mode: str
    reviewer_policy_mode: str
    execution_mode: str
    planner_score_threshold: int
    reviewer_score_threshold: int
    review_pending_reason: str
    planner_policy_last: dict[str, Any]
    review_policy_last: dict[str, Any]
    test_agent_status: str
    security_authorized: bool
    github_write_authorized: bool
    github_local_git_authorized: bool
    github_remote_git_authorized: bool
    security_target_url: str
    security_authorization_note: str
    security_scan_profile: str
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
    long_document_source_manifest_path: str
    long_document_source_manifest_json_path: str
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
    deep_research_mode: bool
    deep_research_tier: int
    deep_research_confirmed: bool
    deep_research_analysis: dict[str, Any]
    deep_research_result_card: dict[str, Any]
    deep_research_source_urls: list[str]
    research_output_formats: list[str]
    research_citation_style: str
    research_enable_plagiarism_check: bool
    research_web_search_enabled: bool
    research_search_backend: str
    research_date_range: str
    research_max_sources: int
    research_checkpoint_enabled: bool
    research_heartbeat_seconds: int
    research_sources: list[str]
    research_pipeline_enabled: bool
    research_pipeline_completed: bool
    pipeline_skip_synthesis: bool
    skip_test_agent: bool
    skip_devops_agent: bool
    user_cancelled: bool
    # Dev pipeline state
    dev_pipeline_mode: bool
    dev_pipeline_status: str
    dev_pipeline_stages_completed: list[str]
    dev_pipeline_error: str
    dev_pipeline_zip_path: str
    dev_pipeline_max_fix_rounds: int
    project_verifier_status: str
    project_verifier_output: str


class ResumeCandidate(TypedDict, total=False):
    run_id: str
    workflow_id: str
    attempt_id: str
    workflow_type: str
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
    approval_request: dict[str, Any]
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
    workflow_id: str
    attempt_id: str
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
    security_authorized: bool
    security_target_url: str
    security_authorization_note: str
    security_scan_profile: str
    execution_mode: str


def _state_has_meaningful_approval_request(state: Mapping[str, Any]) -> bool:
    approval_request = normalize_approval_request(state.get("approval_request", {}))
    return bool(approval_request_to_text(approval_request))


def state_awaiting_user_input(state: Mapping[str, Any]) -> bool:
    return bool(
        str(state.get("pending_user_question", "") or "").strip()
        or _state_has_meaningful_approval_request(state)
    )
