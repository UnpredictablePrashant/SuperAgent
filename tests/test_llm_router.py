import os
import unittest
from unittest.mock import patch


class LlmRouterTests(unittest.TestCase):
    def test_provider_specific_model_beats_legacy_global_override(self):
        from kendr.llm_router import get_model_for_provider

        with patch.dict(os.environ, {
            "KENDR_MODEL": "legacy-global-model",
            "ANTHROPIC_MODEL": "claude-sonnet-4-6",
        }, clear=False):
            model = get_model_for_provider("anthropic")

        self.assertEqual(model, "claude-sonnet-4-6")

    def test_provider_status_keeps_current_model_in_selectable_choices(self):
        from kendr.llm_router import provider_status

        with patch.dict(os.environ, {
            "OPENAI_API_KEY": "test-key",
            "OPENAI_MODEL_GENERAL": "gpt-5.1-preview",
        }, clear=False):
            status = provider_status("openai")

        self.assertTrue(status["ready"])
        self.assertIn("gpt-5.1-preview", status["selectable_models"])


if __name__ == "__main__":
    unittest.main()
