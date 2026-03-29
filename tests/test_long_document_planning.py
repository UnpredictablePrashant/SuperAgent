import os
import unittest
from unittest.mock import patch

os.environ.setdefault("OPENAI_API_KEY", "test-openai-key")

from kendr.discovery import build_registry
from kendr.runtime import AgentRuntime
from tasks.long_document_tasks import long_document_agent


class LongDocumentPlanningTests(unittest.TestCase):
    def test_long_document_agent_requires_subplan_approval_before_execution(self):
        fake_setup_snapshot = {
            "available_agents": [str(card.get("agent_name", "")) for card in build_registry().agent_cards()],
            "disabled_agents": {},
            "setup_actions": [],
            "summary_text": "",
        }
        with patch("kendr.runtime.build_setup_snapshot", return_value=fake_setup_snapshot):
            runtime = AgentRuntime(build_registry())
            state = runtime.build_initial_state("Create a 50-page market structure report.")
            state["current_objective"] = "Create a 50-page market structure report."
            state["long_document_mode"] = True
            state["long_document_pages"] = 50

            fake_outline = {
                "title": "Market Structure Report",
                "sections": [
                    {
                        "id": 1,
                        "title": "Industry Baseline",
                        "objective": "Set the baseline facts and market structure.",
                        "key_questions": ["What defines the market?", "Who are the major players?"],
                        "target_pages": 5,
                    }
                ],
            }

            with (
                patch("tasks.long_document_tasks._build_outline", return_value=fake_outline),
                patch("tasks.long_document_tasks.write_text_file"),
                patch("tasks.long_document_tasks.update_planning_file"),
                patch("tasks.long_document_tasks.log_task_update"),
            ):
                result = long_document_agent(state)

        self.assertTrue(result["long_document_plan_waiting_for_approval"])
        self.assertEqual(result["long_document_plan_status"], "pending")
        self.assertEqual(result["pending_user_input_kind"], "subplan_approval")
        self.assertEqual(result["approval_pending_scope"], "long_document_plan")
        self.assertIn("approve", result["draft_response"].lower())


if __name__ == "__main__":
    unittest.main()
