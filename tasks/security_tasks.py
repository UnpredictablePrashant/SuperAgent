import json
import os
import re
import socket
import ssl
import subprocess
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from tasks.a2a_agent_utils import begin_agent_session, publish_agent_output
from tasks.security_policy import apply_security_profile_defaults, require_security_authorization
from tasks.research_infra import html_to_text, llm_json, llm_text
from tasks.utils import OUTPUT_DIR, log_task_update, write_text_file


def _write_outputs(agent_name: str, call_number: int, summary: str, payload: dict):
    write_text_file(f"{agent_name}_{call_number}.txt", summary)
    write_text_file(f"{agent_name}_{call_number}.json", json.dumps(payload, indent=2, ensure_ascii=False))


def _resolve_paths(raw_paths, working_directory: str | None = None) -> list[str]:
    if isinstance(raw_paths, str):
        raw_paths = [raw_paths]
    paths = []
    for raw_path in raw_paths or []:
        path = Path(raw_path)
        if not path.is_absolute():
            path = Path(working_directory or ".").resolve() / path
        paths.append(str(path))
    return paths


def _require_authorized_security_scope(state: dict):
    target = _target_base_url(state, "")
    apply_security_profile_defaults(state)
    require_security_authorization(state, target)


def _target_base_url(state: dict, task_content: str) -> str:
    return state.get("security_target_url") or state.get("target_url") or task_content or state.get("current_objective") or state.get("user_query", "")


def _request_headers() -> dict:
    return {"User-Agent": os.getenv("RESEARCH_USER_AGENT", "multi-agent-security-bot/1.0")}


def _fetch_url(url: str, timeout: int = 20) -> dict:
    request = Request(url, headers=_request_headers())
    try:
        with urlopen(request, timeout=timeout) as response:
            body = response.read().decode("utf-8", errors="ignore")
            return {
                "url": url,
                "status": getattr(response, "status", None),
                "headers": dict(response.headers.items()),
                "body": body,
                "error": "",
            }
    except HTTPError as exc:
        try:
            body = exc.read().decode("utf-8", errors="ignore")
        except Exception:
            body = ""
        return {"url": url, "status": exc.code, "headers": dict(exc.headers.items()), "body": body, "error": str(exc)}
    except URLError as exc:
        return {"url": url, "status": None, "headers": {}, "body": "", "error": str(exc)}
    except Exception as exc:
        return {"url": url, "status": None, "headers": {}, "body": "", "error": str(exc)}


def _candidate_api_doc_urls(target: str, extra_paths: list[str] | None = None) -> list[str]:
    parsed = urlparse(target if target.startswith(("http://", "https://")) else f"https://{target}")
    base = f"{parsed.scheme}://{parsed.netloc}"
    candidates = [
        "/swagger",
        "/swagger/",
        "/swagger-ui",
        "/swagger-ui/",
        "/swagger-ui/index.html",
        "/swagger.json",
        "/openapi.json",
        "/api-docs",
        "/api-docs/",
        "/v3/api-docs",
        "/v2/api-docs",
        "/docs",
        "/docs/",
        "/redoc",
        "/graphql",
    ]
    for path in extra_paths or []:
        if isinstance(path, str) and path.startswith("/"):
            candidates.append(path)
    return [base + path for path in candidates]


def _extract_endpoints_from_text(text: str) -> list[dict]:
    endpoint_map: dict[tuple[str, str], dict] = {}
    pattern = re.compile(r"\b(GET|POST|PUT|PATCH|DELETE|OPTIONS|HEAD)\s+(/[A-Za-z0-9._~!$&'()*+,;=:@%/\-{}]+)")
    for method, path in pattern.findall(text or ""):
        key = (method.upper(), path)
        endpoint_map[key] = {"method": method.upper(), "path": path, "source": "text"}
    return list(endpoint_map.values())


def _extract_openapi_operations(payload: dict) -> list[dict]:
    operations = []
    global_security = payload.get("security")
    for path, item in (payload.get("paths") or {}).items():
        if not isinstance(item, dict):
            continue
        for method, operation in item.items():
            method_upper = str(method).upper()
            if method_upper not in {"GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS", "HEAD"}:
                continue
            if not isinstance(operation, dict):
                operation = {}
            security = operation.get("security", global_security)
            operations.append(
                {
                    "method": method_upper,
                    "path": path,
                    "summary": operation.get("summary", ""),
                    "description": operation.get("description", ""),
                    "operation_id": operation.get("operationId", ""),
                    "security": security,
                    "tags": operation.get("tags", []),
                    "source": "openapi",
                }
            )
    return operations


