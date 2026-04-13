from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable


@dataclass(slots=True)
class WorkflowDispatchPlan:
    workflow_id: str
    agent_name: str
    reason: str
    intent: str
    content: str
    state_updates: dict[str, Any] = field(default_factory=dict)
    state_mutations: dict[str, Any] = field(default_factory=dict)
    decision_note: str = ""


@dataclass(slots=True)
class WorkflowRouteDefinition:
    workflow_id: str
    stage: str
    matches: Callable[[Any, dict[str, Any]], bool]
    build_plan: Callable[[Any, dict[str, Any]], WorkflowDispatchPlan]


def explicit_workflow_routes() -> list[WorkflowRouteDefinition]:
    return [
        WorkflowRouteDefinition(
            workflow_id="project_build_blueprint",
            stage="early",
            matches=_match_project_build_blueprint,
            build_plan=_build_project_build_blueprint_plan,
        ),
        WorkflowRouteDefinition(
            workflow_id="shell_plan",
            stage="early",
            matches=_match_shell_plan,
            build_plan=_build_shell_plan_plan,
        ),
        WorkflowRouteDefinition(
            workflow_id="local_command",
            stage="early",
            matches=_match_local_command,
            build_plan=_build_local_command_plan,
        ),
        WorkflowRouteDefinition(
            workflow_id="github_operations",
            stage="early",
            matches=_match_github_operations,
            build_plan=_build_github_operations_plan,
        ),
        WorkflowRouteDefinition(
            workflow_id="communication_digest",
            stage="early",
            matches=_match_communication_digest,
            build_plan=_build_communication_digest_plan,
        ),
        WorkflowRouteDefinition(
            workflow_id="project_workbench",
            stage="early",
            matches=_match_project_workbench,
            build_plan=_build_project_workbench_plan,
        ),
        WorkflowRouteDefinition(
            workflow_id="deep_research_resume",
            stage="resume",
            matches=_match_deep_research_resume,
            build_plan=_build_deep_research_resume_plan,
        ),
        WorkflowRouteDefinition(
            workflow_id="document_generation",
            stage="pre_planner",
            matches=_match_document_generation,
            build_plan=_build_document_generation_plan,
        ),
        WorkflowRouteDefinition(
            workflow_id="research_pipeline",
            stage="pre_planner",
            matches=_match_research_pipeline,
            build_plan=_build_research_pipeline_plan,
        ),
        WorkflowRouteDefinition(
            workflow_id="project_audit",
            stage="pre_planner",
            matches=_match_project_audit,
            build_plan=_build_project_audit_plan,
        ),
        WorkflowRouteDefinition(
            workflow_id="superrag",
            stage="late",
            matches=_match_superrag,
            build_plan=_build_superrag_plan,
        ),
        WorkflowRouteDefinition(
            workflow_id="deep_research",
            stage="late",
            matches=_match_deep_research,
            build_plan=_build_deep_research_plan,
        ),
        WorkflowRouteDefinition(
            workflow_id="long_document",
            stage="late",
            matches=_match_long_document,
            build_plan=_build_long_document_plan,
        ),
        WorkflowRouteDefinition(
            workflow_id="drive_informed_long_document",
            stage="post_approval",
            matches=_match_drive_informed_long_document,
            build_plan=_build_drive_informed_long_document_plan,
        ),
        WorkflowRouteDefinition(
            workflow_id="research_pipeline_continue",
            stage="continuation",
            matches=_match_research_pipeline_continue,
            build_plan=_build_research_pipeline_continue_plan,
        ),
        WorkflowRouteDefinition(
            workflow_id="research_synthesis",
            stage="continuation",
            matches=_match_research_synthesis,
            build_plan=_build_research_synthesis_plan,
        ),
    ]


def match_explicit_workflow(runtime: Any, state: dict[str, Any], *, stage: str = "all") -> WorkflowDispatchPlan | None:
    for route in explicit_workflow_routes():
        try:
            if stage != "all" and route.stage != stage:
                continue
            if route.matches(runtime, state):
                return route.build_plan(runtime, state)
        except Exception:
            continue
    return None


def _current_objective(state: dict[str, Any]) -> str:
    return str(state.get("current_objective") or state.get("user_query") or "").strip()


def _match_project_build_blueprint(runtime: Any, state: dict[str, Any]) -> bool:
    return bool(
        not state.get("plan_steps")
        and state.get("last_agent") != "project_blueprint_agent"
        and not state.get("blueprint_json")
        and runtime._is_agent_available(state, "project_blueprint_agent")
        and runtime._is_project_build_request(state)
        and not bool(state.get("dev_pipeline_mode", False))
    )


