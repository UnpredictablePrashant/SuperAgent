import os
import unittest
from tempfile import TemporaryDirectory
from unittest.mock import patch

os.environ.setdefault("OPENAI_API_KEY", "test-openai-key")

from tasks.excel_tasks import excel_agent


class ExcelAgentTests(unittest.TestCase):
    def test_excel_agent_skips_without_paths(self):
        state = {
            "user_query": "Analyze workbook",
            "current_objective": "Analyze workbook",
        }

        with (
            patch("tasks.a2a_agent_utils.record_work_note"),
            patch("tasks.excel_tasks.log_task_update"),
            patch("tasks.excel_tasks.write_text_file"),
        ):
            result = excel_agent(state)

        self.assertTrue(result.get("excel_skipped"))
        self.assertEqual(result.get("excel_skip_reason"), "no_excel_paths")
        self.assertIn("No spreadsheet files were routed", result.get("excel_analysis", ""))

    def test_excel_agent_uses_routed_paths_and_skips_missing_entries(self):
        with TemporaryDirectory() as tmp:
            good_path = os.path.join(tmp, "model.xlsx")
            missing_path = os.path.join(tmp, "missing.xlsx")
            with open(good_path, "wb") as handle:
                handle.write(b"placeholder")

            state = {
                "user_query": "Analyze workbook",
                "current_objective": "Analyze workbook",
                "local_drive_handler_routes": {"excel_agent": [good_path, missing_path]},
                "excel_working_directory": tmp,
            }

            with (
                patch("tasks.a2a_agent_utils.record_work_note"),
                patch("tasks.excel_tasks.log_task_update"),
                patch("tasks.excel_tasks.write_text_file"),
                patch(
                    "tasks.excel_tasks._load_workbook_data",
                    return_value={
                        "file_name": "model.xlsx",
                        "file_path": good_path,
                        "sheets": [{"sheet_name": "Sheet1", "rows": [["col"], [1], [2]]}],
                    },
                ),
                patch(
                    "tasks.excel_tasks._summarize_sheet",
                    return_value={
                        "sheet_name": "Sheet1",
                        "row_count": 2,
                        "column_count": 1,
                        "columns": [],
                        "sample_records": [{"col": 1}],
                    },
                ),
                patch("tasks.excel_tasks._render_workbook_summary", return_value="Workbook summary"),
                patch("tasks.excel_tasks._interpret_summary_with_llm", return_value="Excel analysis"),
            ):
                result = excel_agent(state)

        self.assertFalse(result.get("excel_skipped"))
        self.assertEqual(len(result.get("excel_workbook_summaries", [])), 1)
        self.assertEqual(len(result.get("excel_skipped_files", [])), 1)
        self.assertIn("Skipped: 1", result.get("excel_analysis", ""))

    def test_excel_agent_uses_parse_document_fallback_after_primary_failure(self):
        with TemporaryDirectory() as tmp:
            failing_path = os.path.join(tmp, "broken.xlsx")
            with open(failing_path, "wb") as handle:
                handle.write(b"placeholder")

            state = {
                "user_query": "Analyze workbook",
                "current_objective": "Analyze workbook",
                "local_drive_handler_routes": {"excel_agent": [failing_path]},
                "excel_working_directory": tmp,
            }

            with (
                patch("tasks.a2a_agent_utils.record_work_note"),
                patch("tasks.excel_tasks.log_task_update"),
                patch("tasks.excel_tasks.write_text_file"),
                patch("tasks.excel_tasks._load_workbook_data", side_effect=RuntimeError("openpyxl failed")),
                patch(
                    "tasks.excel_tasks.parse_document",
                    return_value={
                        "path": failing_path,
                        "text": "Recovered from PDF fallback",
                        "metadata": {"reader": "soffice_pdf_fallback", "fallback_source": "pdf_conversion"},
                    },
                ),
                patch("tasks.excel_tasks._interpret_summary_with_llm", return_value="Excel analysis"),
            ):
                result = excel_agent(state)

        self.assertFalse(result.get("excel_skipped"))
        self.assertEqual(len(result.get("excel_fallback_documents", [])), 1)
        self.assertEqual(result["excel_fallback_documents"][0]["metadata"]["reader"], "soffice_pdf_fallback")


if __name__ == "__main__":
    unittest.main()