def _read_security_files(raw_paths, working_directory: str | None = None, limit: int = 20) -> list[dict]:
    files = []
    for path_str in _resolve_paths(raw_paths, working_directory)[:limit]:
        path = Path(path_str)
        if path.exists() and path.is_file():
            files.append(
                {
                    "path": str(path),
                    "content": path.read_text(encoding="utf-8", errors="ignore")[:20000],
                }
            )
    return files


def security_scope_guard_agent(state):
    _, task_content, _ = begin_agent_session(state, "security_scope_guard_agent")
    state["security_scope_guard_calls"] = state.get("security_scope_guard_calls", 0) + 1
    call_number = state["security_scope_guard_calls"]
    target = _target_base_url(state, task_content)
    apply_security_profile_defaults(state)
    authorized = bool(state.get("security_authorized", False))
    scan_mode = state.get("security_scan_mode", "defensive")
    auth_note = str(state.get("security_authorization_note", "")).strip()
    scan_profile = str(state.get("security_scan_profile", "deep")).strip()

    prompt = f"""
You are a security scope guard agent.

Review whether the proposed security assessment is explicitly framed as authorized defensive work.

Target:
{target}

Authorized flag:
{authorized}

Authorization note:
{auth_note or "missing"}

Requested mode:
{scan_mode}

Requested scan profile:
{scan_profile}

Return ONLY valid JSON:
{{
  "decision": "allow|deny",
  "allowed_actions": ["passive_web_checks", "api_surface_mapping", "unauthenticated_endpoint_review", "idor_review", "prompt_integrity_review", "ai_asset_exposure_review", "dependency_audit", "sast_review", "tls_review"],
  "disallowed_actions": ["exploit", "credential_attack", "service_disruption"],
  "reason": "brief explanation"
}}
"""
    fallback = {
        "decision": "allow" if authorized else "deny",
        "allowed_actions": [
            "passive_web_checks",
            "api_surface_mapping",
            "unauthenticated_endpoint_review",
            "idor_review",
            "prompt_integrity_review",
            "ai_asset_exposure_review",
            "dependency_audit",
            "sast_review",
            "tls_review",
        ]
        if authorized
        else [],
        "disallowed_actions": ["exploit", "credential_attack", "service_disruption"],
        "reason": "Fallback security policy applied.",
    }
    result = llm_json(prompt, fallback)
    if not authorized:
        result["decision"] = "deny"
        result["reason"] = "Authorization flag not present."
    elif not auth_note:
        result["decision"] = "deny"
        result["reason"] = "Authorization note (ticket/approval reference) missing."
    summary = (
        f"Decision: {result.get('decision', 'deny')}\n"
        f"Scan Profile: {scan_profile}\n"
        f"Allowed Actions: {', '.join(result.get('allowed_actions', []))}\n"
        f"Disallowed Actions: {', '.join(result.get('disallowed_actions', []))}\n"
        f"Reason: {result.get('reason', '')}"
    )
    _write_outputs("security_scope_guard_agent", call_number, summary, result)
    state["security_scope_report"] = result
    state["draft_response"] = summary
    return publish_agent_output(
        state,
        "security_scope_guard_agent",
        summary,
        f"security_scope_guard_result_{call_number}",
        recipients=["orchestrator_agent", "reviewer_agent"],
    )