def _build_project_build_blueprint_plan(runtime: Any, state: dict[str, Any]) -> WorkflowDispatchPlan:
    objective = _current_objective(state)
    return WorkflowDispatchPlan(
        workflow_id="project_build",
        agent_name="project_blueprint_agent",
        reason="Build request detected. Route to project_blueprint_agent for technical architecture.",
        intent="project-blueprint",
        content=objective,
        state_updates={"blueprint_request": objective},
        state_mutations={"project_build_mode": True},
    )


def _match_local_command(runtime: Any, state: dict[str, Any]) -> bool:
    return bool(
        not state.get("plan_steps")
        and runtime._is_agent_available(state, "os_agent")
        and runtime._is_local_command_request(state)
        and not runtime._is_shell_plan_request(state)
        and not runtime._is_project_build_request(state)
    )


def _match_shell_plan(runtime: Any, state: dict[str, Any]) -> bool:
    return bool(
        not state.get("plan_steps")
        and runtime._is_agent_available(state, "shell_plan_agent")
        and runtime._is_shell_plan_request(state)
        and not runtime._is_project_build_request(state)
    )


def _build_shell_plan_plan(runtime: Any, state: dict[str, Any]) -> WorkflowDispatchPlan:
    objective = _current_objective(state)
    return WorkflowDispatchPlan(
        workflow_id="shell_plan",
        agent_name="shell_plan_agent",
        reason=(
            "The request is a multi-step local setup/runtime workflow. "
            "Route directly to shell_plan_agent for deterministic step planning and execution."
        ),
        intent="shell-plan-dispatch",
        content=objective,
        state_updates={"current_objective": objective},
    )


def _build_local_command_plan(runtime: Any, state: dict[str, Any]) -> WorkflowDispatchPlan:
    objective = _current_objective(state)
    state_updates = {"current_objective": objective}
    os_hint = runtime._derive_local_command_hint(state)
    if isinstance(os_hint, dict) and os_hint:
        state_updates.update(os_hint)
    return WorkflowDispatchPlan(
        workflow_id="local_command",
        agent_name="os_agent",
        reason="The request is a local command execution workflow. Route to os_agent for controlled shell execution.",
        intent="local-command-dispatch",
        content=objective,
        state_updates=state_updates,
    )


def _match_github_operations(runtime: Any, state: dict[str, Any]) -> bool:
    return bool(
        not state.get("plan_steps")
        and state.get("last_agent") != "github_agent"
        and runtime._is_agent_available(state, "github_agent")
        and runtime._is_github_request(state)
        and not runtime._is_project_build_request(state)
    )


def _build_github_operations_plan(runtime: Any, state: dict[str, Any]) -> WorkflowDispatchPlan:
    objective = _current_objective(state)
    github_task = str(state.get("github_task") or objective).strip()
    return WorkflowDispatchPlan(
        workflow_id="github",
        agent_name="github_agent",
        reason=(
            "The request is a GitHub / git repository workflow (PR, issue, clone, push, etc.). "
            "Route to github_agent for direct, deterministic execution."
        ),
        intent="github-operation",
        content=objective,
        state_updates={"github_task": github_task},
        state_mutations={"github_task": github_task},
    )


def _match_communication_digest(runtime: Any, state: dict[str, Any]) -> bool:
    return bool(
        not state.get("plan_steps")
        and state.get("last_agent") != "communication_summary_agent"
        and runtime._is_agent_available(state, "communication_summary_agent")
        and runtime._is_communication_summary_request(state)
        and not runtime._is_project_build_request(state)
    )


def _build_communication_digest_plan(runtime: Any, state: dict[str, Any]) -> WorkflowDispatchPlan:
    objective = _current_objective(state)
    return WorkflowDispatchPlan(
        workflow_id="communication_summary",
        agent_name="communication_summary_agent",
        reason="The request is a communication digest/summary workflow. Route to communication_summary_agent.",
        intent="communication-digest",
        content=objective,
        state_updates={"current_objective": objective},
    )


def _match_project_workbench(runtime: Any, state: dict[str, Any]) -> bool:
    return bool(
        not state.get("plan_steps")
        and state.get("last_agent") != "master_coding_agent"
        and runtime._is_agent_available(state, "master_coding_agent")
        and runtime._is_project_workbench_request(state)
    )


