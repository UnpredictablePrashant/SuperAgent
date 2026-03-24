import json
import os
import shutil
import subprocess
import uuid
import xml.etree.ElementTree as ET
from pathlib import Path
from urllib.parse import urlparse

from tasks.a2a_agent_utils import begin_agent_session, publish_agent_output
from tasks.report_tasks import report_agent
from tasks.research_infra import llm_json, llm_text
from tasks.security_policy import apply_security_profile_defaults
from tasks.security_tasks import (
    _require_authorized_security_scope,
    _target_base_url,
    api_surface_mapper_agent,
    security_findings_agent,
    web_recon_agent,
)
from tasks.utils import get_output_dir, log_task_update, resolve_output_path, write_text_file


AGENT_METADATA = {
    "recon_agent": {
        "description": "Defensive recon orchestrator that combines passive web recon and API surface discovery.",
        "requirements": ["openai"],
        "input_keys": ["security_authorized", "security_target_url"],
        "output_keys": ["recon_report"],
    },
    "scanner_agent": {
        "description": "Defensive scanner that runs safe Nmap and ZAP baseline checks on authorized targets.",
        "requirements": ["openai", "nmap_or_zap"],
        "input_keys": ["security_authorized", "security_target_url"],
        "output_keys": ["scanner_report"],
    },
    "exploit_agent": {
        "description": "Analysis-only exploitability review agent. It does not generate payloads or execute attacks.",
        "requirements": ["openai"],
        "input_keys": ["security_authorized", "security_target_url"],
        "output_keys": ["exploitability_report"],
    },
    "evidence_agent": {
        "description": "Collects screenshots and run artifacts into a structured evidence bundle.",
        "requirements": ["openai"],
        "input_keys": ["security_authorized", "security_target_url"],
        "output_keys": ["evidence_report"],
    },
    "security_report_agent": {
        "description": "Builds a long-form defensive security report and delegates file generation to report_agent.",
        "requirements": ["openai"],
        "input_keys": ["security_authorized", "security_target_url", "report_formats"],
        "output_keys": ["security_report_summary", "report_files"],
    },
}


def _write_outputs(agent_name: str, call_number: int, summary: str, payload: dict):
    write_text_file(f"{agent_name}_{call_number}.txt", summary)
    write_text_file(f"{agent_name}_{call_number}.json", json.dumps(payload, indent=2, ensure_ascii=False))


def _host_from_target(target: str) -> str:
    if not target:
        return ""
    parsed = urlparse(target if target.startswith(("http://", "https://")) else f"https://{target}")
    return parsed.hostname or target


def _is_http_target(target: str) -> bool:
    return str(target).startswith(("http://", "https://"))


def _run_command(cmd: list[str], timeout: int) -> dict:
    try:
        completed = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, check=False)
        return {
            "command": cmd,
            "returncode": completed.returncode,
            "stdout": completed.stdout[-30000:],
            "stderr": completed.stderr[-12000:],
            "timed_out": False,
        }
    except subprocess.TimeoutExpired as exc:
        return {
            "command": cmd,
            "returncode": None,
            "stdout": (exc.stdout or "")[-30000:] if exc.stdout else "",
            "stderr": (exc.stderr or "")[-12000:] if exc.stderr else "",
            "timed_out": True,
            "error": f"Command timed out after {timeout} seconds.",
        }
    except Exception as exc:
        return {
            "command": cmd,
            "returncode": None,
            "stdout": "",
            "stderr": "",
            "timed_out": False,
            "error": str(exc),
        }


def _parse_nmap_xml(path: str) -> dict:
    xml_path = Path(path)
    if not xml_path.exists():
        return {"hosts": [], "summary": "No Nmap XML output produced."}
    try:
        root = ET.fromstring(xml_path.read_text(encoding="utf-8", errors="ignore"))
    except Exception as exc:
        return {"hosts": [], "summary": f"Unable to parse Nmap XML: {exc}"}

    hosts = []
    for host in root.findall("host"):
        addresses = [item.get("addr", "") for item in host.findall("address") if item.get("addr")]
        ports = []
        for port in host.findall("./ports/port"):
            service = port.find("service")
            state_el = port.find("state")
            ports.append(
                {
                    "protocol": port.get("protocol", ""),
                    "port": port.get("portid", ""),
                    "state": state_el.get("state", "") if state_el is not None else "",
                    "service": service.get("name", "") if service is not None else "",
                    "product": service.get("product", "") if service is not None else "",
                    "version": service.get("version", "") if service is not None else "",
                }
            )
        hosts.append({"addresses": addresses, "ports": ports})
    return {"hosts": hosts, "summary": f"Parsed {len(hosts)} host entries from Nmap XML."}


