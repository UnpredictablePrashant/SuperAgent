import json
import re
import textwrap
import zipfile
from datetime import datetime, timezone
from html import escape
from io import BytesIO
from pathlib import Path

from tasks.a2a_agent_utils import begin_agent_session, publish_agent_output
from tasks.utils import OUTPUT_DIR, llm, log_task_update, normalize_llm_text, resolve_output_path, write_text_file


def _strip_code_fences(text: str) -> str:
    stripped = normalize_llm_text(text).strip()
    if stripped.startswith("```") and stripped.endswith("```"):
        lines = stripped.splitlines()
        if len(lines) >= 2:
            return "\n".join(lines[1:-1]).strip()
    return stripped


def _slugify(value: str) -> str:
    slug = re.sub(r"[^a-zA-Z0-9]+", "_", value.strip().lower()).strip("_")
    return slug or "report"


def _normalize_formats(raw_formats, requirement_text: str) -> list[str]:
    if isinstance(raw_formats, str):
        candidates = [item.strip().lower() for item in raw_formats.split(",")]
    elif isinstance(raw_formats, list):
        candidates = [str(item).strip().lower() for item in raw_formats]
    else:
        candidates = []

    requirement_lower = (requirement_text or "").lower()
    if "pdf" in requirement_lower:
        candidates.append("pdf")
    if "excel" in requirement_lower or "xlsx" in requirement_lower:
        candidates.append("xlsx")
    if "html" in requirement_lower:
        candidates.append("html")

    normalized = []
    for item in candidates:
        if item == "excel":
            item = "xlsx"
        if item in {"pdf", "html", "xlsx"} and item not in normalized:
            normalized.append(item)

    return normalized or ["pdf", "xlsx", "html"]


def _collect_report_context(state: dict) -> dict:
    return {
        "user_query": state.get("user_query", ""),
        "current_objective": state.get("current_objective") or state.get("user_query", ""),
        "plan": state.get("plan", ""),
        "draft_response": state.get("draft_response", ""),
        "final_output": state.get("final_output", ""),
        "search_summary": state.get("search_summary", ""),
        "research_result": state.get("research_result", ""),
        "excel_analysis": state.get("excel_analysis", ""),
        "report_target_pages": state.get("report_target_pages", 0),
        "review_reason": state.get("review_reason", ""),
        "review_decision": state.get("review_decision", ""),
        "security_scope_report": state.get("security_scope_report", {}),
        "web_recon": state.get("web_recon", {}),
        "recon_report": state.get("recon_report", {}),
        "api_surface_map": state.get("api_surface_map", {}),
        "scanner_report": state.get("scanner_report", {}),
        "exploitability_report": state.get("exploitability_report", {}),
        "security_findings_report": state.get("security_findings_report", {}),
        "evidence_report": state.get("evidence_report", {}),
        "report_appendix_entries": state.get("report_appendix_entries", []),
        "long_document_mode": state.get("long_document_mode", False),
        "long_document_title": state.get("long_document_title", ""),
        "long_document_summary": state.get("long_document_summary", ""),
        "long_document_compiled_path": state.get("long_document_compiled_path", ""),
        "long_document_manifest_path": state.get("long_document_manifest_path", ""),
        "long_document_sections_data": state.get("long_document_sections_data", []),
        "long_document_references": state.get("long_document_references", []),
        "long_document_references_path": state.get("long_document_references_path", ""),
        "long_document_visual_index_path": state.get("long_document_visual_index_path", ""),
        "long_document_visual_index_json_path": state.get("long_document_visual_index_json_path", ""),
        "agent_history": state.get("agent_history", [])[-16:],
    }


def _manual_report_fallback(title: str, context: dict) -> dict:
    summary = (
        context.get("final_output")
        or context.get("draft_response")
        or context.get("research_result")
        or context.get("search_summary")
        or context.get("excel_analysis")
        or "No report body was available in the workflow state."
    )
    sections = [
        {
            "heading": "Objective",
            "body": context.get("current_objective") or context.get("user_query") or "No objective provided.",
        },
        {
            "heading": "Summary",
            "body": summary,
        },
    ]
    if context.get("plan"):
        sections.append({"heading": "Plan", "body": context["plan"]})
    if context.get("review_reason"):
        sections.append({"heading": "Review Notes", "body": context["review_reason"]})
    return {
        "title": title,
        "summary": summary,
        "sections": sections,
        "key_points": [],
        "recommendations": [],
    }


