import os
import unittest
from unittest.mock import patch


class LlmRouterTests(unittest.TestCase):
    def test_local_models_not_agent_capable(self):
        from kendr.llm_router import is_agent_capable_model

        self.assertFalse(is_agent_capable_model("llama3.2", "ollama"))
        self.assertTrue(is_agent_capable_model("gpt-5.1", "openai"))

    def test_context_window_tracks_newer_openai_models(self):
        from kendr.llm_router import get_context_window

        self.assertEqual(get_context_window("gpt-5.1"), 400000)
        self.assertEqual(get_context_window("gpt-5.4-mini"), 400000)
        self.assertEqual(get_context_window("gpt-4.1"), 1047576)

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

    def test_provider_status_merges_openai_sdk_models(self):
        from kendr.llm_router import provider_status

        class _Model:
            def __init__(self, model_id):
                self.id = model_id

        class _Models:
            def list(self):
                return [_Model("gpt-5.4"), _Model("gpt-5-nano")]

        class _Client:
            def __init__(self, **kwargs):
                self.models = _Models()

        with (
            patch.dict(os.environ, {
                "OPENAI_API_KEY": "test-key",
                "OPENAI_MODEL_GENERAL": "gpt-4o-mini",
            }, clear=False),
            patch("openai.OpenAI", _Client),
        ):
            status = provider_status("openai")

        self.assertIn("gpt-5.4", status["selectable_models"])
        self.assertIn("gpt-5-nano", status["selectable_models"])

    def test_provider_status_exposes_openai_model_badges(self):
        from kendr.llm_router import provider_status

        class _Model:
            def __init__(self, model_id):
                self.id = model_id

        class _Models:
            def list(self):
                return [_Model("gpt-5.4"), _Model("gpt-5-nano"), _Model("gpt-4o-mini")]

        class _Client:
            def __init__(self, **kwargs):
                self.models = _Models()

        with (
            patch.dict(os.environ, {
                "OPENAI_API_KEY": "test-key",
                "OPENAI_MODEL_GENERAL": "gpt-4o-mini",
            }, clear=False),
            patch("openai.OpenAI", _Client),
        ):
            status = provider_status("openai")

        self.assertEqual(status["model_badges"].get("gpt-5.4"), ["latest", "best"])
        self.assertEqual(status["model_badges"].get("gpt-5-nano"), ["cheapest"])

    def test_provider_status_surfaces_model_fetch_error(self):
        from kendr.llm_router import provider_status

        class _Models:
            def list(self):
                raise RuntimeError("invalid api key")

        class _Client:
            def __init__(self, **kwargs):
                self.models = _Models()

        with (
            patch.dict(os.environ, {
                "OPENAI_API_KEY": "test-key",
                "OPENAI_MODEL_GENERAL": "gpt-4o-mini",
            }, clear=False),
            patch("openai.OpenAI", _Client),
        ):
            status = provider_status("openai")

        self.assertIn("invalid api key", status["model_fetch_error"])

    def test_xai_provider_uses_xai_models_api(self):
        from kendr.llm_router import provider_status

        class _Response:
            def raise_for_status(self):
                return None

            def json(self):
                return {"data": [{"id": "grok-4"}, {"id": "grok-4.20-beta-latest-non-reasoning"}]}

        with (
            patch.dict(os.environ, {
                "XAI_API_KEY": "test-key",
                "XAI_MODEL": "grok-4",
            }, clear=False),
            patch("requests.get", return_value=_Response()) as mock_get,
        ):
            status = provider_status("xai")

        mock_get.assert_called_once()
        self.assertIn("grok-4", status["selectable_models"])
        self.assertIn("grok-4.20-beta-latest-non-reasoning", status["selectable_models"])

    def test_provider_status_includes_model_capabilities(self):
        from kendr.llm_router import provider_status

        with patch.dict(os.environ, {
            "OPENAI_API_KEY": "test-key",
            "OPENAI_MODEL_GENERAL": "gpt-5",
        }, clear=False):
            status = provider_status("openai")

        self.assertTrue(status["model_capabilities"]["tool_calling"])
        self.assertTrue(status["model_capabilities"]["vision"])
        self.assertTrue(status["model_capabilities"]["structured_output"])


if __name__ == "__main__":
    unittest.main()