def api_surface_mapper_agent(state):
    _, task_content, _ = begin_agent_session(state, "api_surface_mapper_agent")
    _require_authorized_security_scope(state)
    state["api_surface_mapper_calls"] = state.get("api_surface_mapper_calls", 0) + 1
    call_number = state["api_surface_mapper_calls"]
    target = _target_base_url(state, task_content)
    if not target.startswith(("http://", "https://")):
        raise ValueError("api_surface_mapper_agent requires a full http(s) target URL.")

    docs = []
    endpoints = []
    extra_doc_paths = state.get("security_api_doc_paths") or []
    doc_limit = int(state.get("security_api_doc_limit", 45))
    for url in _candidate_api_doc_urls(target, extra_paths=extra_doc_paths)[:doc_limit]:
        fetched = _fetch_url(url, timeout=int(state.get("security_timeout", 20)))
        body = fetched.get("body", "")
        record = {
            "url": url,
            "status": fetched.get("status"),
            "content_type": fetched.get("headers", {}).get("Content-Type", ""),
            "error": fetched.get("error", ""),
            "body_excerpt": html_to_text(body)[:3000],
        }
        parsed_payload = None
        if body:
            try:
                parsed_payload = json.loads(body)
            except Exception:
                parsed_payload = None
        if isinstance(parsed_payload, dict) and parsed_payload.get("paths"):
            ops = _extract_openapi_operations(parsed_payload)
            for op in ops:
                op["doc_url"] = url
            endpoints.extend(ops)
            record["openapi_path_count"] = len(parsed_payload.get("paths", {}))
        else:
            extracted = _extract_endpoints_from_text(body)
            for op in extracted:
                op["doc_url"] = url
            endpoints.extend(extracted)
            record["text_endpoint_count"] = len(extracted)
        docs.append(record)

    deduped = []
    seen = set()
    for item in endpoints:
        key = (item.get("method", ""), item.get("path", ""))
        if key in seen:
            continue
        seen.add(key)
        deduped.append(item)

    payload = {
        "target": target,
        "doc_candidates": docs,
        "discovered_endpoints": deduped,
        "endpoint_count": len(deduped),
    }
    summary = llm_text(
        f"""You are a defensive API surface mapping agent.

Review this passive API documentation and endpoint discovery payload.
Summarize:
- whether public API docs appear exposed
- the scale of the discovered API surface
- whether sensitive or administrative endpoint families appear present
- what should be reviewed next from a defensive standpoint

Payload:
{json.dumps(payload, indent=2, ensure_ascii=False)[:50000]}
"""
    )
    _write_outputs("api_surface_mapper_agent", call_number, summary, payload)
    state["api_surface_map"] = payload
    state["draft_response"] = summary
    return publish_agent_output(
        state,
        "api_surface_mapper_agent",
        summary,
        f"api_surface_map_{call_number}",
        recipients=["orchestrator_agent", "worker_agent", "reviewer_agent", "security_findings_agent"],
    )


def web_recon_agent(state):
    _, task_content, _ = begin_agent_session(state, "web_recon_agent")
    _require_authorized_security_scope(state)
    state["web_recon_calls"] = state.get("web_recon_calls", 0) + 1
    call_number = state["web_recon_calls"]
    target = _target_base_url(state, task_content)
    if not target.startswith(("http://", "https://")):
        raise ValueError("web_recon_agent requires a full http(s) target URL.")

    headers = {"User-Agent": os.getenv("RESEARCH_USER_AGENT", "multi-agent-security-bot/1.0")}
    request = Request(target, headers=headers)
    with urlopen(request, timeout=int(state.get("security_timeout", 20))) as response:
        body = response.read().decode("utf-8", errors="ignore")
        response_headers = dict(response.headers.items())
        status = getattr(response, "status", None)

    parsed = urlparse(target)
    base = f"{parsed.scheme}://{parsed.netloc}"
    extra_paths = {}
    recon_paths = state.get("security_web_recon_paths") or ["/robots.txt", "/sitemap.xml"]
    for rel in recon_paths:
        try:
            req = Request(base + rel, headers=headers)
            with urlopen(req, timeout=10) as response:
                extra_paths[rel] = response.read().decode("utf-8", errors="ignore")[:4000]
        except Exception as exc:
            extra_paths[rel] = f"Unavailable: {exc}"

    title_match = re.search(r"(?is)<title>(.*?)</title>", body)
    payload = {
        "target": target,
        "status": status,
        "headers": response_headers,
        "title": title_match.group(1).strip() if title_match else "",
        "page_text_excerpt": html_to_text(body)[:4000],
        "extra_paths": extra_paths,
    }
    summary = llm_text(
        f"Summarize the attack surface indicators, public recon clues, and obvious security signals from this web recon payload:\n\n{json.dumps(payload, indent=2, ensure_ascii=False)}"
    )
    _write_outputs("web_recon_agent", call_number, summary, payload)
    state["web_recon"] = payload
    state["draft_response"] = summary
    log_task_update("Web Recon", f"Recon pass #{call_number} saved to {OUTPUT_DIR}/web_recon_agent_{call_number}.txt")
    return publish_agent_output(
        state,
        "web_recon_agent",
        summary,
        f"web_recon_result_{call_number}",
        recipients=["orchestrator_agent", "worker_agent", "reviewer_agent"],
    )