def _build_report_structure(requirement_text: str, context: dict, title: str, target_pages: int = 0) -> dict:
    prompt = f"""
    You are a report generation agent inside a multi-agent system.

    Build a professional report from the workflow context and the report requirement.
    {"The PDF target is approximately " + str(target_pages) + " pages, so create enough sections and appendix structure to support a long-form deliverable." if target_pages else "Keep the structure practical and complete."}
    Return ONLY valid JSON in this exact schema:
    {{
      "title": "report title",
      "summary": "2-4 sentence executive summary",
      "sections": [
        {{
          "heading": "section heading",
          "body": "section body"
        }}
      ],
      "key_points": ["point 1", "point 2"],
      "recommendations": ["recommendation 1", "recommendation 2"]
    }}

    Report requirement:
    {requirement_text}

    Preferred title:
    {title}

    Workflow context:
    {json.dumps(context, indent=2, ensure_ascii=False)}
    """
    response = llm.invoke(prompt)
    raw_output = response.content.strip() if hasattr(response, "content") else str(response).strip()

    try:
        data = json.loads(_strip_code_fences(raw_output))
        if not isinstance(data, dict):
            raise ValueError("Report data must be a JSON object.")
        data.setdefault("title", title)
        data.setdefault("summary", context.get("draft_response") or "No summary provided.")
        data.setdefault("sections", [])
        data.setdefault("key_points", [])
        data.setdefault("recommendations", [])
        return data
    except Exception:
        return _manual_report_fallback(title, context)


def _append_appendices(report_data: dict, appendix_entries) -> dict:
    if not isinstance(report_data, dict):
        return report_data
    sections = report_data.setdefault("sections", [])
    if not isinstance(sections, list):
        sections = []
        report_data["sections"] = sections
    existing = {str(section.get("heading", "")).strip() for section in sections if isinstance(section, dict)}
    for item in appendix_entries or []:
        if not isinstance(item, dict):
            continue
        heading = str(item.get("heading", "")).strip() or "Appendix"
        body = str(item.get("body", "")).strip()
        if not body or heading in existing:
            continue
        sections.append({"heading": heading, "body": body})
        existing.add(heading)
    return report_data


def _render_report_text(report_data: dict) -> str:
    lines = [report_data["title"], "=" * len(report_data["title"]), "", "Executive Summary", report_data["summary"], ""]

    if report_data.get("key_points"):
        lines.append("Key Points")
        for point in report_data["key_points"]:
            lines.append(f"- {point}")
        lines.append("")

    for section in report_data.get("sections", []):
        heading = section.get("heading", "Section")
        body = section.get("body", "")
        lines.append(heading)
        lines.append(body)
        lines.append("")

    if report_data.get("recommendations"):
        lines.append("Recommendations")
        for item in report_data["recommendations"]:
            lines.append(f"- {item}")

    return "\n".join(lines).strip()


