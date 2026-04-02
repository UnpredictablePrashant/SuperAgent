import json
import math
import re
import zipfile
from collections import Counter
from pathlib import Path
from xml.etree import ElementTree as ET

from tasks.a2a_agent_utils import begin_agent_session, publish_agent_output
from tasks.research_infra import parse_document
from tasks.utils import OUTPUT_DIR, llm, log_task_update, write_text_file, normalize_llm_text


XML_NS = {
    "main": "http://schemas.openxmlformats.org/spreadsheetml/2006/main",
    "rel": "http://schemas.openxmlformats.org/package/2006/relationships",
}


def _column_index_from_ref(cell_ref: str) -> int:
    letters = "".join(ch for ch in cell_ref if ch.isalpha()).upper()
    total = 0
    for ch in letters:
        total = total * 26 + (ord(ch) - ord("A") + 1)
    return max(total - 1, 0)


def _normalize_value(value):
    if value is None:
        return None
    if isinstance(value, str):
        stripped = value.strip()
        if not stripped:
            return None
        lowered = stripped.lower()
        if lowered in {"true", "false"}:
            return lowered == "true"
        try:
            if "." in stripped:
                return float(stripped)
            return int(stripped)
        except ValueError:
            return stripped
    return value


def _load_shared_strings(archive: zipfile.ZipFile) -> list[str]:
    if "xl/sharedStrings.xml" not in archive.namelist():
        return []
    root = ET.fromstring(archive.read("xl/sharedStrings.xml"))
    values = []
    for item in root.findall("main:si", XML_NS):
        texts = [node.text or "" for node in item.findall(".//main:t", XML_NS)]
        values.append("".join(texts))
    return values


def _load_sheet_map(archive: zipfile.ZipFile) -> list[tuple[str, str]]:
    workbook_root = ET.fromstring(archive.read("xl/workbook.xml"))
    rel_root = ET.fromstring(archive.read("xl/_rels/workbook.xml.rels"))
    rel_map = {
        rel.attrib["Id"]: rel.attrib["Target"]
        for rel in rel_root.findall("rel:Relationship", XML_NS)
    }

    sheet_map = []
    for sheet in workbook_root.findall("main:sheets/main:sheet", XML_NS):
        name = sheet.attrib["name"]
        rel_id = sheet.attrib.get("{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id")
        target = rel_map.get(rel_id, "")
        if target and not target.startswith("xl/"):
            target = f"xl/{target}"
        sheet_map.append((name, target))
    return sheet_map


def _parse_sheet_rows(archive: zipfile.ZipFile, sheet_path: str, shared_strings: list[str]) -> list[list[object]]:
    root = ET.fromstring(archive.read(sheet_path))
    rows = []

    for row in root.findall("main:sheetData/main:row", XML_NS):
        current = []
        cursor = 0
        for cell in row.findall("main:c", XML_NS):
            ref = cell.attrib.get("r", "")
            column_index = _column_index_from_ref(ref) if ref else cursor
            while cursor < column_index:
                current.append(None)
                cursor += 1

            cell_type = cell.attrib.get("t")
            value = None

            if cell_type == "inlineStr":
                text_node = cell.find("main:is/main:t", XML_NS)
                value = text_node.text if text_node is not None else None
            else:
                value_node = cell.find("main:v", XML_NS)
                raw_value = value_node.text if value_node is not None else None
                if raw_value is not None:
                    if cell_type == "s":
                        shared_index = int(raw_value)
                        value = shared_strings[shared_index] if 0 <= shared_index < len(shared_strings) else raw_value
                    elif cell_type == "b":
                        value = raw_value == "1"
                    else:
                        value = raw_value

            current.append(_normalize_value(value))
            cursor += 1

        if any(value is not None for value in current):
            rows.append(current)
    return rows


def _load_workbook_data(file_path: Path) -> dict:
    if file_path.suffix.lower() not in {".xlsx", ".xlsm"}:
        raise ValueError("excel_agent currently supports .xlsx/.xlsm files.")

    with zipfile.ZipFile(file_path) as archive:
        shared_strings = _load_shared_strings(archive)
        sheet_map = _load_sheet_map(archive)
        sheets = []

        for sheet_name, sheet_path in sheet_map:
            rows = _parse_sheet_rows(archive, sheet_path, shared_strings)
            sheets.append(
                {
                    "sheet_name": sheet_name,
                    "rows": rows,
                }
            )

    return {
        "file_name": file_path.name,
        "file_path": str(file_path),
        "sheets": sheets,
    }