def unauthenticated_endpoint_audit_agent(state):
    _, task_content, _ = begin_agent_session(state, "unauthenticated_endpoint_audit_agent")
    _require_authorized_security_scope(state)
    state["unauthenticated_endpoint_audit_calls"] = state.get("unauthenticated_endpoint_audit_calls", 0) + 1
    call_number = state["unauthenticated_endpoint_audit_calls"]
    api_surface = state.get("api_surface_map", {})
    endpoints = api_surface.get("discovered_endpoints", [])
    if not endpoints:
        raise ValueError("unauthenticated_endpoint_audit_agent requires api_surface_map from api_surface_mapper_agent.")

    candidate_findings = []
    for item in endpoints[:500]:
        security = item.get("security")
        method = item.get("method", "GET")
        path = item.get("path", "")
        path_l = path.lower()
        likely_public = not security
        sensitive_keywords = [
            "admin",
            "user",
            "account",
            "workspace",
            "message",
            "chat",
            "search",
            "file",
            "document",
            "assistant",
            "prompt",
            "config",
        ]
        sensitive = any(keyword in path_l for keyword in sensitive_keywords)
        write_like = method in {"POST", "PUT", "PATCH", "DELETE"}
        if likely_public:
            candidate_findings.append(
                {
                    "method": method,
                    "path": path,
                    "risk": "high" if write_like and sensitive else "medium" if sensitive or write_like else "low",
                    "likely_public": True,
                    "write_like": write_like,
                    "sensitive": sensitive,
                    "reason": "No explicit OpenAPI security requirement declared." if item.get("source") == "openapi" else "Endpoint discovered from public docs/text and requires manual auth validation.",
                }
            )

    payload = {
        "target": api_surface.get("target") or _target_base_url(state, task_content),
        "candidate_public_endpoints": candidate_findings,
        "public_write_candidates": [item for item in candidate_findings if item["write_like"]],
    }
    result = llm_json(
        f"""You are a defensive unauthenticated endpoint review agent.

Review this list of candidate public endpoints discovered from documentation or passive recon.
Prioritize endpoints that appear to allow writes or expose sensitive business objects.

Payload:
{json.dumps(payload, indent=2, ensure_ascii=False)[:50000]}

Return ONLY valid JSON:
{{
  "risk_level": "low|medium|high|critical",
  "prioritized_endpoints": [
    {{
      "method": "HTTP method",
      "path": "/path",
      "severity": "low|medium|high|critical",
      "reason": "brief explanation",
      "recommended_check": "what the authorized defender should validate"
    }}
  ],
  "summary": "brief summary"
}}
""",
        {"risk_level": "unknown", "prioritized_endpoints": [], "summary": "No unauthenticated endpoint findings generated."},
    )
    summary = result.get("summary", "No unauthenticated endpoint findings generated.")
    _write_outputs("unauthenticated_endpoint_audit_agent", call_number, summary, result)
    state["unauthenticated_endpoint_report"] = result
    state["draft_response"] = summary
    return publish_agent_output(
        state,
        "unauthenticated_endpoint_audit_agent",
        summary,
        f"unauthenticated_endpoint_report_{call_number}",
        recipients=["orchestrator_agent", "worker_agent", "reviewer_agent", "security_findings_agent"],
    )


def security_headers_agent(state):
    _, task_content, _ = begin_agent_session(state, "security_headers_agent")
    _require_authorized_security_scope(state)
    state["security_headers_calls"] = state.get("security_headers_calls", 0) + 1
    call_number = state["security_headers_calls"]
    recon = state.get("web_recon", {})
    headers = recon.get("headers", {})
    target = recon.get("target") or _target_base_url(state, task_content)
    expected = [
        "content-security-policy",
        "strict-transport-security",
        "x-content-type-options",
        "x-frame-options",
        "referrer-policy",
        "permissions-policy",
    ]
    present = {key.lower(): value for key, value in headers.items()}
    findings = []
    for header in expected:
        if header not in present:
            findings.append({"header": header, "status": "missing", "severity": "medium"})
        else:
            findings.append({"header": header, "status": "present", "value": present[header], "severity": "info"})

    summary = llm_text(
        f"Review these HTTP security headers for {target} and summarize material misconfigurations and priorities:\n\n{json.dumps(findings, indent=2, ensure_ascii=False)}"
    )
    payload = {"target": target, "findings": findings}
    _write_outputs("security_headers_agent", call_number, summary, payload)
    state["security_headers_report"] = payload
    state["draft_response"] = summary
    return publish_agent_output(
        state,
        "security_headers_agent",
        summary,
        f"security_headers_result_{call_number}",
        recipients=["orchestrator_agent", "worker_agent", "reviewer_agent"],
    )


