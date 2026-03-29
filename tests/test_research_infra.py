import unittest
from tempfile import TemporaryDirectory
from pathlib import Path
from unittest.mock import patch

from tasks.research_infra import parse_document, parse_documents


class ResearchInfraTests(unittest.TestCase):
    def test_parse_document_uses_excel_pdf_fallback_when_primary_read_fails(self):
        with TemporaryDirectory() as tmp:
            excel_path = Path(tmp) / "model.xlsx"
            excel_path.write_bytes(b"placeholder")

            with (
                patch("tasks.research_infra._extract_xlsx_text", side_effect=RuntimeError("primary failed")),
                patch(
                    "tasks.research_infra._extract_excel_text_via_pdf_fallback",
                    return_value=(
                        "Revenue 100\nMargin 55%",
                        {
                            "type": "xlsx",
                            "reader": "soffice_pdf_fallback",
                            "fallback_source": "pdf_conversion",
                            "fallback_pdf_pages": 1,
                        },
                    ),
                ),
            ):
                result = parse_document(str(excel_path))

        self.assertIn("Revenue 100", result["text"])
        self.assertEqual(result["metadata"]["reader"], "soffice_pdf_fallback")
        self.assertEqual(result["metadata"]["fallback_source"], "pdf_conversion")

    def test_parse_documents_continue_on_error_records_fallback_failure(self):
        with TemporaryDirectory() as tmp:
            excel_path = Path(tmp) / "model.xlsx"
            excel_path.write_bytes(b"placeholder")

            with (
                patch("tasks.research_infra._extract_xlsx_text", side_effect=RuntimeError("primary failed")),
                patch(
                    "tasks.research_infra._extract_excel_text_via_pdf_fallback",
                    side_effect=RuntimeError("fallback failed"),
                ),
            ):
                results = parse_documents([str(excel_path)], continue_on_error=True)

        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["metadata"]["type"], "xlsx")
        self.assertIn("fallback failed", results[0]["metadata"].get("error", ""))


if __name__ == "__main__":
    unittest.main()
