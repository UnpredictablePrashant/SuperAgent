from __future__ import annotations

import html
import json
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from kendr import AgentRuntime, build_registry
from kendr.http import (
    build_resume_state_overrides,
    infer_resume_working_directory,
    normalize_incoming_message,
    resume_candidate_requires_branch,
    resume_candidate_requires_force,
    resume_candidate_requires_reply,
    session_id_for_payload,
)
from kendr.orchestration import state_awaiting_user_input
from kendr.persistence import (
    get_run,
    get_task_session_by_run,
    list_channel_sessions,
    list_heartbeat_events,
    list_monitor_events,
    list_monitor_rules,
    list_privileged_audit_events,
    list_recent_runs,
    list_scheduled_jobs,
    list_task_sessions,
)
from kendr.persistence.run_store import scan_manifest_runs
from kendr.recovery import discover_resume_candidates, load_resume_candidate
from kendr.capability_registry import CapabilityRegistryService
from kendr.capability_sync import sync_mcp_capabilities
from kendr.openapi_importer import import_openapi_as_capabilities, parse_openapi_payload
from kendr.machine_index import machine_sync_status, run_machine_sync
from kendr.skill_manager import (
    get_marketplace,
    grant_skill_approval,
    install_catalog_skill,
    uninstall_catalog_skill,
    create_custom_skill,
    edit_custom_skill,
    list_skill_approval_grants,
    list_runtime_skills,
    remove_custom_skill,
    revoke_skill_approval,
    resolve_runtime_skill,
    test_skill,
)
from kendr.unicode_utils import safe_json_dumps, sanitize_text


REGISTRY = build_registry()
RUNTIME = AgentRuntime(REGISTRY)
CAPABILITY_REGISTRY = CapabilityRegistryService()
# NOTE: Always use RUNTIME.agent_routing (not a cached reference) so refreshes
# via _rebuild_skill_registry() / _refresh_mcp_agents() are reflected.
MAX_REGISTRY_QUERY_LIMIT = 10_000


def _rebuild_skill_registry() -> None:
    """Re-register skill agents in REGISTRY after install/uninstall/create/delete.

    Called after any skill mutation so the in-process registry stays in sync
    without requiring a full gateway restart.
    """
    try:
        from kendr.discovery import _register_skill_agents
        from kendr.agent_routing import build_agent_routing_index as _build_ar
        for name in list(REGISTRY.agents.keys()):
            if name.startswith("skill_") and name.endswith("_agent"):
                REGISTRY.agents.pop(name, None)
        REGISTRY.plugins.pop("builtin.skills", None)
        _register_skill_agents(REGISTRY)
        RUNTIME.agent_routing = _build_ar(REGISTRY)
    except Exception:
        pass


def _rebuild_mcp_registry() -> None:
    """Re-register MCP tool agents in REGISTRY after add/remove/toggle/discover.

    Mirrors _rebuild_skill_registry() so both connector types stay in sync
    without requiring a full gateway restart.
    """
    try:
        from kendr.discovery import _register_mcp_tools
        from kendr.agent_routing import build_agent_routing_index as _build_ar
        for name in list(REGISTRY.agents.keys()):
            if name.startswith("mcp_"):
                REGISTRY.agents.pop(name, None)
        REGISTRY.plugins.pop("builtin.mcp", None)
        _register_mcp_tools(REGISTRY)
        RUNTIME.agent_routing = _build_ar(REGISTRY)
    except Exception:
        pass


def _workspace_id_from_query(parsed) -> str:
    params = parse_qs(parsed.query or "")
    workspace_id = str((params.get("workspace_id") or params.get("workspace") or ["default"])[0] or "default").strip()
    return workspace_id or "default"


def _capability_discovery_snapshot(workspace_id: str) -> dict:
    sync_result = sync_mcp_capabilities(workspace_id=workspace_id, actor_user_id="system:gateway-discovery")
    capabilities = CAPABILITY_REGISTRY.list(workspace_id=workspace_id, limit=5000)
    active = [c for c in capabilities if str(c.get("status", "")).strip().lower() == "active"]
    by_type: dict[str, int] = {}
    for item in capabilities:
        ctype = str(item.get("type", "unknown")).strip() or "unknown"
        by_type[ctype] = by_type.get(ctype, 0) + 1
    return {
        "workspace_id": workspace_id,
        "summary": {
            "total": len(capabilities),
            "active": len(active),
            "by_type": by_type,
        },
        "sync": sync_result,
        "capabilities": capabilities,
        "agent_routing_summary": RUNTIME.agent_routing.summary(),
    }


def _capability_discovery_cards(workspace_id: str) -> list[dict]:
    snapshot = _capability_discovery_snapshot(workspace_id)
    cards = []
    for item in snapshot.get("capabilities", []):
        cards.append(
            {
                "id": item.get("id"),
                "type": item.get("type"),
                "key": item.get("key"),
                "name": item.get("name"),
                "description": item.get("description"),
                "status": item.get("status"),
                "health_status": item.get("health_status"),
                "visibility": item.get("visibility"),
                "version": item.get("version"),
                "tags": item.get("tags", []),
                "metadata": item.get("metadata", {}),
            }
        )
    return cards


def _task_session_summary(task_session: dict | None) -> dict:
    if not isinstance(task_session, dict):
        return {}
    summary = task_session.get("summary")
    if isinstance(summary, dict):
        return summary
    raw = task_session.get("summary_json")
    if isinstance(raw, str) and raw.strip():
        try:
            parsed = json.loads(raw)
        except Exception:
            return {}
        if isinstance(parsed, dict):
            return parsed
    return {}


def _run_log_paths(run_output_dir: str) -> dict[str, str]:
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


def _decorate_run_record(run_row: dict, task_session: dict | None = None) -> dict:
    row = dict(run_row or {})
    run_output_dir = str(row.get("run_output_dir", "")).strip()
    if run_output_dir:
        row["output_dir"] = run_output_dir
        row["log_paths"] = _run_log_paths(run_output_dir)
    if isinstance(task_session, dict):
        row["task_session"] = task_session
        summary = _task_session_summary(task_session)
        if summary:
            row["active_task"] = str(summary.get("active_task") or summary.get("objective") or row.get("active_task", "")).strip()
            row["pending_user_input_kind"] = str(summary.get("pending_user_input_kind") or row.get("pending_user_input_kind") or "").strip()
            row["approval_pending_scope"] = str(summary.get("approval_pending_scope") or row.get("approval_pending_scope") or "").strip()
            row["pending_user_question"] = str(summary.get("pending_user_question") or row.get("pending_user_question") or "").strip()
            summary_request = summary.get("approval_request")
            if isinstance(summary_request, dict):
                row["approval_request"] = summary_request
            summary_run_dir = str(summary.get("run_output_dir", "")).strip()
            if summary_run_dir and not run_output_dir:
                row["run_output_dir"] = summary_run_dir
                row["output_dir"] = summary_run_dir
                row["log_paths"] = _run_log_paths(summary_run_dir)
    awaiting = state_awaiting_user_input(row)
    if awaiting:
        row["awaiting_user_input"] = True
        row["status"] = "awaiting_user_input"
    else:
        row.pop("awaiting_user_input", None)
        if str(row.get("status") or "").strip().lower() == "awaiting_user_input":
            row["status"] = "completed" if str(row.get("completed_at") or "").strip() else "running"
    return row