def idor_bola_risk_agent(state):
    _, task_content, _ = begin_agent_session(state, "idor_bola_risk_agent")
    _require_authorized_security_scope(state)
    state["idor_bola_risk_calls"] = state.get("idor_bola_risk_calls", 0) + 1
    call_number = state["idor_bola_risk_calls"]
    api_surface = state.get("api_surface_map", {})
    endpoints = api_surface.get("discovered_endpoints", [])
    if not endpoints:
        raise ValueError("idor_bola_risk_agent requires api_surface_map from api_surface_mapper_agent.")

    object_patterns = re.compile(r"(\{[^}]*id[^}]*\}|/[0-9]+|/[a-f0-9-]{8,}|/users?/|/accounts?/|/files?/|/documents?/|/messages?/|/workspaces?/|/agents?/)", re.IGNORECASE)
    candidates = []
    for item in endpoints[:500]:
        path = item.get("path", "")
        method = item.get("method", "GET")
        if not object_patterns.search(path):
            continue
        candidates.append(
            {
                "method": method,
                "path": path,
                "security": item.get("security"),
                "summary": item.get("summary", ""),
                "description": item.get("description", ""),
                "risk_hint": "write-path object reference" if method in {"PUT", "PATCH", "DELETE"} else "object retrieval path",
            }
        )

    sast_findings = state.get("sast_review_report", {})
    result = llm_json(
        f"""You are a defensive broken object level authorization review agent.

Assess these endpoint patterns for BOLA/IDOR risk.
Focus on user-, file-, message-, workspace-, and document-scoped objects where authorization mistakes would be high impact.

Endpoint candidates:
{json.dumps(candidates, indent=2, ensure_ascii=False)[:40000]}

Relevant SAST findings:
{json.dumps(sast_findings, indent=2, ensure_ascii=False)[:12000]}

Return ONLY valid JSON:
{{
  "risk_level": "low|medium|high|critical",
  "idor_candidates": [
    {{
      "method": "HTTP method",
      "path": "/path",
      "severity": "low|medium|high|critical",
      "reason": "brief explanation",
      "review_focus": "what access control the defender should verify"
    }}
  ],
  "summary": "brief summary"
}}
""",
        {"risk_level": "unknown", "idor_candidates": [], "summary": "No IDOR/BOLA findings generated."},
    )
    summary = result.get("summary", "No IDOR/BOLA findings generated.")
    _write_outputs("idor_bola_risk_agent", call_number, summary, result)
    state["idor_bola_risk_report"] = result
    state["draft_response"] = summary
    return publish_agent_output(
        state,
        "idor_bola_risk_agent",
        summary,
        f"idor_bola_risk_result_{call_number}",
        recipients=["orchestrator_agent", "worker_agent", "reviewer_agent", "security_findings_agent"],
    )


