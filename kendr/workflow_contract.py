from __future__ import annotations

from typing import Any, Mapping


DEEP_RESEARCH_WORKFLOW_TYPES = {"deep_research", "long_document"}


def build_approval_request(
    *,
    scope: str,
    title: str,
    summary: str,
    sections: list[dict[str, Any]] | None = None,
    accept_label: str = "Accept",
    reject_label: str = "Reject",
    suggest_label: str = "Suggestion",
    help_text: str = "",
    artifact_paths: list[str] | None = None,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "scope": str(scope or "").strip(),
        "title": str(title or "").strip(),
        "summary": str(summary or "").strip(),
        "sections": _normalize_sections(sections or []),
        "actions": {
            "accept_label": str(accept_label or "Accept").strip(),
            "reject_label": str(reject_label or "Reject").strip(),
            "suggest_label": str(suggest_label or "Suggestion").strip(),
        },
        "help_text": str(help_text or "").strip(),
        "artifact_paths": [str(path).strip() for path in (artifact_paths or []) if str(path).strip()],
        "metadata": dict(metadata or {}),
    }


def normalize_approval_request(value: Any) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        return {}
    sections = _normalize_sections(value.get("sections", []))
    actions = value.get("actions", {})
    if not isinstance(actions, Mapping):
        actions = {}
    metadata = value.get("metadata", {})
    if not isinstance(metadata, Mapping):
        metadata = {}
    return {
        "scope": str(value.get("scope", "") or "").strip(),
        "title": str(value.get("title", "") or "").strip(),
        "summary": str(value.get("summary", "") or "").strip(),
        "sections": sections,
        "actions": {
            "accept_label": str(actions.get("accept_label", "Accept") or "Accept").strip(),
            "reject_label": str(actions.get("reject_label", "Reject") or "Reject").strip(),
            "suggest_label": str(actions.get("suggest_label", "Suggestion") or "Suggestion").strip(),
        },
        "help_text": str(value.get("help_text", "") or "").strip(),
        "artifact_paths": [str(path).strip() for path in (value.get("artifact_paths", []) or []) if str(path).strip()],
        "metadata": {str(key): metadata[key] for key in metadata},
    }


def approval_request_to_text(request: Mapping[str, Any] | None) -> str:
    normalized = normalize_approval_request(request)
    if not normalized:
        return ""
    lines: list[str] = []
    title = normalized.get("title", "")
    summary = normalized.get("summary", "")
    if title:
        lines.append(title)
    if summary:
        if lines:
            lines.append("")
        lines.append(summary)
    for section in normalized.get("sections", []):
        section_title = str(section.get("title", "") or "").strip()
        items = [str(item).strip() for item in (section.get("items", []) or []) if str(item).strip()]
        if not section_title and not items:
            continue
        if lines:
            lines.append("")
        if section_title:
            lines.append(section_title)
        for item in items:
            lines.append(f"- {item}")
    artifact_paths = normalized.get("artifact_paths", []) or []
    if artifact_paths:
        if lines:
            lines.append("")
        lines.append("Artifacts")
        for path in artifact_paths:
            lines.append(f"- {path}")
    help_text = normalized.get("help_text", "")
    if help_text:
        if lines:
            lines.append("")
        lines.append(help_text)
    return "\n".join(lines).strip()


def is_deep_research_workflow_type(workflow_type: str | None) -> bool:
    return str(workflow_type or "").strip().lower() in DEEP_RESEARCH_WORKFLOW_TYPES


def _normalize_sections(sections: list[dict[str, Any]] | list[Any]) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    for entry in sections or []:
        if not isinstance(entry, Mapping):
            continue
        title = str(entry.get("title", "") or "").strip()
        items = [str(item).strip() for item in (entry.get("items", []) or []) if str(item).strip()]
        if not title and not items:
            continue
        normalized.append({"title": title, "items": items})
    return normalized