def _run_nmap_scan(target: str, state: dict, call_number: int) -> dict:
    apply_security_profile_defaults(state)
    binary = shutil.which("nmap")
    if not binary:
        return {"available": False, "reason": "nmap is not installed."}
    host = _host_from_target(target)
    if not host:
        return {"available": False, "reason": "No scan host was resolved from the target."}

    timeout = int(state.get("scanner_timeout_seconds", 900))
    top_ports = int(state.get("scanner_top_ports", 2000))
    ports = str(state.get("scanner_ports", "")).strip()
    version_intensity = str(state.get("scanner_nmap_version_intensity", "all")).strip().lower()
    default_scripts = bool(state.get("scanner_nmap_default_scripts", True))
    xml_name = f"scanner_nmap_{call_number}_{uuid.uuid4().hex}.xml"
    xml_path = resolve_output_path(xml_name)
    cmd = [binary, "-Pn", "-sT", "-sV"]
    if version_intensity == "light":
        cmd.append("--version-light")
    else:
        cmd.append("--version-all")
    if default_scripts:
        cmd.append("-sC")
    if ports:
        cmd.extend(["-p", ports])
    else:
        cmd.extend(["--top-ports", str(top_ports)])
    cmd.extend(["-oX", xml_path, host])
    execution = _run_command(cmd, timeout)
    return {
        "available": True,
        "target_host": host,
        "xml_path": xml_path,
        "execution": execution,
        "parsed": _parse_nmap_xml(xml_path),
    }


def _run_zap_baseline(target: str, state: dict, call_number: int) -> dict:
    apply_security_profile_defaults(state)
    binary = shutil.which("zap-baseline.py")
    if not binary:
        return {"available": False, "reason": "zap-baseline.py is not installed."}
    if not _is_http_target(target):
        return {"available": False, "reason": "ZAP baseline requires a full http(s) target URL."}

    timeout = int(state.get("scanner_timeout_seconds", 900))
    max_minutes = int(state.get("zap_max_minutes", 20))
    json_name = f"scanner_zap_{call_number}_{uuid.uuid4().hex}.json"
    html_name = f"scanner_zap_{call_number}_{uuid.uuid4().hex}.html"
    json_path = resolve_output_path(json_name)
    html_path = resolve_output_path(html_name)
    cmd = [binary, "-t", target, "-m", str(max_minutes), "-J", json_path, "-r", html_path]
    execution = _run_command(cmd, timeout)

    parsed = {}
    if Path(json_path).exists():
        try:
            parsed = json.loads(Path(json_path).read_text(encoding="utf-8", errors="ignore"))
        except Exception as exc:
            parsed = {"parse_error": str(exc)}
    return {
        "available": True,
        "target_url": target,
        "json_path": json_path,
        "html_path": html_path,
        "execution": execution,
        "parsed": parsed,
    }


def _capture_screenshot(url: str, filename: str, headless: bool = True) -> dict:
    try:
        from playwright.sync_api import sync_playwright
    except Exception as exc:
        return {"available": False, "reason": f"Playwright is not available: {exc}"}

    screenshot_path = resolve_output_path(filename)
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=headless)
            page = browser.new_page()
            page.goto(url, wait_until="networkidle", timeout=45000)
            title = page.title()
            final_url = page.url
            text_excerpt = page.locator("body").inner_text(timeout=15000)[:5000]
            page.screenshot(path=screenshot_path, full_page=True)
            browser.close()
        return {
            "available": True,
            "screenshot_path": screenshot_path,
            "title": title,
            "final_url": final_url,
            "text_excerpt": text_excerpt,
        }
    except Exception as exc:
        return {"available": True, "error": str(exc), "screenshot_path": screenshot_path}


def _security_appendices(state: dict) -> list[dict]:
    entries = []
    appendix_sources = [
        ("Scope Guard", state.get("security_scope_report")),
        ("Recon", state.get("recon_report") or state.get("web_recon")),
        ("API Surface", state.get("api_surface_map")),
        ("Scanner", state.get("scanner_report")),
        ("Exploitability Review", state.get("exploitability_report")),
        ("Findings", state.get("security_findings_report")),
        ("Evidence", state.get("evidence_report")),
    ]
    for heading, payload in appendix_sources:
        if not payload:
            continue
        entries.append(
            {
                "heading": f"Appendix - {heading}",
                "body": json.dumps(payload, indent=2, ensure_ascii=False)[:35000],
            }
        )
    return entries