def tls_assessment_agent(state):
    _, task_content, _ = begin_agent_session(state, "tls_assessment_agent")
    _require_authorized_security_scope(state)
    state["tls_assessment_calls"] = state.get("tls_assessment_calls", 0) + 1
    call_number = state["tls_assessment_calls"]
    target = _target_base_url(state, task_content)
    parsed = urlparse(target if target.startswith(("http://", "https://")) else f"https://{target}")
    hostname = parsed.hostname
    port = parsed.port or 443
    if not hostname:
        raise ValueError("tls_assessment_agent requires a hostname or https URL.")

    context = ssl.create_default_context()
    with socket.create_connection((hostname, port), timeout=int(state.get("security_timeout", 20))) as sock:
        with context.wrap_socket(sock, server_hostname=hostname) as tls_sock:
            cert = tls_sock.getpeercert()
            cipher = tls_sock.cipher()
            version = tls_sock.version()

    payload = {
        "hostname": hostname,
        "port": port,
        "tls_version": version,
        "cipher": cipher,
        "certificate": cert,
    }
    summary = llm_text(
        f"Assess this TLS configuration for server-side security posture, certificate issues, and upgrade priorities:\n\n{json.dumps(payload, indent=2, ensure_ascii=False)}"
    )
    _write_outputs("tls_assessment_agent", call_number, summary, payload)
    state["tls_assessment_report"] = payload
    state["draft_response"] = summary
    return publish_agent_output(
        state,
        "tls_assessment_agent",
        summary,
        f"tls_assessment_result_{call_number}",
        recipients=["orchestrator_agent", "worker_agent", "reviewer_agent"],
    )


def dependency_audit_agent(state):
    _, task_content, _ = begin_agent_session(state, "dependency_audit_agent")
    _require_authorized_security_scope(state)
    state["dependency_audit_calls"] = state.get("dependency_audit_calls", 0) + 1
    call_number = state["dependency_audit_calls"]
    working_directory = Path(state.get("dependency_audit_workdir", ".")).resolve()

    manifests = []
    for name in ["requirements.txt", "package.json", "pom.xml", "build.gradle", "pyproject.toml"]:
        path = working_directory / name
        if path.exists():
            manifests.append({"path": str(path), "content": path.read_text(encoding="utf-8", errors="ignore")[:12000]})

    tool_results = {}
    if shutil_which := __import__("shutil").which("dependency-check"):
        try:
            output_dir = working_directory / "output"
            output_dir.mkdir(exist_ok=True)
            cmd = [
                shutil_which,
                "--project",
                "multi-agent-audit",
                "--scan",
                str(working_directory),
                "--format",
                "JSON",
                "--out",
                str(output_dir),
            ]
            completed = subprocess.run(cmd, capture_output=True, text=True, timeout=600, check=False)
            tool_results["dependency_check"] = {
                "returncode": completed.returncode,
                "stdout": completed.stdout[-4000:],
                "stderr": completed.stderr[-4000:],
            }
        except Exception as exc:
            tool_results["dependency_check"] = {"error": str(exc)}

    prompt = f"""
You are a dependency audit agent.

Manifest files:
{json.dumps(manifests, indent=2, ensure_ascii=False)}

Optional tool results:
{json.dumps(tool_results, indent=2, ensure_ascii=False)}

Summarize dependency security risks, obvious outdated components, and recommended next checks.
"""
    summary = llm_text(prompt)
    payload = {"manifests": manifests, "tool_results": tool_results}
    _write_outputs("dependency_audit_agent", call_number, summary, payload)
    state["dependency_audit_report"] = payload
    state["draft_response"] = summary
    return publish_agent_output(
        state,
        "dependency_audit_agent",
        summary,
        f"dependency_audit_result_{call_number}",
        recipients=["orchestrator_agent", "worker_agent", "reviewer_agent"],
    )


def sast_review_agent(state):
    _, task_content, _ = begin_agent_session(state, "sast_review_agent")
    _require_authorized_security_scope(state)
    state["sast_review_calls"] = state.get("sast_review_calls", 0) + 1
    call_number = state["sast_review_calls"]
    paths = _resolve_paths(state.get("sast_paths") or [], state.get("sast_working_directory"))
    if not paths and task_content and Path(task_content).exists():
        paths = [task_content]
    if not paths:
        raise ValueError("sast_review_agent requires 'sast_paths' or a file path task.")

    files = []
    for path_str in paths[:20]:
        path = Path(path_str)
        if path.exists() and path.is_file():
            files.append({"path": str(path), "content": path.read_text(encoding="utf-8", errors="ignore")[:20000]})

    prompt = f"""
You are a static application security review agent.

Review these files for common application security issues such as injection risk, missing auth checks, weak secrets handling, unsafe deserialization, SSRF, path traversal, and broken access control.

Files:
{json.dumps(files, indent=2, ensure_ascii=False)[:50000]}

Return ONLY valid JSON:
{{
  "findings": [
    {{
      "file": "path",
      "severity": "low|medium|high|critical",
      "title": "issue title",
      "detail": "brief explanation",
      "recommendation": "fix guidance"
    }}
  ],
  "summary": "brief SAST summary"
}}
"""
    result = llm_json(prompt, {"findings": [], "summary": "No SAST findings generated."})
    summary = result.get("summary", "No SAST findings generated.")
    _write_outputs("sast_review_agent", call_number, summary, result)
    state["sast_review_report"] = result
    state["draft_response"] = summary
    return publish_agent_output(
        state,
        "sast_review_agent",
        summary,
        f"sast_review_result_{call_number}",
        recipients=["orchestrator_agent", "worker_agent", "reviewer_agent"],
    )