def _is_cancelled_error(exc: Exception) -> bool:
    lowered = str(exc or "").strip().lower()
    return any(
        marker in lowered
        for marker in (
            "kill switch triggered",
            "run stopped by user",
            "stopped by user",
            "cancelled by user",
            "run cancelled",
            "run canceled",
        )
    )


def _html_page(title: str, body: str) -> bytes:
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>{html.escape(title)}</title>
  <style>
    body {{ font-family: Arial, sans-serif; margin: 32px; line-height: 1.5; }}
    .grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(320px, 1fr)); gap: 16px; }}
    .card {{ border: 1px solid #ddd; border-radius: 8px; padding: 16px; }}
    code, pre {{ background: #f5f5f5; border-radius: 6px; padding: 4px 6px; }}
    pre {{ white-space: pre-wrap; }}
  </style>
</head>
<body>
{body}
</body>
</html>""".encode("utf-8")


class GatewayHandler(BaseHTTPRequestHandler):
    def _send_json(self, status: int, payload: dict | list):
        body = safe_json_dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_html(self, status: int, title: str, body: str):
        page = _html_page(sanitize_text(title), sanitize_text(body))
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(page)))
        self.end_headers()
        self.wfile.write(page)

    def _read_json_body(self) -> tuple[dict | None, str]:
        try:
            content_length = int(self.headers.get("Content-Length", "0") or 0)
            raw = self.rfile.read(content_length)
            payload = json.loads(raw.decode("utf-8")) if raw else {}
            if not isinstance(payload, dict):
                return None, "JSON body must be an object."
            return payload, ""
        except Exception as exc:
            return None, str(exc)

    def do_GET(self):
        parsed = urlparse(self.path)
        if parsed.path == "/":
            self._handle_home()
            return
        if parsed.path == "/health":
            self._send_json(200, {"status": "ok"})
            return
        if parsed.path == "/api/machine/status":
            params = parse_qs(parsed.query or "")
            working_directory = str((params.get("working_directory") or [""])[0] or "").strip()
            if not working_directory:
                working_directory = str(Path.cwd().resolve())
            try:
                status = machine_sync_status(working_directory)
                self._send_json(200, {"working_directory": working_directory, "status": status})
            except Exception as exc:
                self._send_json(500, {"error": str(exc)})
            return
        if parsed.path == "/registry/skills":
            try:
                from kendr.skill_manager import get_marketplace as _get_marketplace
                _marketplace = _get_marketplace()
            except Exception:
                _marketplace = {"catalog": [], "custom": [], "categories": [], "installed_count": 0}
            self._send_json(200, {
                "catalog": _marketplace.get("catalog", []),
                "custom": _marketplace.get("custom", []),
                "categories": _marketplace.get("categories", []),
                "installed_count": _marketplace.get("installed_count", 0),
                "user_skills_prompt": RUNTIME.agent_routing.user_skills_prompt_block(),
                "agent_summary": RUNTIME.agent_routing.summary(),
            })
            return
        if parsed.path == "/registry/auth-profiles":
            workspace_id = _workspace_id_from_query(parsed)
            params = parse_qs(parsed.query or "")
            provider = str((params.get("provider") or [""])[0] or "").strip()
            limit = int(str((params.get("limit") or ["200"])[0] or "200"))
            items = CAPABILITY_REGISTRY.list_auth_profiles(
                workspace_id=workspace_id,
                provider=provider,
                limit=max(1, min(limit, MAX_REGISTRY_QUERY_LIMIT)),
            )
            self._send_json(200, {"workspace_id": workspace_id, "count": len(items), "items": items})
            return
        if parsed.path == "/registry/policy-profiles":
            workspace_id = _workspace_id_from_query(parsed)
            params = parse_qs(parsed.query or "")
            limit = int(str((params.get("limit") or ["200"])[0] or "200"))
            items = CAPABILITY_REGISTRY.list_policy_profiles(
                workspace_id=workspace_id,
                limit=max(1, min(limit, MAX_REGISTRY_QUERY_LIMIT)),
            )
            self._send_json(200, {"workspace_id": workspace_id, "count": len(items), "items": items})
            return
        if parsed.path == "/registry/capabilities":
            workspace_id = _workspace_id_from_query(parsed)
            params = parse_qs(parsed.query or "")
            capability_type = str((params.get("type") or [""])[0] or "").strip()
            status = str((params.get("status") or [""])[0] or "").strip()
            visibility = str((params.get("visibility") or [""])[0] or "").strip()
            search = str((params.get("q") or [""])[0] or "").strip()
            limit = int(str((params.get("limit") or ["200"])[0] or "200"))
            items = CAPABILITY_REGISTRY.list(
                workspace_id=workspace_id,
                capability_type=capability_type,
                status=status,
                visibility=visibility,
                search=search,
                limit=max(1, min(limit, MAX_REGISTRY_QUERY_LIMIT)),
            )
            self._send_json(200, {"workspace_id": workspace_id, "count": len(items), "items": items})
            return
        if parsed.path.startswith("/registry/capabilities/"):
            suffix = parsed.path.split("/registry/capabilities/", 1)[1].strip()
            capability_id, action = (suffix.split("/", 1) + [""])[:2] if "/" in suffix else (suffix, "")
            capability_id = capability_id.strip()
            action = action.strip().lower()
            if not capability_id:
                self._send_json(400, {"error": "missing_capability_id"})
                return
            workspace_id = _workspace_id_from_query(parsed)
            params = parse_qs(parsed.query or "")
            if action == "health":
                limit = int(str((params.get("limit") or ["50"])[0] or "50"))
                runs = CAPABILITY_REGISTRY.list_health_runs(
                    workspace_id=workspace_id,
                    capability_id=capability_id,
                    limit=max(1, min(limit, MAX_REGISTRY_QUERY_LIMIT)),
                )
                self._send_json(200, {"workspace_id": workspace_id, "capability_id": capability_id, "count": len(runs), "items": runs})
                return
            if action == "audit":
                limit = int(str((params.get("limit") or ["100"])[0] or "100"))
                events = CAPABILITY_REGISTRY.list_audit_events(
                    workspace_id=workspace_id,
                    capability_id=capability_id,
                    action=str((params.get("action") or [""])[0] or "").strip(),
                    limit=max(1, min(limit, MAX_REGISTRY_QUERY_LIMIT)),
                )
                self._send_json(200, {"workspace_id": workspace_id, "capability_id": capability_id, "count": len(events), "items": events})
                return
            item = CAPABILITY_REGISTRY.get(capability_id)
            if not item:
                self._send_json(404, {"error": "capability_not_found", "capability_id": capability_id})
                return
            self._send_json(200, item)
            return
        if parsed.path == "/registry/discovery":
            workspace_id = _workspace_id_from_query(parsed)
            self._send_json(200, _capability_discovery_snapshot(workspace_id))
            return
        if parsed.path == "/registry/discovery/cards":
            workspace_id = _workspace_id_from_query(parsed)
            cards = _capability_discovery_cards(workspace_id)
            self._send_json(200, {"workspace_id": workspace_id, "cards": cards, "count": len(cards)})
            return
        if parsed.path == "/registry/plan":
            plan = getattr(RUNTIME, "_live_plan_data", {}) or {}
            steps = plan.get("execution_steps") or plan.get("steps") or []
            total = len(steps)
            completed = sum(1 for s in steps if isinstance(s, dict) and s.get("status") == "completed")
            running_count = sum(1 for s in steps if isinstance(s, dict) and s.get("status") == "running")
            failed_count = sum(1 for s in steps if isinstance(s, dict) and s.get("status") == "failed")
            self._send_json(200, {
                "has_plan": bool(plan),
                "summary": plan.get("summary", ""),
                "total_steps": total,
                "completed_steps": completed,
                "running_steps": running_count,
                "failed_steps": failed_count,
                "steps": steps,
            })
            return
        if parsed.path == "/registry/agents":
            self._send_json(
                200,
                [
                    {
                        "name": agent.name,
                        "description": agent.description,
                        "plugin": agent.plugin_name,
                        "skills": agent.skills,
                    }
                    for agent in REGISTRY.agents.values()
                ],
            )
            return
        if parsed.path in {"/registry/integrations", "/registry/plugins"}:
            try:
                from kendr.integration_registry import list_integrations as _list_integrations

                _integration_cards = [item.to_dict() for item in _list_integrations()]
            except Exception:
                _integration_cards = []
            self._send_json(200, _integration_cards)
            return
        # ── Unified connector catalog ──────────────────────────────────────────
        if parsed.path == "/registry/connectors":
            try:
                from kendr.connector_registry import (
                    build_connector_catalog as _build_catalog,
                    build_integration_catalog as _build_integrations,
                )
                _specs = _build_catalog(REGISTRY, RUNTIME.agent_routing)
                _integration_specs = _build_integrations()
                _all = _specs + _integration_specs
                _by_type = {
                    t: [s.to_dict() for s in _all if s.connector_type == t]
                    for t in ("task_agent", "skill", "mcp_tool", "integration")
                }
                _by_type["plugin"] = list(_by_type["integration"])
                self._send_json(200, {
                    "total": len(_all),
                    "connectors": [s.to_dict() for s in _all],
                    "by_type": _by_type,
                })
            except Exception as exc:
                self._send_json(500, {"error": str(exc)})
            return
        # ── MCP server management ──────────────────────────────────────────────
        if parsed.path == "/api/connectors/mcp":
            from kendr.mcp_manager import list_servers_safe as _ls
            try:
                self._send_json(200, {"servers": _ls()})
            except Exception as exc:
                self._send_json(500, {"error": str(exc)})
            return
        if parsed.path.startswith("/api/connectors/mcp/") and parsed.path.endswith("/tools"):
            _sid = parsed.path.split("/api/connectors/mcp/", 1)[1].rsplit("/tools", 1)[0].strip()
            try:
                from kendr.mcp_manager import get_server as _get_srv
                _srv = _get_srv(_sid)
                if not _srv:
                    self._send_json(404, {"error": "server_not_found"})
                    return
                import json as _json
                _tools = _srv.get("tools") or []
                if isinstance(_tools, str):
                    try:
                        _tools = _json.loads(_tools)
                    except Exception:
                        _tools = []
                self._send_json(200, {"server_id": _sid, "tools": _tools})
            except Exception as exc:
                self._send_json(500, {"error": str(exc)})
            return
        if parsed.path == "/runs":
            api_limit = max(100, int(str(os.getenv("KENDR_RUNS_API_LIMIT", "500") or "500")))
            db_runs = list_recent_runs(api_limit)
            known_ids = {r["run_id"] for r in db_runs}
            manifest_runs = scan_manifest_runs(known_run_ids=known_ids)
            all_runs = db_runs + manifest_runs
            task_sessions = list_task_sessions(max(api_limit, 500))
            task_by_run: dict[str, dict] = {}
            for session in task_sessions:
                run_id = str(session.get("run_id", "")).strip()
                if run_id and run_id not in task_by_run:
                    task_by_run[run_id] = session
            all_runs = [
                _decorate_run_record(run, task_by_run.get(str(run.get("run_id", "")).strip()))
                for run in all_runs
                if isinstance(run, dict)
            ]
            all_runs.sort(
                key=lambda r: str(r.get("updated_at") or r.get("started_at") or ""),
                reverse=True,
            )
            self._send_json(200, all_runs[:api_limit])
            return
        if parsed.path.startswith("/runs/"):
            run_id = parsed.path.split("/runs/", 1)[1].strip()
            if not run_id:
                self._send_json(400, {"error": "missing_run_id"})
                return
            match = get_run(run_id)
            if not match:
                manifest_list = scan_manifest_runs(known_run_ids=set())
                match = next((r for r in manifest_list if r.get("run_id") == run_id), None)
            if not match:
                self._send_json(404, {"error": "run_not_found", "run_id": run_id})
                return
            task_session = get_task_session_by_run(run_id)
            self._send_json(200, _decorate_run_record(match, task_session if isinstance(task_session, dict) else None))
            return
        if parsed.path == "/resume-candidates":
            params = parse_qs(parsed.query or "")
            search_path = str((params.get("path") or [""])[0] or "").strip()
            if not search_path:
                self._send_json(400, {"error": "missing_path", "detail": "Provide ?path=<output-folder-or-working-directory>."})
                return
            limit = int(str((params.get("limit") or ["20"])[0] or "20"))
            self._send_json(200, discover_resume_candidates(search_path, limit=limit))
            return
        if parsed.path == "/sessions":
            self._send_json(200, list_channel_sessions(500))
            return
        if parsed.path == "/jobs":
            self._send_json(200, list_scheduled_jobs())
            return
        if parsed.path == "/task-sessions":
            self._send_json(200, list_task_sessions(500))
            return
        if parsed.path.startswith("/task-sessions/by-run/"):
            run_id = parsed.path.split("/task-sessions/by-run/", 1)[1].strip()
            if not run_id:
                self._send_json(400, {"error": "missing_run_id"})
                return
            session = get_task_session_by_run(run_id)
            if not session:
                self._send_json(404, {"error": "task_session_not_found", "run_id": run_id})
                return
            self._send_json(200, session)
            return
        if parsed.path == "/monitors":
            self._send_json(200, list_monitor_rules())
            return
        if parsed.path == "/monitor-events":
            self._send_json(200, list_monitor_events())
            return
        if parsed.path == "/heartbeats":
            self._send_json(200, list_heartbeat_events())
            return
        if parsed.path == "/audit/privileged":
            self._send_json(200, list_privileged_audit_events())
            return
        # ── Skill Marketplace ──────────────────────────────────────────────
        if parsed.path == "/api/marketplace/skills":
            params = parse_qs(parsed.query or "")
            q = str((params.get("q") or [""])[0] or "").strip()
            category = str((params.get("category") or [""])[0] or "").strip()
            try:
                result = get_marketplace(q=q, category=category)
                self._send_json(200, result)
            except Exception as exc:
                self._send_json(500, {"error": str(exc)})
            return
        if parsed.path == "/api/marketplace/skills/installed":
            try:
                rows = list_runtime_skills()
                self._send_json(200, {"items": rows, "count": len(rows)})
            except Exception as exc:
                self._send_json(500, {"error": str(exc)})
            return
        if parsed.path.startswith("/api/marketplace/skills/"):
            skill_id = parsed.path.split("/api/marketplace/skills/", 1)[1].strip()
            if skill_id.endswith("/approvals"):
                resolved_skill_id = skill_id.rsplit("/approvals", 1)[0].strip()
                params = parse_qs(parsed.query or "")
                session_id = str((params.get("session_id") or [""])[0] or "").strip()
                status = str((params.get("status") or [""])[0] or "").strip()
                items = list_skill_approval_grants(skill_id=resolved_skill_id, session_id=session_id, status=status)
                self._send_json(200, {"items": items, "count": len(items)})
                return
            if skill_id:
                row = resolve_runtime_skill(skill_id=skill_id)
                if row:
                    self._send_json(200, row)
                else:
                    self._send_json(404, {"error": "not_found", "skill_id": skill_id})
                return
        self._send_json(404, {"error": "not_found"})

    def do_DELETE(self):
        parsed = urlparse(self.path)
        # ── DELETE /api/connectors/mcp/{id} ───────────────────────────────────
        if parsed.path.startswith("/api/connectors/mcp/"):
            _sid = parsed.path.split("/api/connectors/mcp/", 1)[1].strip()
            if not _sid:
                self._send_json(400, {"error": "missing_server_id"})
                return
            try:
                from kendr.mcp_manager import remove_server as _rm
                ok = _rm(_sid)
                if ok:
                    _rebuild_mcp_registry()
                self._send_json(200, {"ok": ok})
            except Exception as exc:
                self._send_json(500, {"error": str(exc)})
            return
        self._send_json(404, {"error": "not_found"})

    def do_POST(self):
        if self.path == "/api/machine/sync":
            payload, err = self._read_json_body()
            if payload is None:
                self._send_json(400, {"error": "invalid_json", "detail": err})
                return
            working_directory = str(payload.get("working_directory", "") or "").strip()
            if not working_directory:
                working_directory = str(Path.cwd().resolve())
            scope = str(payload.get("scope", "machine") or "machine").strip().lower()
            roots = payload.get("roots")
            if not isinstance(roots, list):
                roots = []
            try:
                result = run_machine_sync(
                    working_directory=working_directory,
                    scope=scope,
                    roots=[str(item) for item in roots if str(item).strip()],
                    max_files=int(payload.get("max_files", 250000) or 250000),
                )
                self._send_json(200, result)
            except Exception as exc:
                self._send_json(500, {"error": str(exc)})
            return
        # ── MCP server CRUD ────────────────────────────────────────────────────
        # POST /api/connectors/mcp  → add a new MCP server
        if self.path == "/api/connectors/mcp":
            payload, err = self._read_json_body()
            if payload is None:
                self._send_json(400, {"error": "invalid_json", "detail": err})
                return
            name = str(payload.get("name", "")).strip()
            connection = str(payload.get("connection", "")).strip()
            if not name or not connection:
                self._send_json(400, {"error": "name and connection are required"})
                return
            try:
                from kendr.mcp_manager import add_server as _add_srv
                server = _add_srv(
                    name=name,
                    connection=connection,
                    server_type=str(payload.get("type", "http")).strip() or "http",
                    description=str(payload.get("description", "")).strip(),
                    auth_token=str(payload.get("auth_token", "")).strip(),
                    enabled=bool(payload.get("enabled", True)),
                )
                _rebuild_mcp_registry()
                self._send_json(200, {"ok": True, "server": server})
            except Exception as exc:
                self._send_json(500, {"ok": False, "error": str(exc)})
            return
        # POST /api/connectors/mcp/{id}/discover  → discover tools for server
        if self.path.startswith("/api/connectors/mcp/") and self.path.endswith("/discover"):
            _sid = self.path.split("/api/connectors/mcp/", 1)[1].rsplit("/discover", 1)[0].strip()
            try:
                from kendr.mcp_manager import discover_tools as _discover
                result = _discover(_sid)
                _rebuild_mcp_registry()
                self._send_json(200, result)
            except Exception as exc:
                self._send_json(500, {"ok": False, "error": str(exc)})
            return
        # POST /api/connectors/mcp/{id}/toggle  → enable / disable server
        if self.path.startswith("/api/connectors/mcp/") and self.path.endswith("/toggle"):
            _sid = self.path.split("/api/connectors/mcp/", 1)[1].rsplit("/toggle", 1)[0].strip()
            payload, err = self._read_json_body()
            if payload is None:
                self._send_json(400, {"error": "invalid_json", "detail": err})
                return
            try:
                from kendr.mcp_manager import toggle_server as _toggle
                ok = _toggle(_sid, bool(payload.get("enabled", True)))
                _rebuild_mcp_registry()
                self._send_json(200, {"ok": ok})
            except Exception as exc:
                self._send_json(500, {"ok": False, "error": str(exc)})
            return
        if self.path == "/registry/mcp-refresh":
            try:
                stale_before = [n for n in REGISTRY.agents if n.startswith("mcp_")]
                _rebuild_mcp_registry()
                mcp_agents = [n for n in REGISTRY.agents if n.startswith("mcp_")]
                sync_result = sync_mcp_capabilities(workspace_id="default", actor_user_id="system:gateway-mcp-refresh")
                self._send_json(200, {
                    "ok": True,
                    "mcp_agent_count": len(mcp_agents),
                    "removed_stale": len(stale_before),
                    "capability_sync": sync_result,
                })
            except Exception as exc:
                self._send_json(500, {"ok": False, "error": str(exc)})
            return
        if self.path == "/registry/auth-profiles":
            payload, err = self._read_json_body()
            if payload is None:
                self._send_json(400, {"error": "invalid_json", "detail": err})
                return
            workspace_id = str(payload.get("workspace_id", "default") or "default").strip() or "default"
            auth_type = str(payload.get("auth_type", "")).strip()
            provider = str(payload.get("provider", "")).strip()
            secret_ref = str(payload.get("secret_ref", "")).strip()
            if not (auth_type and provider and secret_ref):
                self._send_json(
                    400,
                    {"error": "missing_required_fields", "detail": "auth_type, provider, and secret_ref are required."},
                )
                return
            result = CAPABILITY_REGISTRY.create_auth_profile(
                workspace_id=workspace_id,
                auth_type=auth_type,
                provider=provider,
                secret_ref=secret_ref,
                scopes=payload.get("scopes", []) if isinstance(payload.get("scopes", []), list) else [],
                metadata=payload.get("metadata", {}) if isinstance(payload.get("metadata", {}), dict) else {},
            )
            self._send_json(200, {"ok": True, "auth_profile": result})
            return
        if self.path == "/registry/policy-profiles":
            payload, err = self._read_json_body()
            if payload is None:
                self._send_json(400, {"error": "invalid_json", "detail": err})
                return
            workspace_id = str(payload.get("workspace_id", "default") or "default").strip() or "default"
            name = str(payload.get("name", "")).strip()
            rules = payload.get("rules", {}) if isinstance(payload.get("rules", {}), dict) else {}
            if not name:
                self._send_json(400, {"error": "missing_required_fields", "detail": "name is required."})
                return
            result = CAPABILITY_REGISTRY.create_policy_profile(
                workspace_id=workspace_id,
                name=name,
                rules=rules,
            )
            self._send_json(200, {"ok": True, "policy_profile": result})
            return
        if self.path == "/registry/capabilities":
            payload, err = self._read_json_body()
            if payload is None:
                self._send_json(400, {"error": "invalid_json", "detail": err})
                return
            try:
                workspace_id = str(payload.get("workspace_id", "default") or "default").strip() or "default"
                actor_user_id = str(payload.get("actor_user_id", "system:gateway") or "system:gateway").strip()
                result = CAPABILITY_REGISTRY.create(
                    workspace_id=workspace_id,
                    capability_type=str(payload.get("type", "")).strip(),
                    key=str(payload.get("key", "")).strip(),
                    name=str(payload.get("name", "")).strip(),
                    description=str(payload.get("description", "")).strip(),
                    owner_user_id=str(payload.get("owner_user_id", actor_user_id) or actor_user_id).strip(),
                    visibility=str(payload.get("visibility", "workspace") or "workspace").strip(),
                    status=str(payload.get("status", "draft") or "draft").strip(),
                    version=int(payload.get("version", 1) or 1),
                    tags=payload.get("tags", []) if isinstance(payload.get("tags", []), list) else [],
                    metadata=payload.get("metadata", {}) if isinstance(payload.get("metadata", {}), dict) else {},
                    schema_in=payload.get("schema_in", {}) if isinstance(payload.get("schema_in", {}), dict) else {},
                    schema_out=payload.get("schema_out", {}) if isinstance(payload.get("schema_out", {}), dict) else {},
                    auth_profile_id=str(payload.get("auth_profile_id", "")).strip(),
                    policy_profile_id=str(payload.get("policy_profile_id", "")).strip(),
                )
                self._send_json(200, {"ok": True, "capability": result})
            except Exception as exc:
                self._send_json(400, {"ok": False, "error": str(exc)})
            return
        if self.path.startswith("/registry/capabilities/"):
            suffix = self.path.split("/registry/capabilities/", 1)[1].strip()
            if not suffix:
                self._send_json(400, {"error": "missing_capability_id"})
                return
            if "/" in suffix:
                capability_id, action = suffix.split("/", 1)
                action = action.strip().lower()
            else:
                capability_id, action = suffix, ""
            capability_id = capability_id.strip()
            if not capability_id:
                self._send_json(400, {"error": "missing_capability_id"})
                return
            payload, err = self._read_json_body()
            if payload is None:
                self._send_json(400, {"error": "invalid_json", "detail": err})
                return
            workspace_id = str(payload.get("workspace_id", "default") or "default").strip() or "default"
            actor_user_id = str(payload.get("actor_user_id", "system:gateway") or "system:gateway").strip()
            try:
                if action == "publish":
                    result = CAPABILITY_REGISTRY.publish(capability_id, workspace_id=workspace_id, actor_user_id=actor_user_id)
                elif action == "disable":
                    result = CAPABILITY_REGISTRY.disable(capability_id, workspace_id=workspace_id, actor_user_id=actor_user_id)
                elif action == "verify":
                    result = CAPABILITY_REGISTRY.verify(capability_id, workspace_id=workspace_id, actor_user_id=actor_user_id)
                elif action == "health-check":
                    result = CAPABILITY_REGISTRY.record_health(
                        capability_id,
                        workspace_id=workspace_id,
                        actor_user_id=actor_user_id,
                        status=str(payload.get("status", "healthy") or "healthy"),
                        latency_ms=payload.get("latency_ms", None),
                        error=str(payload.get("error", "") or ""),
                    )
                elif action == "update":
                    allowed = {
                        "name",
                        "description",
                        "status",
                        "visibility",
                        "tags",
                        "metadata",
                        "schema_in",
                        "schema_out",
                        "auth_profile_id",
                        "policy_profile_id",
                    }
                    updates = {k: v for k, v in payload.items() if k in allowed}
                    result = CAPABILITY_REGISTRY.update(
                        capability_id,
                        actor_user_id=actor_user_id,
                        workspace_id=workspace_id,
                        **updates,
                    )
                else:
                    self._send_json(404, {"error": "not_found"})
                    return
            except Exception as exc:
                self._send_json(400, {"ok": False, "error": str(exc)})
                return
            if not result:
                self._send_json(404, {"error": "capability_not_found", "capability_id": capability_id})
                return
            self._send_json(200, {"ok": True, "capability": result})
            return
        if self.path == "/registry/apis/import-openapi":
            payload, err = self._read_json_body()
            if payload is None:
                self._send_json(400, {"error": "invalid_json", "detail": err})
                return
            try:
                openapi_spec = parse_openapi_payload(
                    spec=payload.get("openapi") if isinstance(payload.get("openapi"), dict) else None,
                    spec_text=str(payload.get("openapi_text", "")).strip(),
                )
            except Exception as exc:
                self._send_json(400, {"error": "invalid_openapi", "detail": str(exc)})
                return
            workspace_id = str(payload.get("workspace_id", "default") or "default").strip() or "default"
            owner_user_id = str(payload.get("owner_user_id", "system:gateway-openapi") or "system:gateway-openapi").strip()
            try:
                result = import_openapi_as_capabilities(
                    workspace_id=workspace_id,
                    owner_user_id=owner_user_id,
                    openapi_spec=openapi_spec,
                    auth_profile_id=str(payload.get("auth_profile_id", "")).strip(),
                    policy_profile_id=str(payload.get("policy_profile_id", "")).strip(),
                    visibility=str(payload.get("visibility", "workspace") or "workspace").strip(),
                    status=str(payload.get("status", "draft") or "draft").strip(),
                )
                self._send_json(200, {"ok": True, "import_result": result})
            except Exception as exc:
                self._send_json(500, {"ok": False, "error": str(exc)})
            return
        # ── Skill Marketplace POST routes ──────────────────────────────────────
        if self.path == "/api/marketplace/skills/create":
            payload, err = self._read_json_body()
            if payload is None:
                self._send_json(400, {"error": "invalid_json", "detail": err})
                return
            try:
                skill = create_custom_skill(
                    name=str(payload.get("name", "")).strip(),
                    description=str(payload.get("description", "")).strip(),
                    category=str(payload.get("category", "Custom")).strip() or "Custom",
                    icon=str(payload.get("icon", "⚡")).strip() or "⚡",
                    skill_type=str(payload.get("skill_type", "python")).strip(),
                    code=str(payload.get("code", "")).strip(),
                    input_schema=payload.get("input_schema") if isinstance(payload.get("input_schema"), dict) else None,
                    output_schema=payload.get("output_schema") if isinstance(payload.get("output_schema"), dict) else None,
                    tags=payload.get("tags") if isinstance(payload.get("tags"), list) else None,
                    metadata=payload.get("metadata") if isinstance(payload.get("metadata"), dict) else None,
                    permissions=payload.get("permissions") if isinstance(payload.get("permissions"), dict) else None,
                )
                _rebuild_skill_registry()
                self._send_json(200, {"ok": True, "skill": skill})
            except Exception as exc:
                self._send_json(400, {"ok": False, "error": str(exc)})
            return
        if self.path.startswith("/api/marketplace/skills/") and self.path.endswith("/install"):
            catalog_id = self.path.split("/api/marketplace/skills/", 1)[1].rsplit("/install", 1)[0].strip()
            try:
                skill = install_catalog_skill(catalog_id)
                _rebuild_skill_registry()
                self._send_json(200, {"ok": True, "skill": skill})
            except Exception as exc:
                self._send_json(400, {"ok": False, "error": str(exc)})
            return
        if self.path.startswith("/api/marketplace/skills/") and self.path.endswith("/uninstall"):
            catalog_id = self.path.split("/api/marketplace/skills/", 1)[1].rsplit("/uninstall", 1)[0].strip()
            try:
                ok = uninstall_catalog_skill(catalog_id)
                _rebuild_skill_registry()
                self._send_json(200, {"ok": ok})
            except Exception as exc:
                self._send_json(400, {"ok": False, "error": str(exc)})
            return
        if self.path.startswith("/api/marketplace/skills/") and self.path.endswith("/test"):
            skill_id = self.path.split("/api/marketplace/skills/", 1)[1].rsplit("/test", 1)[0].strip()
            payload, err = self._read_json_body()
            if payload is None:
                self._send_json(400, {"error": "invalid_json", "detail": err})
                return
            try:
                result = test_skill(
                    skill_id,
                    payload.get("inputs", payload),
                    approval=payload.get("approval") if isinstance(payload.get("approval"), dict) else None,
                    session_id=str(payload.get("session_id", "") or "").strip(),
                )
                if result.get("error_type") == "approval_required":
                    self._send_json(409, result)
                else:
                    self._send_json(200, result)
            except Exception as exc:
                self._send_json(500, {"success": False, "error": str(exc)})
            return
        if self.path.startswith("/api/marketplace/skills/") and self.path.endswith("/approve"):
            skill_id = self.path.split("/api/marketplace/skills/", 1)[1].rsplit("/approve", 1)[0].strip()
            payload, err = self._read_json_body()
            if payload is None:
                self._send_json(400, {"error": "invalid_json", "detail": err})
                return
            try:
                grant = grant_skill_approval(
                    skill_id=skill_id,
                    scope=str(payload.get("scope", "once") or "once").strip(),
                    note=str(payload.get("note", "") or "").strip(),
                    actor=str(payload.get("actor", "user") or "user").strip(),
                    session_id=str(payload.get("session_id", "") or "").strip(),
                )
                self._send_json(200, {"ok": True, "grant": grant})
            except Exception as exc:
                self._send_json(400, {"ok": False, "error": str(exc)})
            return
        if self.path.startswith("/api/marketplace/skills/") and self.path.endswith("/revoke-approval"):
            skill_id = self.path.split("/api/marketplace/skills/", 1)[1].rsplit("/revoke-approval", 1)[0].strip()
            payload, err = self._read_json_body()
            if payload is None:
                self._send_json(400, {"error": "invalid_json", "detail": err})
                return
            grant_id = str(payload.get("grant_id", "") or "").strip()
            if not skill_id or not grant_id:
                self._send_json(400, {"ok": False, "error": "grant_id_required"})
                return
            grant = revoke_skill_approval(grant_id=grant_id)
            if grant:
                self._send_json(200, {"ok": True, "grant": grant})
            else:
                self._send_json(404, {"ok": False, "error": "grant_not_found"})
            return
        if self.path.startswith("/api/marketplace/skills/") and self.path.endswith("/edit"):
            skill_id = self.path.split("/api/marketplace/skills/", 1)[1].rsplit("/edit", 1)[0].strip()
            payload, err = self._read_json_body()
            if payload is None:
                self._send_json(400, {"error": "invalid_json", "detail": err})
                return
            try:
                allowed = {"name", "description", "category", "icon", "code", "input_schema", "output_schema", "tags", "status", "metadata"}
                updates = {k: v for k, v in payload.items() if k in allowed}
                if isinstance(payload.get("permissions"), dict):
                    updates["permissions"] = payload.get("permissions")
                skill = edit_custom_skill(skill_id, **updates)
                if skill:
                    self._send_json(200, {"ok": True, "skill": skill})
                else:
                    self._send_json(404, {"ok": False, "error": "skill_not_found"})
            except Exception as exc:
                self._send_json(400, {"ok": False, "error": str(exc)})
            return
        if self.path.startswith("/api/marketplace/skills/") and self.path.endswith("/delete"):
            skill_id = self.path.split("/api/marketplace/skills/", 1)[1].rsplit("/delete", 1)[0].strip()
            try:
                ok = remove_custom_skill(skill_id)
                _rebuild_skill_registry()
                self._send_json(200, {"ok": ok})
            except Exception as exc:
                self._send_json(400, {"ok": False, "error": str(exc)})
            return
        if self.path not in {"/ingest", "/resume"}:
            self._send_json(404, {"error": "not_found"})
            return
        try:
            content_length = int(self.headers.get("Content-Length", "0") or 0)
            raw = self.rfile.read(content_length)
            payload = json.loads(raw.decode("utf-8")) if raw else {}
            if not isinstance(payload, dict):
                raise ValueError("JSON body must be an object.")
        except Exception as exc:
            self._send_json(400, {"error": "invalid_json", "detail": str(exc)})
            return

        if self.path == "/resume":
            search_path = str(
                payload.get("output_folder")
                or payload.get("working_directory")
                or payload.get("path")
                or ""
            ).strip()
            if not search_path:
                self._send_json(400, {"error": "missing_path", "detail": "Provide output_folder, working_directory, or path."})
                return
            candidate = load_resume_candidate(search_path)
            if not candidate:
                self._send_json(404, {"error": "resume_candidate_not_found", "path": search_path})
                return

            branch = bool(payload.get("branch", False))
            force = bool(payload.get("force", False))
            if resume_candidate_requires_branch(candidate, branch=branch):
                self._send_json(409, {"error": "completed_run_requires_branch", "candidate": candidate})
                return
            if resume_candidate_requires_force(candidate, force=force):
                self._send_json(409, {"error": "takeover_required", "candidate": candidate})
                return
            if resume_candidate_requires_reply(candidate):
                pending_text = str(payload.get("reply") or payload.get("text") or "").strip()
                if not pending_text:
                    self._send_json(409, {"error": "reply_required", "candidate": candidate})
                    return
                text = pending_text
            else:
                text = str(payload.get("text") or payload.get("message") or payload.get("user_query") or "").strip() or "resume"

            working_directory = infer_resume_working_directory(candidate)
            if not working_directory:
                self._send_json(400, {"error": "working_directory_required", "candidate": candidate})
                return

            state_overrides = build_resume_state_overrides(
                candidate,
                branch=branch,
                working_directory=working_directory,
                incoming_channel=str(payload.get("channel", "webchat") or "webchat"),
                incoming_sender_id=str(payload.get("sender_id", "") or ""),
                incoming_chat_id=str(payload.get("chat_id", "") or ""),
                incoming_workspace_id=str(payload.get("workspace_id", "") or ""),
                incoming_is_group=bool(payload.get("is_group", False)),
            )
        else:
            text = str(payload.get("text") or payload.get("message") or payload.get("user_query") or "").strip()
            if not text:
                self._send_json(400, {"error": "missing_text", "detail": "Provide text, message, or user_query."})
                return
        force_new_session = bool(payload.get("new_session", False) or text.lower() == "/new")
        if text.lower() == "/new":
            text = str(payload.get("next_text") or "Started a new session.")
        working_directory = str(
            (state_overrides.get("working_directory", "") if self.path == "/resume" else payload.get("working_directory"))
            or os.getenv("KENDR_WORKING_DIR", "")
        ).strip()
        if not working_directory:
            self._send_json(
                400,
                {
                    "error": "working_directory_required",
                    "detail": (
                        "Working folder is required before tasks can run. "
                        "Configure KENDR_WORKING_DIR in Setup UI (Core Runtime) "
                        "or send working_directory in this request."
                    ),
                    "setup_url": "/component/core_runtime",
                },
            )
            return

        if self.path != "/resume":
            # use_mcp: pass through as-is (None = default = MCP enabled; False = disable mcp_* agents)
            _use_mcp_raw = payload.get("use_mcp")
            _use_mcp = None if _use_mcp_raw is None else bool(_use_mcp_raw)
            state_overrides = {
                "run_id": str(payload.get("run_id", "")).strip(),
                "workflow_id": str(payload.get("workflow_id", "")).strip() or str(payload.get("run_id", "")).strip(),
                "attempt_id": str(payload.get("attempt_id", "")).strip() or str(payload.get("run_id", "")).strip(),
                "workflow_type": str(payload.get("workflow_type", "")).strip(),
                "max_steps": int(payload.get("max_steps", 20)),
                "incoming_channel": payload.get("channel", "webchat"),
                "incoming_sender_id": payload.get("sender_id", ""),
                "incoming_chat_id": payload.get("chat_id", ""),
                "incoming_workspace_id": payload.get("workspace_id", ""),
                "incoming_text": text,
                "incoming_is_group": bool(payload.get("is_group", False)),
                "incoming_mentions_assistant": bool(payload.get("mentions_assistant", False)),
                "incoming_payload": payload,
                "session_id": session_id_for_payload(payload, force_new=force_new_session),
                "channel_session_key": session_id_for_payload(payload, force_new=False),
                "memory_force_new_session": force_new_session,
                "working_directory": working_directory,
                **({} if _use_mcp is None else {"use_mcp": _use_mcp}),
            }
        else:
            state_overrides["max_steps"] = int(payload.get("max_steps", 20))
            state_overrides["incoming_text"] = text
            state_overrides["incoming_mentions_assistant"] = bool(payload.get("mentions_assistant", False))
            state_overrides["incoming_payload"] = payload
            explicit_workflow_id = str(payload.get("workflow_id", "")).strip()
            explicit_attempt_id = str(payload.get("attempt_id", "")).strip()
            explicit_run_id = str(payload.get("run_id", "")).strip()
            if explicit_workflow_id:
                state_overrides["workflow_id"] = explicit_workflow_id
            elif explicit_run_id and not str(state_overrides.get("workflow_id", "")).strip():
                state_overrides["workflow_id"] = explicit_run_id
            if explicit_attempt_id:
                state_overrides["attempt_id"] = explicit_attempt_id
            elif explicit_run_id and not str(state_overrides.get("attempt_id", "")).strip():
                state_overrides["attempt_id"] = explicit_run_id
            if explicit_run_id:
                state_overrides["run_id"] = explicit_run_id
            explicit_workflow_type = str(payload.get("workflow_type", "")).strip()
            if explicit_workflow_type:
                state_overrides["workflow_type"] = explicit_workflow_type
            if not str(state_overrides.get("session_id", "")).strip():
                state_overrides["session_id"] = session_id_for_payload(
                    payload,
                    force_new=bool(state_overrides.get("memory_force_new_session", False)),
                )
            if not str(state_overrides.get("channel_session_key", "")).strip():
                state_overrides["channel_session_key"] = session_id_for_payload(payload, force_new=False)
        normalized_channel = normalize_incoming_message(
            payload,
            channel=str(state_overrides.get("incoming_channel") or payload.get("channel") or "webchat"),
            sender_id=str(state_overrides.get("incoming_sender_id") or payload.get("sender_id") or ""),
            chat_id=str(state_overrides.get("incoming_chat_id") or payload.get("chat_id") or ""),
            workspace_id=str(state_overrides.get("incoming_workspace_id") or payload.get("workspace_id") or ""),
            text=text,
            is_group=bool(state_overrides.get("incoming_is_group", payload.get("is_group", False))),
            mentions_assistant=bool(state_overrides.get("incoming_mentions_assistant", payload.get("mentions_assistant", False))),
            force_activate=bool(payload.get("gateway_force_activate", False)),
        )
        if (
            normalized_channel.get("channel") in {"webchat", "project_ui"}
            and not bool(payload.get("force_channel_gateway_agent", False))
        ):
            state_overrides["gateway_message"] = normalized_channel
        if not str(state_overrides.get("run_id", "")).strip():
            state_overrides.pop("run_id", None)
        passthrough_keys = [
            "provider",
            "model",
            "privileged_mode",
            "privileged_approved",
            "privileged_approval_note",
            "privileged_approval_mode",
            "privileged_require_approvals",
            "privileged_read_only",
            "privileged_allow_root",
            "privileged_allow_destructive",
            "privileged_enable_backup",
            "privileged_allowed_paths",
            "privileged_allowed_domains",
            "kill_switch_file",
            "shell_auto_approve",
            "auto_approve",
            "auto_approve_blueprint",
            "auto_approve_plan",
            "skip_reviews",
            "max_step_revisions",
            "adaptive_agent_selection",
            "execution_mode",
            "planner_policy_mode",
            "reviewer_policy_mode",
            "planner_mode",
            "reviewer_mode",
            "planner_score_threshold",
            "reviewer_score_threshold",
            "deep_research_mode",
            "deep_research_confirmed",
            "deep_research_source_urls",
            "long_document_mode",
            "long_document_pages",
            "long_document_sections",
            "long_document_section_pages",
            "long_document_title",
            "long_document_collect_sources_first",
            "long_document_disable_visuals",
            "long_document_section_search",
            "long_document_section_search_results",
            "research_max_wait_seconds",
            "research_poll_interval_seconds",
            "research_max_tool_calls",
            "research_max_output_tokens",
            "research_model",
            "research_instructions",
            "research_heartbeat_seconds",
            "research_output_formats",
            "research_citation_style",
            "research_enable_plagiarism_check",
            "research_web_search_enabled",
            "research_search_backend",
            "research_date_range",
            "research_max_sources",
            "research_checkpoint_enabled",
            "research_kb_enabled",
            "research_kb_id",
            "research_kb_top_k",
            "local_drive_paths",
            "local_drive_recursive",
            "local_drive_include_hidden",
            "local_drive_max_files",
            "local_drive_extensions",
            "local_drive_enable_image_ocr",
            "local_drive_ocr_instruction",
            "local_drive_working_directory",
            "local_drive_index_to_memory",
            "local_drive_auto_generate_extension_handlers",
            "local_drive_force_long_document",
            "codebase_mode",
            "superrag_mode",
            "superrag_action",
            "superrag_session_id",
            "superrag_new_session",
            "superrag_session_title",
            "superrag_local_paths",
            "superrag_paths",
            "superrag_local_recursive",
            "superrag_local_include_hidden",
            "superrag_local_max_files",
            "superrag_local_extensions",
            "superrag_include_working_directory",
            "superrag_urls",
            "superrag_url_max_pages",
            "superrag_url_same_domain",
            "superrag_db_url",
            "superrag_db_schema",
            "superrag_db_tables",
            "superrag_db_sample_rows",
            "superrag_db_max_tables",
            "superrag_onedrive_enabled",
            "superrag_onedrive_path",
            "superrag_onedrive_max_files",
            "superrag_onedrive_max_download_mb",
            "superrag_chat_query",
            "superrag_top_k",
            "superrag_chunk_size",
            "superrag_chunk_overlap",
            "shell_auto_approve",
        ]
        for key in passthrough_keys:
            if key in payload:
                state_overrides[key] = payload.get(key)
        if isinstance(payload.get("history"), list):
            state_overrides["session_history"] = payload.get("history", [])[-20:]
        if "communication_authorized" in payload:
            state_overrides["communication_authorized"] = bool(payload.get("communication_authorized"))
        if bool(payload.get("security_authorized", False)):
            state_overrides["security_authorized"] = True
        if payload.get("security_target_url"):
            state_overrides["security_target_url"] = str(payload.get("security_target_url")).strip()
        if payload.get("security_authorization_note"):
            state_overrides["security_authorization_note"] = str(payload.get("security_authorization_note")).strip()
        if payload.get("security_scan_profile"):
            state_overrides["security_scan_profile"] = str(payload.get("security_scan_profile")).strip().lower()
        try:
            result = RUNTIME.run_query(text, state_overrides=state_overrides)
            awaiting_user_input = state_awaiting_user_input(result)
            self._send_json(
                200,
                {
                    "run_id": result.get("run_id"),
                    "output_dir": result.get("run_output_dir", ""),
                    "working_directory": result.get("working_directory", ""),
                    "workflow_id": result.get("workflow_id") or result.get("run_id"),
                    "attempt_id": result.get("attempt_id") or result.get("run_id"),
                    "workflow_type": result.get("workflow_type", ""),
                    "final_output": result.get("final_output") or result.get("draft_response", ""),
                    "last_agent": result.get("last_agent", ""),
                    "status": "awaiting_user_input" if awaiting_user_input else "completed",
                    "awaiting_user_input": awaiting_user_input,
                    "pending_user_input_kind": result.get("pending_user_input_kind", ""),
                    "approval_pending_scope": result.get("approval_pending_scope", ""),
                    "pending_user_question": result.get("pending_user_question", ""),
                    "approval_request": result.get("approval_request", {}),
                    "last_shell_command": result.get("last_shell_command", ""),
                    "recent_shell_commands": result.get("recent_shell_commands", []),
                    "software_inventory_last_synced": result.get("software_inventory_last_synced", ""),
                    "software_inventory_stale": bool(result.get("software_inventory_stale", True)),
                    "software_inventory": result.get("software_inventory", {}),
                    "file_index_last_synced": result.get("file_index_last_synced", ""),
                    "indexed_files": int(result.get("indexed_files", 0) or 0),
                    "recent_file_changes_24h": int(result.get("recent_file_changes_24h", 0) or 0),
                    "machine_sync_stale": bool(result.get("machine_sync_stale", True)),
                    "resume_candidate": candidate if self.path == "/resume" else {},
                    # Long-document / deep-research export paths
                    "long_document_compiled_path": result.get("long_document_compiled_path", ""),
                    "long_document_compiled_html_path": result.get("long_document_compiled_html_path", ""),
                    "long_document_compiled_pdf_path": result.get("long_document_compiled_pdf_path", ""),
                    "long_document_compiled_docx_path": result.get("long_document_compiled_docx_path", ""),
                },
            )
        except Exception as exc:
            if _is_cancelled_error(exc):
                self._send_json(409, {"error": "run_cancelled", "detail": str(exc), "status": "cancelled"})
                return
            self._send_json(500, {"error": "workflow_failed", "detail": str(exc)})

    def _handle_home(self):
        agents = list(REGISTRY.agents.values())
        runtime_plugins = list(REGISTRY.plugins.values())
        try:
            from kendr.integration_registry import list_integrations as _list_integrations

            integrations = _list_integrations()
        except Exception:
            integrations = []
        runs = list_recent_runs(8)
        sessions = list_channel_sessions(8)
        jobs = list_scheduled_jobs(8)
        task_sessions = list_task_sessions(8)
        monitors = list_monitor_rules(8)
        heartbeats = list_heartbeat_events(8)
        body = f"""
        <h1>Kendr Gateway</h1>
        <p>Integration-aware, runtime-plugin extensible agent runtime with dynamic discovery, CLI control, and HTTP ingress.</p>
        <div class="grid">
          <div class="card">
            <h2>Registry</h2>
            <p>Agents: <strong>{len(agents)}</strong></p>
            <p>Runtime Plugins: <strong>{len(runtime_plugins)}</strong></p>
            <p>Integrations: <strong>{len(integrations)}</strong></p>
            <p><a href="/registry/agents">/registry/agents</a></p>
            <p><a href="/registry/capabilities">/registry/capabilities</a></p>
            <p><a href="/registry/discovery">/registry/discovery</a></p>
            <p><a href="/registry/auth-profiles">/registry/auth-profiles</a></p>
            <p><a href="/registry/policy-profiles">/registry/policy-profiles</a></p>
            <p><a href="/registry/integrations">/registry/integrations</a></p>
            <p><a href="/registry/plugins">/registry/plugins</a></p>
          </div>
          <div class="card">
            <h2>Gateway</h2>
            <p>POST channel payloads to <code>/ingest</code>.</p>
<pre>{html.escape(json.dumps({"channel": "webchat", "sender_id": "u1", "chat_id": "c1", "text": "hello"}, indent=2))}</pre>
          </div>
          <div class="card">
            <h2>Activity</h2>
            <p><a href="/runs">/runs</a></p>
            <p><a href="/sessions">/sessions</a></p>
            <p><a href="/task-sessions">/task-sessions</a></p>
            <p><a href="/resume-candidates?path=output">/resume-candidates?path=output</a></p>
            <p><a href="/jobs">/jobs</a></p>
            <p><a href="/monitors">/monitors</a></p>
            <p><a href="/monitor-events">/monitor-events</a></p>
            <p><a href="/heartbeats">/heartbeats</a></p>
            <p><a href="/audit/privileged">/audit/privileged</a></p>
          </div>
        </div>
        <div class="grid">
          <div class="card">
            <h2>Recent Runs</h2>
            <pre>{html.escape(json.dumps(runs, indent=2, ensure_ascii=False))}</pre>
          </div>
          <div class="card">
            <h2>Recent Sessions</h2>
            <pre>{html.escape(json.dumps(sessions, indent=2, ensure_ascii=False))}</pre>
          </div>
          <div class="card">
            <h2>Task Sessions</h2>
            <pre>{html.escape(json.dumps(task_sessions, indent=2, ensure_ascii=False))}</pre>
          </div>
          <div class="card">
            <h2>Scheduled Jobs</h2>
            <pre>{html.escape(json.dumps(jobs, indent=2, ensure_ascii=False))}</pre>
          </div>
          <div class="card">
            <h2>Monitor Rules</h2>
            <pre>{html.escape(json.dumps(monitors, indent=2, ensure_ascii=False))}</pre>
          </div>
          <div class="card">
            <h2>Heartbeats</h2>
            <pre>{html.escape(json.dumps(heartbeats, indent=2, ensure_ascii=False))}</pre>
          </div>
        </div>
        """
        self._send_html(200, "Kendr Gateway", body)


def main() -> None:
    import threading as _threading

    host = os.getenv("GATEWAY_HOST", "127.0.0.1")
    port = int(os.getenv("GATEWAY_PORT", "8790"))
    server = ThreadingHTTPServer((host, port), GatewayHandler)
    print(f"Gateway server running at http://{host}:{port}")

    if os.getenv("KENDR_UI_ENABLED", "1") != "0":
        def _start_ui() -> None:
            try:
                from kendr.ui_server import main as _ui_main
                _ui_main()
            except OSError as exc:
                if "Address already in use" in str(exc):
                    pass
                else:
                    print(f"[kendr-ui] startup error: {exc}")
            except Exception as exc:
                print(f"[kendr-ui] startup error: {exc}")

        _ui_thread = _threading.Thread(target=_start_ui, daemon=True, name="kendr-ui")
        _ui_thread.start()

    server.serve_forever()


if __name__ == "__main__":
    main()