def _build_project_workbench_plan(runtime: Any, state: dict[str, Any]) -> WorkflowDispatchPlan:
    objective = _current_objective(state)
    return WorkflowDispatchPlan(
        workflow_id="project_workbench",
        agent_name="master_coding_agent",
        reason=(
            "Project workbench request detected with an active repository context. "
            "Route directly to master_coding_agent for code-aware inspection or implementation, bypassing the generic planner."
        ),
        intent="project-workbench-dispatch",
        content=objective,
        state_updates={
            "master_coding_request": objective,
            "coding_task": objective,
            "codebase_mode": True,
        },
        state_mutations={"codebase_mode": True},
    )


def _deep_research_pipeline_completed(state: dict[str, Any]) -> bool:
    result_card = state.get("deep_research_result_card", {})
    result_kind = str((result_card or {}).get("kind", "")).strip().lower() if isinstance(result_card, dict) else ""
    return bool(
        result_kind == "result"
        or str(state.get("long_document_compiled_path", "")).strip()
        or str(state.get("long_document_manifest_path", "")).strip()
    )


def _match_deep_research_resume(runtime: Any, state: dict[str, Any]) -> bool:
    deep_research_workflow = bool(
        bool(state.get("deep_research_mode", False))
        or str(state.get("workflow_type", "")).strip().lower() == "deep_research"
    )
    return bool(
        deep_research_workflow
        and bool(state.get("deep_research_confirmed", False))
        and not _deep_research_pipeline_completed(state)
        and runtime._is_agent_available(state, "long_document_agent")
    )


def _build_deep_research_resume_plan(runtime: Any, state: dict[str, Any]) -> WorkflowDispatchPlan:
    objective = _current_objective(state)
    reason = "Deep research confirmed by user — resuming long_document_agent to run the full research pipeline."
    return WorkflowDispatchPlan(
        workflow_id="deep_research_resume",
        agent_name="long_document_agent",
        reason=reason,
        intent="long-document-resume",
        content=objective,
        state_updates={"long_document_mode": True},
        state_mutations={
            "long_document_mode": True,
            "long_document_job_started": True,
        },
    )


def _match_document_generation(runtime: Any, state: dict[str, Any]) -> bool:
    return bool(
        not state.get("plan_steps")
        and not state.get("long_document_mode")
        and not state.get("long_document_job_started")
        and state.get("last_agent") not in {"long_document_agent"}
        and runtime._is_document_generation_request(state)
        and runtime._is_agent_available(state, "long_document_agent")
    )


def _build_document_generation_plan(runtime: Any, state: dict[str, Any]) -> WorkflowDispatchPlan:
    objective = _current_objective(state)
    workflow_type = state.get("workflow_type") or "long_document"
    reason = (
        "The request asks for a researched document/report to be produced as a file. "
        "Routing directly to long_document_agent which will research, write, and export "
        "the document as Markdown, PDF, and DOCX."
    )
    return WorkflowDispatchPlan(
        workflow_id="document_generation",
        agent_name="long_document_agent",
        reason=reason,
        intent="long-document-dispatch",
        content=objective,
        state_updates={
            "long_document_mode": True,
            "long_document_collect_sources_first": True,
            "current_objective": objective,
        },
        state_mutations={
            "long_document_mode": True,
            "workflow_type": workflow_type,
            "long_document_job_started": True,
            "long_document_collect_sources_first": True,
        },
        decision_note=(
            "next_agent=long_document_agent\n"
            f"reason={reason}\n"
            "state_updates={"
            "'long_document_mode': True, "
            "'long_document_collect_sources_first': True, "
            f"'current_objective': {objective!r}"
            "}"
        ),
    )


def _match_research_pipeline(runtime: Any, state: dict[str, Any]) -> bool:
    return bool(
        not state.get("plan_steps")
        and not state.get("research_pipeline_enabled")
        and not state.get("research_synthesis_done")
        and state.get("last_agent") not in {"research_pipeline_agent", "deep_research_agent"}
        and runtime._is_research_request(state)
        and not runtime._is_deep_research_request(state)
        and runtime._is_agent_available(state, "research_pipeline_agent")
    )


def _build_research_pipeline_plan(runtime: Any, state: dict[str, Any]) -> WorkflowDispatchPlan:
    objective = _current_objective(state)
    sources = state.get("research_sources") or ["web"]
    reason = (
        "The request is a research / information task. Bypassing the planner and routing "
        "to research_pipeline_agent for multi-source web evidence collection."
    )
    return WorkflowDispatchPlan(
        workflow_id="research_pipeline",
        agent_name="research_pipeline_agent",
        reason=reason,
        intent="research-pipeline-dispatch",
        content=objective,
        state_updates={
            "research_sources": sources,
            "research_pipeline_enabled": True,
        },
        state_mutations={
            "research_pipeline_enabled": True,
            "research_pipeline_completed": False,
        },
        decision_note=(
            "next_agent=research_pipeline_agent\n"
            f"reason={reason}\n"
            f"state_updates={{'research_sources': {sources!r}, 'research_pipeline_enabled': True}}"
        ),
    )