def prompt_security_agent(state):
    _, task_content, _ = begin_agent_session(state, "prompt_security_agent")
    _require_authorized_security_scope(state)
    state["prompt_security_calls"] = state.get("prompt_security_calls", 0) + 1
    call_number = state["prompt_security_calls"]
    prompt_paths = state.get("prompt_asset_paths") or state.get("security_prompt_paths") or state.get("document_paths") or []
    prompt_files = _read_security_files(prompt_paths, state.get("security_working_directory"))
    if not prompt_files and state.get("sast_paths"):
        prompt_files = _read_security_files(state.get("sast_paths"), state.get("sast_working_directory"))

    keyword_hits = []
    keyword_pattern = re.compile(r"(system[_ -]?prompt|prompt|instruction|guardrail|policy|assistant[_ -]?config|model[_ -]?config)", re.IGNORECASE)
    for item in prompt_files:
        matches = keyword_pattern.findall(item["content"])
        if matches:
            keyword_hits.append({"path": item["path"], "match_count": len(matches)})

    result = llm_json(
        f"""You are a defensive prompt and AI configuration security agent.

Review these files for prompt-layer governance and integrity risks.
Focus on:
- whether prompts or model instructions are treated as crown-jewel assets
- missing version control or integrity monitoring
- weak access control around prompt changes
- prompts that could silently alter AI behavior
- prompt files that include secrets, sensitive business logic, or unsafe embedded instructions

Files:
{json.dumps(prompt_files, indent=2, ensure_ascii=False)[:50000]}

Keyword hits:
{json.dumps(keyword_hits, indent=2, ensure_ascii=False)}

Return ONLY valid JSON:
{{
  "risk_level": "low|medium|high|critical",
  "prompt_assets": [
    {{
      "path": "file path",
      "role": "prompt|config|policy|unknown",
      "sensitivity": "low|medium|high|critical",
      "reason": "brief explanation"
    }}
  ],
  "integrity_gaps": [
    {{
      "title": "gap title",
      "severity": "low|medium|high|critical",
      "detail": "brief detail",
      "recommendation": "brief remediation"
    }}
  ],
  "summary": "brief summary"
}}
""",
        {"risk_level": "unknown", "prompt_assets": [], "integrity_gaps": [], "summary": "No prompt security findings generated."},
    )
    summary = result.get("summary", "No prompt security findings generated.")
    _write_outputs("prompt_security_agent", call_number, summary, result)
    state["prompt_security_report"] = result
    state["draft_response"] = summary
    return publish_agent_output(
        state,
        "prompt_security_agent",
        summary,
        f"prompt_security_result_{call_number}",
        recipients=["orchestrator_agent", "worker_agent", "reviewer_agent", "security_findings_agent"],
    )


