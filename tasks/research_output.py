from __future__ import annotations

from pathlib import Path


def _clean_line(value) -> str:
    text = " ".join(str(value or "").strip().split())
    return text


def _dedupe_preserve(values: list[str]) -> list[str]:
    deduped: list[str] = []
    seen: set[str] = set()
    for value in values:
        if not value or value in seen:
            continue
        seen.add(value)
        deduped.append(value)
    return deduped


def normalize_report_bullets(values) -> list[str]:
    normalized: list[str] = []
    for value in values or []:
        text = _clean_line(value)
        if not text:
            continue
        if text.startswith(("- ", "* ")):
            text = text[2:].strip()
        elif text.startswith("-") or text.startswith("*"):
            text = text[1:].strip()
        normalized.append(text)
    return _dedupe_preserve(normalized)


def split_sources_section(text: str) -> tuple[str, list[str]]:
    body = str(text or "").strip()
    if not body:
        return "", []
    markers = ("\nSources:\n", "\nSources:\r\n")
    for marker in markers:
        if marker in body:
            prefix, suffix = body.split(marker, 1)
            return prefix.strip(), normalize_report_bullets(suffix.splitlines())
    if body.startswith("Sources:\n"):
        return "", normalize_report_bullets(body[len("Sources:\n"):].splitlines())
    return body, []


def has_next_steps_section(text: str) -> bool:
    normalized = str(text or "").strip().lower()
    if not normalized:
        return False
    return any(
        marker in normalized
        for marker in (
            "\nrecommended next steps",
            "\nnext steps",
            "\nrecommended actions",
            "recommended next steps:",
            "next steps:",
        )
    )


def render_phase0_report(
    *,
    title: str,
    objective: str,
    findings: str,
    coverage_lines=None,
    next_steps=None,
    sources_lines=None,
) -> str:
    normalized_coverage = normalize_report_bullets(coverage_lines)
    normalized_next_steps = normalize_report_bullets(next_steps)
    normalized_sources = normalize_report_bullets(sources_lines)

    lines: list[str] = [str(title or "Research Brief").strip(), "=" * len(str(title or "Research Brief").strip()), ""]

    objective_text = str(objective or "").strip()
    if objective_text:
        lines.extend(["Objective:", objective_text, ""])

    if normalized_coverage:
        lines.append("Coverage:")
        lines.extend(f"- {item}" for item in normalized_coverage)
        lines.append("")

    findings_text = str(findings or "").strip()
    if findings_text:
        lines.extend(["Findings:", findings_text, ""])

    if normalized_next_steps and not has_next_steps_section(findings_text):
        lines.append("Recommended Next Steps:")
        lines.extend(f"- {item}" for item in normalized_next_steps)
        lines.append("")

    if normalized_sources:
        lines.append("Sources:")
        lines.extend(f"- {item}" for item in normalized_sources)
        lines.append("")

    return "\n".join(lines).strip()


def display_artifact_path(path_value: str, *, output_root: str = "output") -> str:
    raw = str(path_value or "").strip()
    if not raw:
        return ""

    normalized = raw.replace("\\", "/").lstrip("./")
    root = str(output_root or "output").strip().replace("\\", "/").strip("/")
    if root:
        prefix = f"{root}/"
        if normalized.startswith(prefix):
            return normalized[len(prefix) :]
        token = f"/{prefix}"
        if token in normalized:
            return normalized.split(token, 1)[1]

    candidate = Path(raw)
    if candidate.is_absolute():
        return candidate.name or normalized
    return normalized


def render_artifact_lines(artifacts: list[tuple[str, str]], *, output_root: str = "output") -> list[str]:
    lines: list[str] = []
    seen: set[str] = set()
    for label, path_value in artifacts:
        display_value = display_artifact_path(path_value, output_root=output_root)
        if not label or not display_value:
            continue
        line = f"- {label}: {display_value}"
        if line in seen:
            continue
        seen.add(line)
        lines.append(line)
    return lines