def _render_html(report_data: dict, generated_at: str, formats: list[str]) -> str:
    section_html = []
    for section in report_data.get("sections", []):
        section_html.append(
            "<section>"
            f"<h2>{escape(section.get('heading', 'Section'))}</h2>"
            f"<p>{escape(section.get('body', ''))}</p>"
            "</section>"
        )

    key_points = "".join(f"<li>{escape(point)}</li>" for point in report_data.get("key_points", []))
    recommendations = "".join(
        f"<li>{escape(item)}</li>" for item in report_data.get("recommendations", [])
    )

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{escape(report_data["title"])}</title>
  <style>
    :root {{
      --ink: #1d2433;
      --muted: #5a6478;
      --panel: #ffffff;
      --line: #d6dce8;
      --bg: linear-gradient(135deg, #eef3ff 0%, #f7f4ea 100%);
    }}
    body {{
      margin: 0;
      font-family: Georgia, "Times New Roman", serif;
      color: var(--ink);
      background: var(--bg);
    }}
    main {{
      max-width: 900px;
      margin: 32px auto;
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 18px;
      padding: 36px;
      box-shadow: 0 18px 40px rgba(29, 36, 51, 0.08);
    }}
    h1, h2 {{
      margin: 0 0 12px;
      line-height: 1.2;
    }}
    p, li {{
      line-height: 1.7;
      color: var(--muted);
    }}
    .meta {{
      margin-bottom: 24px;
      padding-bottom: 16px;
      border-bottom: 1px solid var(--line);
      font-size: 14px;
      color: var(--muted);
    }}
    .summary {{
      font-size: 18px;
      color: var(--ink);
    }}
    .tag {{
      display: inline-block;
      margin-right: 8px;
      margin-top: 8px;
      padding: 6px 10px;
      border-radius: 999px;
      border: 1px solid var(--line);
      background: #f8fafc;
      font-size: 12px;
    }}
  </style>
</head>
<body>
  <main>
    <h1>{escape(report_data["title"])}</h1>
    <div class="meta">
      <div>Generated at: {escape(generated_at)}</div>
      <div>Formats: {" ".join(f'<span class="tag">{escape(item)}</span>' for item in formats)}</div>
    </div>
    <p class="summary">{escape(report_data["summary"])}</p>
    {"<section><h2>Key Points</h2><ul>" + key_points + "</ul></section>" if key_points else ""}
    {''.join(section_html)}
    {"<section><h2>Recommendations</h2><ul>" + recommendations + "</ul></section>" if recommendations else ""}
  </main>
</body>
</html>"""


def _wrap_pdf_lines(text: str, width: int = 92) -> list[str]:
    lines = []
    for paragraph in text.splitlines():
        if not paragraph.strip():
            lines.append("")
            continue
        lines.extend(textwrap.wrap(paragraph, width=width) or [""])
    return lines


def _escape_pdf_text(value: str) -> str:
    return value.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")


def _render_pdf_bytes(text: str) -> bytes:
    lines = _wrap_pdf_lines(text)
    page_height = 792
    margin_top = 742
    leading = 14
    lines_per_page = 48
    pages = [lines[i : i + lines_per_page] for i in range(0, max(len(lines), 1), lines_per_page)] or [[]]

    objects = []

    def add_object(payload: str | bytes) -> int:
        objects.append(payload if isinstance(payload, bytes) else payload.encode("latin-1", errors="replace"))
        return len(objects)

    font_id = add_object("<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>")
    page_ids = []
    content_ids = []

    for page_lines in pages:
        stream_lines = ["BT", "/F1 11 Tf", f"50 {margin_top} Td"]
        first_line = True
        for line in page_lines:
            escaped_line = _escape_pdf_text(line)
            if first_line:
                stream_lines.append(f"({escaped_line}) Tj")
                first_line = False
            else:
                stream_lines.append(f"0 -{leading} Td")
                stream_lines.append(f"({escaped_line}) Tj")
        if first_line:
            stream_lines.append("( ) Tj")
        stream_lines.append("ET")
        stream = "\n".join(stream_lines).encode("latin-1", errors="replace")
        content_id = add_object(
            b"<< /Length " + str(len(stream)).encode("ascii") + b" >>\nstream\n" + stream + b"\nendstream"
        )
        content_ids.append(content_id)
        page_ids.append(add_object(""))

    pages_id = add_object("")
    for idx, page_id in enumerate(page_ids):
        page_object = (
            f"<< /Type /Page /Parent {pages_id} 0 R /MediaBox [0 0 612 {page_height}] "
            f"/Resources << /Font << /F1 {font_id} 0 R >> >> /Contents {content_ids[idx]} 0 R >>"
        )
        objects[page_id - 1] = page_object.encode("latin-1")

    kids = " ".join(f"{page_id} 0 R" for page_id in page_ids)
    objects[pages_id - 1] = f"<< /Type /Pages /Count {len(page_ids)} /Kids [{kids}] >>".encode("latin-1")
    catalog_id = add_object(f"<< /Type /Catalog /Pages {pages_id} 0 R >>")

    buffer = bytearray(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
    offsets = [0]
    for index, payload in enumerate(objects, start=1):
        offsets.append(len(buffer))
        buffer.extend(f"{index} 0 obj\n".encode("ascii"))
        buffer.extend(payload)
        buffer.extend(b"\nendobj\n")

    xref_offset = len(buffer)
    buffer.extend(f"xref\n0 {len(objects) + 1}\n".encode("ascii"))
    buffer.extend(b"0000000000 65535 f \n")
    for offset in offsets[1:]:
        buffer.extend(f"{offset:010d} 00000 n \n".encode("ascii"))
    buffer.extend(
        (
            f"trailer\n<< /Size {len(objects) + 1} /Root {catalog_id} 0 R >>\n"
            f"startxref\n{xref_offset}\n%%EOF"
        ).encode("ascii")
    )
    return bytes(buffer)


def _column_letter(index: int) -> str:
    result = ""
    current = index
    while current >= 0:
        current, remainder = divmod(current, 26)
        result = chr(65 + remainder) + result
        current -= 1
    return result


def _excel_cell(row_idx: int, col_idx: int, value: str) -> str:
    cell_ref = f"{_column_letter(col_idx)}{row_idx}"
    safe_value = escape(value or "", quote=False)
    return (
        f'<c r="{cell_ref}" t="inlineStr"><is><t xml:space="preserve">{safe_value}</t></is></c>'
    )


def _render_xlsx_rows(report_data: dict, generated_at: str) -> list[list[str]]:
    rows = [
        ["Field", "Value"],
        ["Title", report_data["title"]],
        ["Generated At", generated_at],
        ["Executive Summary", report_data.get("summary", "")],
    ]
    for index, point in enumerate(report_data.get("key_points", []), start=1):
        rows.append([f"Key Point {index}", point])
    for section in report_data.get("sections", []):
        rows.append([section.get("heading", "Section"), section.get("body", "")])
    for index, item in enumerate(report_data.get("recommendations", []), start=1):
        rows.append([f"Recommendation {index}", item])
    return rows


def _render_xlsx_bytes(report_data: dict, generated_at: str) -> bytes:
    rows = _render_xlsx_rows(report_data, generated_at)
    sheet_rows = []
    for row_index, row in enumerate(rows, start=1):
        cells = [_excel_cell(row_index, col_index, str(value)) for col_index, value in enumerate(row)]
        sheet_rows.append(f'<row r="{row_index}">{"".join(cells)}</row>')

    sheet_xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
        '<sheetViews><sheetView workbookViewId="0"/></sheetViews>'
        '<sheetFormatPr defaultRowHeight="15"/>'
        '<cols><col min="1" max="1" width="24" customWidth="1"/>'
        '<col min="2" max="2" width="100" customWidth="1"/></cols>'
        f'<sheetData>{"".join(sheet_rows)}</sheetData>'
        '</worksheet>'
    )

    workbook_xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
        'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
        '<sheets><sheet name="Report" sheetId="1" r:id="rId1"/></sheets>'
        '</workbook>'
    )

    workbook_rels = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Id="rId1" '
        'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" '
        'Target="worksheets/sheet1.xml"/>'
        '<Relationship Id="rId2" '
        'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" '
        'Target="styles.xml"/>'
        '</Relationships>'
    )

    root_rels = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Id="rId1" '
        'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" '
        'Target="xl/workbook.xml"/>'
        '<Relationship Id="rId2" '
        'Type="http://schemas.openxmlformats.org/package/2006/relationships/metadata/core-properties" '
        'Target="docProps/core.xml"/>'
        '<Relationship Id="rId3" '
        'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/extended-properties" '
        'Target="docProps/app.xml"/>'
        '</Relationships>'
    )

    content_types = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
        '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
        '<Default Extension="xml" ContentType="application/xml"/>'
        '<Override PartName="/xl/workbook.xml" '
        'ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
        '<Override PartName="/xl/worksheets/sheet1.xml" '
        'ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
        '<Override PartName="/xl/styles.xml" '
        'ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/>'
        '<Override PartName="/docProps/core.xml" '
        'ContentType="application/vnd.openxmlformats-package.core-properties+xml"/>'
        '<Override PartName="/docProps/app.xml" '
        'ContentType="application/vnd.openxmlformats-officedocument.extended-properties+xml"/>'
        '</Types>'
    )

    styles_xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<styleSheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
        '<fonts count="1"><font><sz val="11"/><name val="Calibri"/></font></fonts>'
        '<fills count="1"><fill><patternFill patternType="none"/></fill></fills>'
        '<borders count="1"><border/></borders>'
        '<cellStyleXfs count="1"><xf/></cellStyleXfs>'
        '<cellXfs count="1"><xf xfId="0"/></cellXfs>'
        '<cellStyles count="1"><cellStyle name="Normal" xfId="0" builtinId="0"/></cellStyles>'
        '</styleSheet>'
    )

    created_at = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    core_xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<cp:coreProperties xmlns:cp="http://schemas.openxmlformats.org/package/2006/metadata/core-properties" '
        'xmlns:dc="http://purl.org/dc/elements/1.1/" '
        'xmlns:dcterms="http://purl.org/dc/terms/" '
        'xmlns:dcmitype="http://purl.org/dc/dcmitype/" '
        'xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">'
        f'<dc:title>{escape(report_data["title"], quote=False)}</dc:title>'
        '<dc:creator>multi-agent report_agent</dc:creator>'
        f'<dcterms:created xsi:type="dcterms:W3CDTF">{created_at}</dcterms:created>'
        f'<dcterms:modified xsi:type="dcterms:W3CDTF">{created_at}</dcterms:modified>'
        '</cp:coreProperties>'
    )

    app_xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Properties xmlns="http://schemas.openxmlformats.org/officeDocument/2006/extended-properties" '
        'xmlns:vt="http://schemas.openxmlformats.org/officeDocument/2006/docPropsVTypes">'
        '<Application>multi-agent report_agent</Application>'
        '</Properties>'
    )

    buffer = BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("[Content_Types].xml", content_types)
        archive.writestr("_rels/.rels", root_rels)
        archive.writestr("docProps/app.xml", app_xml)
        archive.writestr("docProps/core.xml", core_xml)
        archive.writestr("xl/workbook.xml", workbook_xml)
        archive.writestr("xl/_rels/workbook.xml.rels", workbook_rels)
        archive.writestr("xl/styles.xml", styles_xml)
        archive.writestr("xl/worksheets/sheet1.xml", sheet_xml)
    return buffer.getvalue()


def report_agent(state):
    active_task, task_content, _ = begin_agent_session(state, "report_agent")
    state["report_agent_calls"] = state.get("report_agent_calls", 0) + 1
    call_number = state["report_agent_calls"]

    requirement_text = (
        state.get("report_requirement")
        or task_content
        or state.get("current_objective")
        or state.get("user_query", "")
    )
    report_title = state.get("report_title") or f"Workflow Report {call_number}"
    report_formats = _normalize_formats(state.get("report_formats"), requirement_text)
    generated_at = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")

    context = _collect_report_context(state)
    target_pages = int(state.get("report_target_pages", 0) or 0)
    report_data = _build_report_structure(requirement_text, context, report_title, target_pages=target_pages)
    report_data = _append_appendices(report_data, state.get("report_appendix_entries"))
    report_text = _render_report_text(report_data)

    base_name = state.get("report_output_basename") or _slugify(report_data["title"])
    output_paths = {}

    log_task_update(
        "Report Agent",
        f"Report pass #{call_number} started.",
        f"Formats: {', '.join(report_formats)}",
    )

    if "html" in report_formats:
        html_filename = f"{base_name}_{call_number}.html"
        write_text_file(html_filename, _render_html(report_data, generated_at, report_formats))
        output_paths["html"] = resolve_output_path(html_filename)

    if "pdf" in report_formats:
        pdf_filename = f"{base_name}_{call_number}.pdf"
        pdf_path = Path(resolve_output_path(pdf_filename))
        pdf_path.write_bytes(_render_pdf_bytes(report_text))
        output_paths["pdf"] = str(pdf_path)

    if "xlsx" in report_formats:
        xlsx_filename = f"{base_name}_{call_number}.xlsx"
        xlsx_path = Path(resolve_output_path(xlsx_filename))
        xlsx_path.write_bytes(_render_xlsx_bytes(report_data, generated_at))
        output_paths["xlsx"] = str(xlsx_path)

    manifest = {
        "title": report_data["title"],
        "formats": report_formats,
        "files": output_paths,
        "generated_at": generated_at,
        "summary": report_data.get("summary", ""),
    }
    manifest_filename = f"{base_name}_manifest_{call_number}.json"
    summary_filename = f"{base_name}_summary_{call_number}.txt"
    write_text_file(manifest_filename, json.dumps(manifest, indent=2, ensure_ascii=False))
    write_text_file(summary_filename, report_text)

    state["report_data"] = report_data
    state["report_summary"] = report_text
    state["report_files"] = output_paths
    state["report_manifest"] = manifest
    state["draft_response"] = (
        f"Generated report '{report_data['title']}' in formats: {', '.join(report_formats)}.\n"
        + "\n".join(f"- {fmt}: {path}" for fmt, path in output_paths.items())
    )

    log_task_update(
        "Report Agent",
        f"Report files saved under {OUTPUT_DIR}.",
        state["draft_response"],
    )
    state = publish_agent_output(
        state,
        "report_agent",
        state["draft_response"],
        f"report_result_{call_number}",
        recipients=["orchestrator_agent", "worker_agent", "reviewer_agent"],
    )
    return state
