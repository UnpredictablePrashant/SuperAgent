from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from kendr.skill_manager import execute_skill_by_slug


class EverydaySkillTests(unittest.TestCase):
    def test_file_finder_returns_name_matches(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "budget-notes.txt").write_text("March budget", encoding="utf-8")
            (root / "other.txt").write_text("nothing here", encoding="utf-8")

            with patch("kendr.skill_manager.get_user_skill", return_value=None):
                result = execute_skill_by_slug(
                    "file-finder",
                    {"query": "budget", "root_path": str(root), "search_content": False},
                )

        self.assertTrue(result["success"], result.get("error"))
        self.assertEqual(result["output"]["matches"][0]["relative_path"], "budget-notes.txt")

    def test_doc_summarizer_summarizes_text_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "notes.txt"
            path.write_text("Line one\nLine two", encoding="utf-8")
            with (
                patch("kendr.skill_manager.get_user_skill", return_value=None),
                patch("kendr.skill_manager._llm_text", return_value="Short summary"),
            ):
                result = execute_skill_by_slug("doc-summarizer", {"file_path": str(path), "style": "short"})

        self.assertTrue(result["success"], result.get("error"))
        self.assertEqual(result["output"]["summary"], "Short summary")

    def test_spreadsheet_basic_summarizes_csv(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "budget.csv"
            path.write_text("category,amount\nRent,1000\nFood,250\n", encoding="utf-8")
            with (
                patch("kendr.skill_manager.get_user_skill", return_value=None),
                patch("kendr.skill_manager._llm_text", return_value="Totals look correct"),
            ):
                result = execute_skill_by_slug(
                    "spreadsheet-basic",
                    {"file_path": str(path), "question": "Tell me the totals"},
                )

        self.assertTrue(result["success"], result.get("error"))
        self.assertIn("budget.csv", result["output"]["summary"])
        self.assertEqual(result["output"]["analysis"], "Totals look correct")

    def test_meeting_notes_formats_output(self):
        with (
            patch("kendr.skill_manager.get_user_skill", return_value=None),
            patch("kendr.skill_manager._llm_text", return_value="1. Send recap\n2. Confirm date"),
        ):
            result = execute_skill_by_slug("meeting-notes", {"notes": "Discussed release date", "style": "action_items"})

        self.assertTrue(result["success"], result.get("error"))
        self.assertIn("Send recap", result["output"]["result"])

    def test_todo_planner_formats_plan(self):
        with (
            patch("kendr.skill_manager.get_user_skill", return_value=None),
            patch("kendr.skill_manager._llm_text", return_value="Morning: pay bills\nAfternoon: finish report"),
        ):
            result = execute_skill_by_slug("todo-planner", {"tasks": "pay bills\nfinish report", "horizon": "today"})

        self.assertTrue(result["success"], result.get("error"))
        self.assertIn("Morning", result["output"]["plan"])

    def test_travel_helper_returns_llm_summary_without_provider(self):
        with (
            patch("kendr.skill_manager.get_user_skill", return_value=None),
            patch("kendr.skill_manager._llm_text", return_value="Take the morning train and pack light."),
        ):
            result = execute_skill_by_slug(
                "travel-helper",
                {"request": "Plan a day trip from Boston to New York", "origin": "Boston", "destination": "New York"},
            )

        self.assertTrue(result["success"], result.get("error"))
        self.assertEqual(result["output"]["travel_data"]["source"], "planner")
        self.assertIn("morning train", result["output"]["summary"])

    def test_travel_helper_uses_serpapi_only_when_requested(self):
        with (
            patch.dict(os.environ, {"SERP_API_KEY": "test-serp-key"}, clear=False),
            patch("kendr.skill_manager.get_user_skill", return_value=None),
            patch("kendr.skill_manager._llm_text", return_value="Take the express route."),
            patch("tasks.travel_tasks._serpapi_request", return_value={"route": "express"}),
        ):
            result = execute_skill_by_slug(
                "travel-helper",
                {
                    "request": "Plan a fast route from Boston to New York",
                    "origin": "Boston",
                    "destination": "New York",
                    "provider": "serpapi",
                },
            )

        self.assertTrue(result["success"], result.get("error"))
        self.assertEqual(result["output"]["travel_data"]["source"], "serpapi")

    def test_message_draft_returns_draft_text(self):
        with (
            patch("kendr.skill_manager.get_user_skill", return_value=None),
            patch("kendr.skill_manager._llm_text", return_value="Hi team, can we move the meeting to Friday?"),
        ):
            result = execute_skill_by_slug(
                "message-draft",
                {"recipient": "team", "goal": "move the meeting to Friday", "channel": "email"},
            )

        self.assertTrue(result["success"], result.get("error"))
        self.assertIn("Friday", result["output"]["draft"])

    def test_calendar_agenda_rejects_invalid_window(self):
        with patch("kendr.skill_manager.get_user_skill", return_value=None):
            result = execute_skill_by_slug("calendar-agenda", {"window": "month"})

        self.assertFalse(result["success"])
        self.assertIn("today", result["error"])

    def test_file_reader_requires_file_path(self):
        with patch("kendr.skill_manager.get_user_skill", return_value=None):
            result = execute_skill_by_slug("file-reader", {})

        self.assertFalse(result["success"])
        self.assertIn("file_path", result["error"])


if __name__ == "__main__":
    unittest.main()