def _match_project_audit(runtime: Any, state: dict[str, Any]) -> bool:
    return bool(
        not state.get("plan_steps")
        and state.get("last_agent") != "master_coding_agent"
        and runtime._is_agent_available(state, "master_coding_agent")
        and runtime._is_project_audit_request(state)
    )


def _build_project_audit_plan(runtime: Any, state: dict[str, Any]) -> WorkflowDispatchPlan:
    objective = _current_objective(state)
    return WorkflowDispatchPlan(
        workflow_id="project_audit",
        agent_name="master_coding_agent",
        reason="The request is a project/codebase audit. Route to master_coding_agent for a structured production-readiness assessment.",
        intent="project-audit-dispatch",
        content=objective,
        state_updates={"master_coding_request": objective, "coding_task": objective},
    )


def _match_superrag(runtime: Any, state: dict[str, Any]) -> bool:
    return bool(
        not state.get("plan_steps")
        and state.get("last_agent") != "superrag_agent"
        and runtime._is_agent_available(state, "superrag_agent")
        and runtime._is_superrag_request(state)
    )


def _build_superrag_plan(runtime: Any, state: dict[str, Any]) -> WorkflowDispatchPlan:
    objective = _current_objective(state)
    return WorkflowDispatchPlan(
        workflow_id="superrag",
        agent_name="superrag_agent",
        reason=(
            "The request is a RAG/session knowledge-system workflow. "
            "Route to superrag_agent for ingestion, indexing, session switching, or chat."
        ),
        intent="superrag-dispatch",
        content=objective,
        state_updates={"current_objective": objective},
        decision_note=(
            f"next_agent=superrag_agent\nreason=The request is a RAG/session knowledge-system workflow. "
            f"Route to superrag_agent for ingestion, indexing, session switching, or chat.\n"
            f"state_updates={{'current_objective': '{objective}'}}"
        ),
    )


def _match_deep_research(runtime: Any, state: dict[str, Any]) -> bool:
    return bool(
        not state.get("plan_steps")
        and state.get("last_agent") != "deep_research_agent"
        and runtime._is_agent_available(state, "deep_research_agent")
        and not runtime._is_long_document_request(state)
        and runtime._is_deep_research_request(state)
    )


def _build_deep_research_plan(runtime: Any, state: dict[str, Any]) -> WorkflowDispatchPlan:
    objective = _current_objective(state)
    reason = "The request is a deep research task. Route to deep_research_agent for deep research execution."
    return WorkflowDispatchPlan(
        workflow_id="deep_research",
        agent_name="deep_research_agent",
        reason=reason,
        intent="deep-research-dispatch",
        content=objective,
        state_updates={"research_query": objective},
        state_mutations={"workflow_type": state.get("workflow_type") or "deep_research"},
        decision_note=f"next_agent=deep_research_agent\nreason={reason}\nstate_updates={{'research_query': '{objective}'}}",
    )


def _match_long_document(runtime: Any, state: dict[str, Any]) -> bool:
    return bool(
        not state.get("plan_steps")
        and state.get("last_agent") != "long_document_agent"
        and runtime._is_agent_available(state, "long_document_agent")
        and runtime._is_long_document_request(state)
    )


def _build_long_document_plan(runtime: Any, state: dict[str, Any]) -> WorkflowDispatchPlan:
    objective = _current_objective(state)
    reason = (
        "The request is a deep research report objective. "
        "Route to long_document_agent for staged section research and final merge."
    )
    workflow_type = state.get("workflow_type") or ("deep_research" if runtime._is_deep_research_request(state) else "long_document")
    updates = {
        "current_objective": objective,
        "long_document_mode": True,
    }
    return WorkflowDispatchPlan(
        workflow_id="long_document",
        agent_name="long_document_agent",
        reason=reason,
        intent="long-document-dispatch",
        content=objective,
        state_updates=updates,
        state_mutations={"workflow_type": workflow_type},
        decision_note=(
            "next_agent=long_document_agent\n"
            f"reason={reason}\n"
            f"state_updates={updates}"
        ),
    )