def ai_asset_exposure_agent(state):
    _, task_content, _ = begin_agent_session(state, "ai_asset_exposure_agent")
    _require_authorized_security_scope(state)
    state["ai_asset_exposure_calls"] = state.get("ai_asset_exposure_calls", 0) + 1
    call_number = state["ai_asset_exposure_calls"]
    files = _read_security_files(
        state.get("ai_asset_paths") or state.get("document_paths") or state.get("sast_paths") or [],
        state.get("security_working_directory") or state.get("sast_working_directory"),
    )
    api_surface = state.get("api_surface_map", {})
    recon = state.get("web_recon", {})
    text_bundle = "\n\n".join([item["content"] for item in files[:10]])
    signal_patterns = {
        "s3": r"s3://[^\s\"']+",
        "gs": r"gs://[^\s\"']+",
        "azure_blob": r"https://[A-Za-z0-9.-]+\.blob\.core\.windows\.net/[^\s\"']+",
        "vector_store": r"vector[_ -]?store|embedding|embeddings|qdrant|pinecone|weaviate|faiss",
        "rag": r"\bRAG\b|retrieval[- ]augmented|knowledge base|document chunks?",
        "prompt_config": r"system[_ -]?prompt|model[_ -]?config|guardrail",
        "download_url": r"https?://[^\s\"']+(download|export|files?/|documents?/)[^\s\"']*",
    }
    detected = {}
    for name, pattern in signal_patterns.items():
        hits = re.findall(pattern, text_bundle, flags=re.IGNORECASE)
        if hits:
            detected[name] = hits[:20]

    result = llm_json(
        f"""You are a defensive AI asset exposure review agent.

Assess whether this evidence suggests exposed AI assets such as RAG stores, vector pipelines, prompt configs, download URLs, model configs, or storage references.
Focus on confidentiality and governance risk, not exploitation.

API surface:
{json.dumps(api_surface, indent=2, ensure_ascii=False)[:18000]}

Web recon:
{json.dumps(recon, indent=2, ensure_ascii=False)[:8000]}

Detected text signals:
{json.dumps(detected, indent=2, ensure_ascii=False)}

Files:
{json.dumps(files, indent=2, ensure_ascii=False)[:25000]}

Return ONLY valid JSON:
{{
  "risk_level": "low|medium|high|critical",
  "exposure_signals": [
    {{
      "asset_type": "prompt|vector_store|storage_path|download_url|rag_data|model_config|unknown",
      "severity": "low|medium|high|critical",
      "detail": "brief explanation",
      "defensive_action": "brief remediation"
    }}
  ],
  "summary": "brief summary"
}}
""",
        {"risk_level": "unknown", "exposure_signals": [], "summary": "No AI asset exposure findings generated."},
    )
    summary = result.get("summary", "No AI asset exposure findings generated.")
    _write_outputs("ai_asset_exposure_agent", call_number, summary, result)
    state["ai_asset_exposure_report"] = result
    state["draft_response"] = summary
    return publish_agent_output(
        state,
        "ai_asset_exposure_agent",
        summary,
        f"ai_asset_exposure_result_{call_number}",
        recipients=["orchestrator_agent", "worker_agent", "reviewer_agent", "security_findings_agent"],
    )


def security_findings_agent(state):
    _, task_content, _ = begin_agent_session(state, "security_findings_agent")
    _require_authorized_security_scope(state)
    state["security_findings_calls"] = state.get("security_findings_calls", 0) + 1
    call_number = state["security_findings_calls"]
    evidence = {
        "scope": state.get("security_scope_report", {}),
        "recon": state.get("web_recon", {}),
        "api_surface": state.get("api_surface_map", {}),
        "unauthenticated_endpoints": state.get("unauthenticated_endpoint_report", {}),
        "idor_bola": state.get("idor_bola_risk_report", {}),
        "headers": state.get("security_headers_report", {}),
        "tls": state.get("tls_assessment_report", {}),
        "dependency_audit": state.get("dependency_audit_report", {}),
        "sast": state.get("sast_review_report", {}),
        "prompt_security": state.get("prompt_security_report", {}),
        "ai_asset_exposure": state.get("ai_asset_exposure_report", {}),
    }

    prompt = f"""
You are a defensive security findings aggregation agent.

Aggregate these security assessment results into a prioritized finding list and remediation plan.

Evidence:
{json.dumps(evidence, indent=2, ensure_ascii=False)[:50000]}

Return ONLY valid JSON:
{{
  "overall_risk": "low|medium|high|critical",
  "prioritized_findings": [
    {{
      "title": "finding",
      "severity": "low|medium|high|critical",
      "source": "agent name",
      "detail": "brief detail",
      "remediation": "brief remediation"
    }}
  ],
  "summary": "brief security summary"
}}
"""
    result = llm_json(prompt, {"overall_risk": "unknown", "prioritized_findings": [], "summary": "No aggregated security findings."})
    summary = result.get("summary", "No aggregated security findings.")
    _write_outputs("security_findings_agent", call_number, summary, result)
    state["security_findings_report"] = result
    state["draft_response"] = summary
    return publish_agent_output(
        state,
        "security_findings_agent",
        summary,
        f"security_findings_result_{call_number}",
        recipients=["orchestrator_agent", "worker_agent", "reviewer_agent", "report_agent"],
    )
