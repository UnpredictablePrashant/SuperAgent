import os
import unittest
from pathlib import Path
from types import SimpleNamespace
from tempfile import TemporaryDirectory
from unittest.mock import patch

os.environ.setdefault("OPENAI_API_KEY", "test-openai-key")

from superagent.discovery import build_registry
from superagent.runtime import AgentRuntime


class RuntimeRoutingTests(unittest.TestCase):
    def test_explicit_deep_research_request_routes_to_deep_research_agent(self):
        runtime = AgentRuntime(build_registry())
        state = runtime.build_initial_state("Do deep research on OpenAI's enterprise strategy with citations.")

        with patch("superagent.runtime.llm.invoke") as mock_invoke:
            routed_state = runtime.orchestrator_agent(state)

        self.assertEqual(routed_state["next_agent"], "deep_research_agent")
        self.assertIn("deep research task", routed_state["orchestrator_reason"].lower())
        self.assertFalse(mock_invoke.called, "Deep-research routing should bypass generic LLM router.")
        self.assertTrue(routed_state.get("a2a", {}).get("tasks"), "Expected an A2A task to be created.")
        task = routed_state["a2a"]["tasks"][-1]
        self.assertEqual(task["recipient"], "deep_research_agent")
        self.assertEqual(task.get("state_updates", {}).get("research_query"), routed_state["current_objective"])

    def test_after_deep_research_run_orchestrator_can_finish(self):
        runtime = AgentRuntime(build_registry())
        state = runtime.build_initial_state("Do deep research on battery recycling market trends.")
        state["last_agent"] = "deep_research_agent"
        state["review_pending"] = False
        state["draft_response"] = "Research draft available."

        finish_json = (
            '{"agent":"finish","reason":"done","state_updates":{},'
            '"task_content":"","final_response":"Research completed."}'
        )
        with patch("superagent.runtime.llm.invoke", return_value=SimpleNamespace(content=finish_json)):
            routed_state = runtime.orchestrator_agent(state)

        self.assertEqual(routed_state["next_agent"], "__finish__")
        self.assertEqual(routed_state["final_output"], "Research completed.")

    def test_run_query_accepts_working_directory_in_state_overrides(self):
        runtime = AgentRuntime(build_registry())

        with TemporaryDirectory() as tmp:
            mock_app = SimpleNamespace(invoke=lambda state: {**state, "final_output": "ok"})
            with (
                patch("superagent.runtime.initialize_db"),
                patch("superagent.runtime.insert_run"),
                patch("superagent.runtime.update_run"),
                patch("superagent.runtime.reset_text_file"),
                patch("superagent.runtime.write_text_file"),
                patch("superagent.runtime.append_daily_memory_note"),
                patch("superagent.runtime.append_long_term_memory"),
                patch("superagent.runtime.close_session_memory"),
                patch.object(runtime, "_write_session_record"),
                patch.object(runtime, "_is_agent_available", return_value=True),
                patch.object(runtime, "build_workflow", return_value=mock_app),
            ):
                result = runtime.run_query(
                    "Test query",
                    state_overrides={"working_directory": tmp},
                    create_outputs=False,
                )

        self.assertEqual(result.get("working_directory"), str(Path(tmp).resolve()))
        self.assertEqual(result.get("final_output"), "ok")


if __name__ == "__main__":
    unittest.main()