def recon_agent(state):
    _, task_content, _ = begin_agent_session(state, "recon_agent")
    _require_authorized_security_scope(state)
    state["recon_agent_calls"] = state.get("recon_agent_calls", 0) + 1
    call_number = state["recon_agent_calls"]
    target = _target_base_url(state, task_content)

    if not state.get("web_recon") and _is_http_target(target):
        state = web_recon_agent(state)
    if not state.get("api_surface_map") and _is_http_target(target):
        try:
            state = api_surface_mapper_agent(state)
        except Exception as exc:
            state["api_surface_map_error"] = str(exc)

    payload = {
        "target": target,
        "web_recon": state.get("web_recon", {}),
        "api_surface_map": state.get("api_surface_map", {}),
        "api_surface_map_error": state.get("api_surface_map_error", ""),
        "tool_availability": {
            "nmap": shutil.which("nmap") is not None,
            "zap_baseline": shutil.which("zap-baseline.py") is not None,
            "playwright": shutil.which("playwright") is not None,
        },
    }
    summary = llm_text(
        f"""You are a defensive recon orchestration agent.

Combine this passive recon evidence into a concise recon brief.
Highlight the externally visible surface, likely next safe checks, and whether the target looks like a web app, API platform, or mixed surface.

Payload:
{json.dumps(payload, indent=2, ensure_ascii=False)[:50000]}
"""
    )
    _write_outputs("recon_agent", call_number, summary, payload)
    state["recon_report"] = payload
    state["draft_response"] = summary
    log_task_update("Recon Agent", f"Recon bundle #{call_number} saved in {get_output_dir()}.")
    return publish_agent_output(
        state,
        "recon_agent",
        summary,
        f"recon_result_{call_number}",
        recipients=["orchestrator_agent", "worker_agent", "reviewer_agent", "scanner_agent", "security_findings_agent"],
    )


def scanner_agent(state):
    _, task_content, _ = begin_agent_session(state, "scanner_agent")
    _require_authorized_security_scope(state)
    state["scanner_agent_calls"] = state.get("scanner_agent_calls", 0) + 1
    call_number = state["scanner_agent_calls"]
    target = _target_base_url(state, task_content)

    payload = {
        "target": target,
        "nmap": _run_nmap_scan(target, state, call_number),
        "zap_baseline": _run_zap_baseline(target, state, call_number),
    }
    summary = llm_text(
        f"""You are a defensive scanner agent.

Review these safe baseline scan results. Do not propose exploitation. Summarize exposed services, web risk signals, and what should be validated by an authorized defender.

Payload:
{json.dumps(payload, indent=2, ensure_ascii=False)[:50000]}
"""
    )
    _write_outputs("scanner_agent", call_number, summary, payload)
    state["scanner_report"] = payload
    state["draft_response"] = summary
    log_task_update("Scanner Agent", f"Scanner bundle #{call_number} saved in {get_output_dir()}.")
    return publish_agent_output(
        state,
        "scanner_agent",
        summary,
        f"scanner_result_{call_number}",
        recipients=["orchestrator_agent", "worker_agent", "reviewer_agent", "security_findings_agent", "exploit_agent", "evidence_agent"],
    )


def exploit_agent(state):
    _, task_content, _ = begin_agent_session(state, "exploit_agent")
    _require_authorized_security_scope(state)
    state["exploit_agent_calls"] = state.get("exploit_agent_calls", 0) + 1
    call_number = state["exploit_agent_calls"]
    target = _target_base_url(state, task_content)

    evidence = {
        "target": target,
        "recon": state.get("recon_report", {}),
        "scanner": state.get("scanner_report", {}),
        "findings": state.get("security_findings_report", {}),
    }
    result = llm_json(
        f"""You are an exploitability review agent inside a defensive, authorized assessment workflow.

You must not generate payloads, step-by-step attack instructions, exploit chains, or service-disruption guidance.
You may only assess likely exploitability at a high level for defenders and recommend safe validation steps.

Evidence:
{json.dumps(evidence, indent=2, ensure_ascii=False)[:50000]}

Return ONLY valid JSON:
{{
  "mode": "analysis_only",
  "payload_generation": "disabled",
  "likely_exploitation_paths": [
    {{
      "title": "high-level issue class",
      "severity": "low|medium|high|critical",
      "reason": "why the issue may be exploitable",
      "defender_validation": "safe validation focus without payloads"
    }}
  ],
  "summary": "brief summary"
}}
""",
        {
            "mode": "analysis_only",
            "payload_generation": "disabled",
            "likely_exploitation_paths": [],
            "summary": "Analysis-only exploitability review completed. Payload generation is disabled.",
        },
    )
    summary = result.get("summary", "Analysis-only exploitability review completed. Payload generation is disabled.")
    _write_outputs("exploit_agent", call_number, summary, result)
    state["exploitability_report"] = result
    state["draft_response"] = summary
    return publish_agent_output(
        state,
        "exploit_agent",
        summary,
        f"exploitability_result_{call_number}",
        recipients=["orchestrator_agent", "worker_agent", "reviewer_agent", "security_findings_agent", "security_report_agent"],
    )