def _rows_to_records(rows: list[list[object]]) -> tuple[list[str], list[dict]]:
    if not rows:
        return [], []

    header_row = rows[0]
    headers = []
    seen = Counter()
    for index, value in enumerate(header_row):
        header = str(value).strip() if value is not None else f"column_{index + 1}"
        if not header:
            header = f"column_{index + 1}"
        seen[header] += 1
        if seen[header] > 1:
            header = f"{header}_{seen[header]}"
        headers.append(header)

    records = []
    for row in rows[1:]:
        padded = row + [None] * max(0, len(headers) - len(row))
        records.append({headers[i]: padded[i] if i < len(padded) else None for i in range(len(headers))})
    return headers, records


def _numeric_stats(values: list[float]) -> dict:
    if not values:
        return {}
    total = sum(values)
    count = len(values)
    mean = total / count
    variance = sum((value - mean) ** 2 for value in values) / count
    return {
        "count": count,
        "min": min(values),
        "max": max(values),
        "mean": round(mean, 4),
        "sum": round(total, 4),
        "stddev": round(math.sqrt(variance), 4),
    }


def _summarize_sheet(sheet: dict, max_rows: int) -> dict:
    headers, records = _rows_to_records(sheet["rows"])
    sample_records = records[:max_rows]
    column_summaries = []

    for header in headers:
        values = [record.get(header) for record in records if record.get(header) is not None]
        numeric_values = [value for value in values if isinstance(value, (int, float)) and not isinstance(value, bool)]
        text_values = [str(value) for value in values[:5]]
        column_summaries.append(
            {
                "column": header,
                "non_empty_count": len(values),
                "unique_sample": list(dict.fromkeys(text_values))[:5],
                "numeric_stats": _numeric_stats(numeric_values),
            }
        )

    return {
        "sheet_name": sheet["sheet_name"],
        "row_count": len(records),
        "column_count": len(headers),
        "columns": column_summaries,
        "sample_records": sample_records,
    }


def _render_workbook_summary(workbook_summary: dict) -> str:
    lines = [
        f"Excel file: {workbook_summary['file_name']}",
        f"Path: {workbook_summary['file_path']}",
        "",
    ]
    for sheet in workbook_summary["sheets"]:
        lines.append(f"Sheet: {sheet['sheet_name']}")
        lines.append(f"- Rows: {sheet['row_count']}")
        lines.append(f"- Columns: {sheet['column_count']}")
        lines.append("- Column summaries:")
        for column in sheet["columns"]:
            lines.append(f"  - {column['column']}: non-empty={column['non_empty_count']}")
            if column["numeric_stats"]:
                lines.append(f"    numeric_stats={json.dumps(column['numeric_stats'], ensure_ascii=False)}")
            if column["unique_sample"]:
                lines.append(f"    sample_values={json.dumps(column['unique_sample'], ensure_ascii=False)}")
        if sheet["sample_records"]:
            lines.append("- Sample rows:")
            for record in sheet["sample_records"][:3]:
                lines.append(f"  - {json.dumps(record, ensure_ascii=False)}")
        lines.append("")
    return "\n".join(lines).strip()


def _interpret_summary_with_llm(objective: str, workbook_text: str, analysis_question: str) -> str:
    prompt = f"""
    You are an Excel analysis agent.

    Objective:
    {objective}

    Workbook summary:
    {workbook_text}

    User question:
    {analysis_question or "Provide a concise explanation of the data, what stands out, and any important insights."}

    Return a clear, practical analysis. Mention important patterns, anomalies, and recommended next checks when useful.
    """
    response = llm.invoke(prompt)
    return normalize_llm_text(response.content if hasattr(response, "content") else response).strip()


