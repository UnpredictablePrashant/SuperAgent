from __future__ import annotations

import os
import re


SECURITY_SCAN_PROFILES = {"baseline", "standard", "deep", "extensive"}

_SECURITY_HINTS = [
    "security",
    "vulnerability",
    "vuln",
    "scan",
    "scanner",
    "nmap",
    "zap",
    "pentest",
    "penetration test",
    "recon",
    "sast",
    "tls",
    "idor",
    "bola",
    "cve",
    "owasp",
    "api audit",
]


def is_security_assessment_query(text: str) -> bool:
    cleaned = (text or "").strip().lower()
    if not cleaned:
        return False
    return any(hint in cleaned for hint in _SECURITY_HINTS)


def authorization_process_text(target_hint: str = "") -> str:
    target_line = f"Target: {target_hint}\n" if target_hint else ""
    return (
        "Security authorization is required before any scanning starts.\n"
        f"{target_line}"
        "Required process:\n"
        "1. Confirm you own the target or have explicit written permission from the owner.\n"
        "2. Define scope clearly (domains/IPs/routes/assets) and approved testing window.\n"
        "3. Record authorization evidence (ticket ID, contract ID, or signed approval reference).\n"
        "4. Run with explicit CLI authorization fields before scanning.\n"
        "CLI example:\n"
        "kendr run --security-authorized --security-target-url https://example.com --security-authorization-note 'Ticket SEC-123 approved by owner' 'perform defensive security assessment'"
    )


def _profile_defaults(profile: str) -> dict:
    if profile == "baseline":
        return {
            "scanner_top_ports": 200,
            "zap_max_minutes": 3,
            "security_timeout": 20,
            "security_api_doc_limit": 18,
            "security_web_recon_paths": ["/robots.txt", "/sitemap.xml"],
            "scanner_nmap_default_scripts": False,
            "scanner_nmap_version_intensity": "light",
        }
    if profile == "standard":
        return {
            "scanner_top_ports": 1000,
            "zap_max_minutes": 8,
            "security_timeout": 30,
            "security_api_doc_limit": 26,
            "security_web_recon_paths": ["/robots.txt", "/sitemap.xml", "/.well-known/security.txt", "/security.txt"],
            "scanner_nmap_default_scripts": True,
            "scanner_nmap_version_intensity": "light",
        }
    if profile == "extensive":
        return {
            "scanner_top_ports": 5000,
            "zap_max_minutes": 35,
            "security_timeout": 45,
            "security_api_doc_limit": 60,
            "security_web_recon_paths": [
                "/robots.txt",
                "/sitemap.xml",
                "/.well-known/security.txt",
                "/security.txt",
                "/.well-known/assetlinks.json",
                "/.well-known/apple-app-site-association",
                "/crossdomain.xml",
                "/clientaccesspolicy.xml",
                "/favicon.ico",
                "/humans.txt",
            ],
            "scanner_nmap_default_scripts": True,
            "scanner_nmap_version_intensity": "all",
        }
    # default: deep
    return {
        "scanner_top_ports": 2000,
        "zap_max_minutes": 20,
        "security_timeout": 40,
        "security_api_doc_limit": 45,
        "security_web_recon_paths": [
            "/robots.txt",
            "/sitemap.xml",
            "/.well-known/security.txt",
            "/security.txt",
            "/.well-known/assetlinks.json",
            "/.well-known/apple-app-site-association",
            "/crossdomain.xml",
            "/clientaccesspolicy.xml",
        ],
        "scanner_nmap_default_scripts": True,
        "scanner_nmap_version_intensity": "all",
    }


def apply_security_profile_defaults(state: dict) -> dict:
    requested = str(state.get("security_scan_profile") or os.getenv("SECURITY_SCAN_PROFILE", "deep")).strip().lower()
    profile = requested if requested in SECURITY_SCAN_PROFILES else "deep"
    defaults = _profile_defaults(profile)
    state["security_scan_profile"] = profile
    for key, value in defaults.items():
        if key not in state or state.get(key) in {None, ""}:
            state[key] = value
    return state


def _normalize_target(target: str) -> str:
    return re.sub(r"\s+", " ", (target or "").strip())


def require_security_authorization(state: dict, target: str) -> None:
    authorized = bool(state.get("security_authorized", False))
    note = str(state.get("security_authorization_note", "")).strip()
    normalized_target = _normalize_target(target)

    if not normalized_target:
        raise PermissionError(
            "security_target_url is required for defensive security assessment.\n"
            + authorization_process_text()
        )

    if not authorized:
        raise PermissionError(
            "security_authorized flag is missing; scanning is blocked.\n"
            + authorization_process_text(normalized_target)
        )

    if not note:
        raise PermissionError(
            "security_authorization_note is required (ticket/approval reference) before scanning.\n"
            + authorization_process_text(normalized_target)
        )