def evidence_agent(state):
    _, task_content, _ = begin_agent_session(state, "evidence_agent")
    _require_authorized_security_scope(state)
    state["evidence_agent_calls"] = state.get("evidence_agent_calls", 0) + 1
    call_number = state["evidence_agent_calls"]
    target = _target_base_url(state, task_content)

    screenshot = {}
    if _is_http_target(target):
        screenshot = _capture_screenshot(
            target,
            f"evidence_capture_{call_number}_{uuid.uuid4().hex}.png",
            headless=bool(state.get("evidence_headless", True)),
        )

    artifact_paths = []
    output_dir = Path(get_output_dir())
    include_prefixes = (
        "security_",
        "web_recon_",
        "api_surface_",
        "recon_agent_",
        "scanner_agent_",
        "exploit_agent_",
        "report_",
    )
    if output_dir.exists():
        for item in sorted(output_dir.iterdir()):
            if item.is_file() and item.name.startswith(include_prefixes):
                artifact_paths.append(str(item))

    payload = {
        "target": target,
        "screenshot": screenshot,
        "artifact_paths": artifact_paths,
        "artifact_count": len(artifact_paths),
    }
    summary = llm_text(
        f"""You are an evidence collection agent.

Summarize the evidence bundle for a defensive security assessment. Note whether screenshots were captured and whether the artifact trail looks complete enough for a client-facing report.

Payload:
{json.dumps(payload, indent=2, ensure_ascii=False)[:45000]}
"""
    )
    _write_outputs("evidence_agent", call_number, summary, payload)
    state["evidence_report"] = payload
    state["draft_response"] = summary
    log_task_update("Evidence Agent", f"Evidence bundle #{call_number} saved in {get_output_dir()}.")
    return publish_agent_output(
        state,
        "evidence_agent",
        summary,
        f"evidence_result_{call_number}",
        recipients=["orchestrator_agent", "worker_agent", "reviewer_agent", "security_report_agent", "report_agent"],
    )


def security_report_agent(state):
    _, task_content, _ = begin_agent_session(state, "security_report_agent")
    _require_authorized_security_scope(state)
    state["security_report_agent_calls"] = state.get("security_report_agent_calls", 0) + 1
    call_number = state["security_report_agent_calls"]
    target = _target_base_url(state, task_content)

    if not state.get("security_findings_report"):
        try:
            state = security_findings_agent(state)
        except Exception as exc:
            state["security_findings_error"] = str(exc)

    target_pages = int(state.get("report_target_pages", 50) or 50)
    state["report_title"] = state.get("report_title") or f"Security Assessment - {target}"
    state["report_formats"] = state.get("report_formats") or ["pdf", "html", "xlsx"]
    state["report_target_pages"] = target_pages
    state["report_appendix_entries"] = _security_appendices(state)
    state["report_requirement"] = state.get("report_requirement") or (
        f"Create a detailed defensive security assessment report for {target}. "
        f"Target approximately {target_pages} pages in the PDF version. "
        "Include executive summary, scope, methodology, recon, scanner outputs, exploitability analysis "
        "(analysis only, no payloads), evidence inventory, prioritized findings, remediation roadmap, and appendices."
    )
    state = report_agent(state)
    report_files = state.get("report_files", {})
    summary = (
        f"Generated security report package for {target}.\n"
        f"Target pages: {target_pages}\n"
        + "\n".join(f"- {fmt}: {path}" for fmt, path in report_files.items())
    )
    payload = {
        "target": target,
        "target_pages": target_pages,
        "report_files": report_files,
        "report_manifest": state.get("report_manifest", {}),
    }
    _write_outputs("security_report_agent", call_number, summary, payload)
    state["security_report_summary"] = summary
    state["draft_response"] = summary
    return publish_agent_output(
        state,
        "security_report_agent",
        summary,
        f"security_report_result_{call_number}",
        recipients=["orchestrator_agent", "worker_agent", "reviewer_agent"],
    )