def excel_agent(state):
    active_task, task_content, _ = begin_agent_session(state, "excel_agent")
    state["excel_agent_calls"] = state.get("excel_agent_calls", 0) + 1
    call_number = state["excel_agent_calls"]

    objective = state.get("current_objective") or state.get("user_query", "")
    analysis_question = state.get("excel_question") or task_content or objective
    max_rows = int(state.get("excel_max_sample_rows", 5))
    working_directory = state.get("excel_working_directory", ".")

    primary_path = state.get("excel_file_path") or state.get("excel_path")
    candidate_paths: list[str] = []
    if primary_path:
        candidate_paths.append(str(primary_path))

    multi_paths = state.get("excel_file_paths") or state.get("excel_paths") or []
    if isinstance(multi_paths, list):
        candidate_paths.extend(str(item) for item in multi_paths if str(item).strip())

    routed_paths = []
    local_routes = state.get("local_drive_handler_routes", {})
    if isinstance(local_routes, dict):
        raw = local_routes.get("excel_agent", [])
        if isinstance(raw, list):
            routed_paths = [str(item) for item in raw if str(item).strip()]
    candidate_paths.extend(routed_paths)

    resolved_paths: list[Path] = []
    seen: set[str] = set()
    for raw in candidate_paths:
        raw_value = str(raw or "").strip()
        if not raw_value:
            continue
        file_path = Path(raw_value)
        if not file_path.is_absolute():
            file_path = Path(working_directory).resolve() / file_path
        normalized = str(file_path.resolve())
        if normalized in seen:
            continue
        seen.add(normalized)
        resolved_paths.append(file_path)

    if not resolved_paths:
        summary = (
            "No spreadsheet files were routed to excel_agent. "
            "Skipped Excel analysis and continued without blocking the workflow."
        )
        write_text_file(f"excel_agent_output_{call_number}.txt", summary)
        state["excel_workbook_summary"] = {}
        state["excel_workbook_summaries"] = []
        state["excel_summary_text"] = ""
        state["excel_analysis"] = summary
        state["excel_skipped"] = True
        state["excel_skip_reason"] = "no_excel_paths"
        state["draft_response"] = summary
        log_task_update("Excel Agent", f"Analysis pass #{call_number} skipped: no spreadsheet files detected.")
        return publish_agent_output(
            state,
            "excel_agent",
            summary,
            f"excel_analysis_{call_number}",
            recipients=["orchestrator_agent", "worker_agent", "reviewer_agent"],
        )

    log_task_update("Excel Agent", f"Analysis pass #{call_number} started.", "\n".join(str(path) for path in resolved_paths))
    workbook_summaries = []
    fallback_documents = []
    skipped_files = []
    for index, file_path in enumerate(resolved_paths, start=1):
        log_task_update("Excel Agent", f"[{index}/{len(resolved_paths)}] Reading workbook.", str(file_path))
        if not file_path.exists():
            skipped_files.append({"path": str(file_path), "error": "file_not_found"})
            log_task_update("Excel Agent", f"[{index}/{len(resolved_paths)}] Skipped workbook.", f"{file_path}\nreason: file_not_found")
            continue
        if file_path.suffix.lower() not in {".xlsx", ".xlsm"}:
            skipped_files.append({"path": str(file_path), "error": "unsupported_extension"})
            log_task_update(
                "Excel Agent",
                f"[{index}/{len(resolved_paths)}] Skipped workbook.",
                f"{file_path}\nreason: unsupported_extension",
            )
            continue
        try:
            workbook_data = _load_workbook_data(file_path)
            summarized_sheets = [_summarize_sheet(sheet, max_rows=max_rows) for sheet in workbook_data["sheets"]]
            workbook_summaries.append(
                {
                    "file_name": workbook_data["file_name"],
                    "file_path": workbook_data["file_path"],
                    "sheets": summarized_sheets,
                }
            )
            log_task_update("Excel Agent", f"[{index}/{len(resolved_paths)}] Parsed workbook.", str(file_path))
        except Exception as exc:
            try:
                fallback_doc = parse_document(str(file_path))
                fallback_text = str(fallback_doc.get("text", "") or "").strip()
                if fallback_text:
                    fallback_documents.append(
                        {
                            "file_name": file_path.name,
                            "file_path": str(file_path),
                            "text": fallback_text[:12000],
                            "metadata": fallback_doc.get("metadata", {}),
                            "source_error": str(exc),
                        }
                    )
                    log_task_update(
                        "Excel Agent",
                        f"[{index}/{len(resolved_paths)}] Used fallback text extraction.",
                        f"{file_path}\nreader: {fallback_doc.get('metadata', {}).get('reader', 'fallback')}",
                    )
                    continue
            except Exception as fallback_exc:
                skipped_files.append(
                    {
                        "path": str(file_path),
                        "error": f"primary={exc}; fallback={fallback_exc}",
                    }
                )
                log_task_update(
                    "Excel Agent",
                    f"[{index}/{len(resolved_paths)}] Skipped workbook.",
                    f"{file_path}\nreason: primary={exc}; fallback={fallback_exc}",
                )
                continue

            skipped_files.append({"path": str(file_path), "error": str(exc)})
            log_task_update("Excel Agent", f"[{index}/{len(resolved_paths)}] Skipped workbook.", f"{file_path}\nreason: {exc}")

    if not workbook_summaries and not fallback_documents:
        summary = (
            "No supported spreadsheet content could be parsed. "
            "Skipped Excel analysis and continued without blocking the workflow."
        )
        if skipped_files:
            summary = (
                f"{summary}\n\nExcel file handling summary:\n"
                f"- Attempted: {len(resolved_paths)}\n"
                f"- Parsed: 0\n"
                f"- Skipped: {len(skipped_files)}"
            )
        write_text_file(f"excel_agent_output_{call_number}.txt", summary)
        state["excel_workbook_summary"] = {}
        state["excel_workbook_summaries"] = []
        state["excel_summary_text"] = ""
        state["excel_analysis"] = summary
        state["excel_skipped"] = True
        state["excel_skip_reason"] = "no_parsed_workbooks"
        state["excel_skipped_files"] = skipped_files
        state["draft_response"] = summary
        return publish_agent_output(
            state,
            "excel_agent",
            summary,
            f"excel_analysis_{call_number}",
            recipients=["orchestrator_agent", "worker_agent", "reviewer_agent"],
        )

    workbook_text_blocks = []
    for workbook_summary in workbook_summaries:
        workbook_text_blocks.append(_render_workbook_summary(workbook_summary))
    for fallback_item in fallback_documents:
        workbook_text_blocks.append(
            "\n".join(
                [
                    f"Excel fallback text source: {fallback_item['file_name']}",
                    f"Path: {fallback_item['file_path']}",
                    f"Fallback metadata: {json.dumps(fallback_item.get('metadata', {}), ensure_ascii=False)}",
                    "Extracted text:",
                    fallback_item["text"],
                ]
            )
        )
    workbook_text = "\n\n---\n\n".join(workbook_text_blocks)
    analysis_text = _interpret_summary_with_llm(objective, workbook_text, analysis_question)
    if skipped_files:
        analysis_text = (
            f"{analysis_text}\n\nExcel file handling summary:\n"
            f"- Attempted: {len(resolved_paths)}\n"
            f"- Parsed: {len(workbook_summaries)}\n"
            f"- Skipped: {len(skipped_files)}"
        )

    raw_filename = f"excel_agent_raw_{call_number}.json"
    summary_filename = f"excel_agent_summary_{call_number}.txt"
    output_filename = f"excel_agent_output_{call_number}.txt"

    write_text_file(raw_filename, json.dumps(workbook_summaries, indent=2, ensure_ascii=False))
    write_text_file(summary_filename, workbook_text)
    write_text_file(output_filename, analysis_text)

    state["excel_workbook_summary"] = workbook_summaries[0] if workbook_summaries else {}
    state["excel_workbook_summaries"] = workbook_summaries
    state["excel_fallback_documents"] = fallback_documents
    state["excel_summary_text"] = workbook_text
    state["excel_analysis"] = analysis_text
    state["excel_skipped"] = False
    state["excel_skip_reason"] = ""
    state["excel_skipped_files"] = skipped_files
    state["draft_response"] = analysis_text

    log_task_update(
        "Excel Agent",
        f"Excel analysis saved to {OUTPUT_DIR}/{output_filename}",
        analysis_text,
    )
    state = publish_agent_output(
        state,
        "excel_agent",
        analysis_text,
        f"excel_analysis_{call_number}",
        recipients=["orchestrator_agent", "worker_agent", "reviewer_agent"],
    )
    return state
