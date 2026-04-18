import unittest

from kendr.orchestration.intent_discovery import build_intent_candidates


class IntentDiscoveryTests(unittest.TestCase):
    def test_build_intent_candidates_prioritizes_project_build_over_general_task(self):
        result = build_intent_candidates(
            user_query="Build a production-ready web app and plan the implementation.",
            current_objective="Build a production-ready web app and plan the implementation.",
            flags={
                "security_assessment": False,
                "local_command": False,
                "shell_plan": False,
                "github": False,
                "registry_discovery": False,
                "communication_digest": False,
                "project_build": True,
                "long_document": False,
                "deep_research": False,
                "superrag": False,
                "local_drive": False,
            },
            planner_signals={"score": 7, "threshold": 4, "explicit_plan_request": True, "risk_markers": 1},
        )

        self.assertEqual(result["selected"]["intent_type"], "project_build")
        self.assertTrue(result["selected"]["requires_planner"])
        self.assertEqual(result["selected"]["execution_mode"], "plan")
        self.assertGreaterEqual(len(result["candidates"]), 2)

    def test_build_intent_candidates_suppresses_long_document_when_deep_research_is_present(self):
        result = build_intent_candidates(
            user_query="Do deep research and produce a long report with citations.",
            current_objective="Do deep research and produce a long report with citations.",
            flags={
                "security_assessment": False,
                "local_command": False,
                "shell_plan": False,
                "github": False,
                "registry_discovery": False,
                "communication_digest": False,
                "project_build": False,
                "long_document": True,
                "deep_research": True,
                "superrag": False,
                "local_drive": False,
            },
            planner_signals={"score": 6, "threshold": 4, "explicit_plan_request": False, "risk_markers": 0},
        )

        intent_types = [candidate["intent_type"] for candidate in result["candidates"]]
        self.assertIn("deep_research", intent_types)
        self.assertNotIn("long_document", intent_types)
        self.assertEqual(result["selected"]["intent_type"], "deep_research")


if __name__ == "__main__":
    unittest.main()