def _match_drive_informed_long_document(runtime: Any, state: dict[str, Any]) -> bool:
    return bool(
        not state.get("plan_steps")
        and bool(state.get("local_drive_force_long_document", False))
        and runtime._is_long_document_request(state)
        and runtime._is_agent_available(state, "long_document_agent")
        and state.get("last_agent") != "long_document_agent"
        and int(state.get("local_drive_calls", 0) or 0) > 0
    )


def _build_drive_informed_long_document_plan(runtime: Any, state: dict[str, Any]) -> WorkflowDispatchPlan:
    objective = _current_objective(state)
    drive_summary = str(state.get("local_drive_summary") or state.get("document_summary") or "").strip()
    long_doc_objective = objective
    if drive_summary:
        long_doc_objective = (
            f"{objective}\n\nUse this local-drive evidence summary as primary context:\n"
            f"{runtime._truncate(drive_summary, 5000)}"
        )
    updates: dict[str, Any] = {
        "current_objective": long_doc_objective,
        "long_document_mode": True,
    }
    if int(state.get("long_document_pages", 0) or 0) <= 0:
        updates["long_document_pages"] = 50
    reason = (
        "Local-drive ingestion is complete and a deep research report was requested. "
        "Route to long_document_agent for staged long-running synthesis."
    )
    return WorkflowDispatchPlan(
        workflow_id="drive_informed_long_document",
        agent_name="long_document_agent",
        reason=reason,
        intent="drive-informed-long-document",
        content=long_doc_objective,
        state_updates=updates,
        decision_note=(
            "next_agent=long_document_agent\n"
            f"reason={reason}\n"
            f"state_updates={updates}"
        ),
    )


def _match_research_pipeline_continue(runtime: Any, state: dict[str, Any]) -> bool:
    return bool(
        bool(state.get("research_pipeline_enabled", False))
        and not bool(state.get("research_pipeline_completed", False))
        and not state.get("plan_steps")
        and state.get("last_agent") != "research_pipeline_agent"
        and runtime._is_agent_available(state, "research_pipeline_agent")
    )


def _build_research_pipeline_continue_plan(runtime: Any, state: dict[str, Any]) -> WorkflowDispatchPlan:
    objective = _current_objective(state)
    sources = state.get("research_sources") or ["web"]
    reason = (
        "research_pipeline_enabled is set. Routing to research_pipeline_agent "
        "to perform parallel multi-source evidence collection and LLM synthesis."
    )
    return WorkflowDispatchPlan(
        workflow_id="research_pipeline_continue",
        agent_name="research_pipeline_agent",
        reason=reason,
        intent="research-pipeline-dispatch",
        content=objective,
        state_updates={
            "research_sources": sources,
            "research_pipeline_enabled": True,
        },
        decision_note=(
            "next_agent=research_pipeline_agent\n"
            f"reason={reason}\n"
            f"state_updates={{'research_sources': {sources!r}, 'research_pipeline_enabled': True}}"
        ),
    )


def _research_body(state: dict[str, Any]) -> str:
    return (
        str(state.get("research_pipeline_report") or "").strip()
        or str(state.get("research_pipeline_synthesis") or "").strip()
        or str(state.get("research_result") or "").strip()
        or str(state.get("draft_response") or "").strip()
    )


def _match_research_synthesis(runtime: Any, state: dict[str, Any]) -> bool:
    return bool(
        not state.get("plan_steps")
        and not state.get("research_synthesis_done")
        and state.get("last_agent") in {"research_pipeline_agent", "deep_research_agent"}
        and runtime._is_agent_available(state, "worker_agent")
        and _research_body(state)
    )


def _build_research_synthesis_plan(runtime: Any, state: dict[str, Any]) -> WorkflowDispatchPlan:
    research_body = _research_body(state)
    original_query = str(state.get("user_query") or state.get("current_objective") or "").strip()
    synthesis_objective = (
        "You have been given the following research findings collected from the web. "
        "Write a comprehensive, well-structured, and easy-to-read final report that "
        "directly answers the user's query. Cite sources where available. Do not omit "
        "important details.\n\n"
        f"User's original query: {original_query}\n\n"
        f"Research findings:\n{research_body[:12000]}"
    )
    reason = (
        "Research collection complete. Routing to worker_agent to synthesize "
        "the findings into a final structured report."
    )
    return WorkflowDispatchPlan(
        workflow_id="research_synthesis",
        agent_name="worker_agent",
        reason=reason,
        intent="research-synthesis",
        content=synthesis_objective,
        state_updates={"current_objective": synthesis_objective},
        state_mutations={
            "research_synthesis_done": True,
            "current_objective": synthesis_objective,
        },
    )
