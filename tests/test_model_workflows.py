import unittest


class ModelWorkflowRecommendationTests(unittest.TestCase):
    def test_glm_is_preferred_for_best_ocr_when_available(self):
        from kendr.model_workflows import build_workflow_recommendations

        statuses = [
            {
                "provider": "glm",
                "ready": True,
                "model": "glm-5",
                "selectable_model_details": [
                    {
                        "name": "glm-5",
                        "family": "glm",
                        "context_window": 131072,
                        "capabilities": {
                            "tool_calling": True,
                            "vision": True,
                            "structured_output": True,
                            "reasoning": True,
                            "native_web_search": False,
                        },
                        "agent_capable": True,
                    },
                    {
                        "name": "glm-4-flash",
                        "family": "glm",
                        "context_window": 131072,
                        "capabilities": {
                            "tool_calling": True,
                            "vision": True,
                            "structured_output": True,
                            "reasoning": True,
                            "native_web_search": False,
                        },
                        "agent_capable": True,
                    },
                ],
            },
            {
                "provider": "openai",
                "ready": True,
                "model": "gpt-4o-mini",
                "selectable_model_details": [
                    {
                        "name": "gpt-4o-mini",
                        "family": "openai",
                        "context_window": 128000,
                        "capabilities": {
                            "tool_calling": True,
                            "vision": True,
                            "structured_output": True,
                            "reasoning": False,
                            "native_web_search": True,
                        },
                        "agent_capable": True,
                    },
                    {
                        "name": "gpt-5.4",
                        "family": "openai",
                        "context_window": 400000,
                        "capabilities": {
                            "tool_calling": True,
                            "vision": True,
                            "structured_output": True,
                            "reasoning": True,
                            "native_web_search": True,
                        },
                        "agent_capable": True,
                    },
                ],
            },
            {
                "provider": "ollama",
                "ready": True,
                "model": "qwen2.5",
                "selectable_model_details": [
                    {
                        "name": "qwen2.5",
                        "family": "qwen",
                        "context_window": 131072,
                        "capabilities": {
                            "tool_calling": True,
                            "vision": False,
                            "structured_output": False,
                            "reasoning": False,
                            "native_web_search": False,
                        },
                        "agent_capable": False,
                    }
                ],
            },
        ]

        payload = build_workflow_recommendations(statuses, multi_model=True)
        workflow = next(item for item in payload["workflows"] if item["id"] == "ocr_ingestion")
        best_ocr = workflow["best"]["stages"][0]
        cheapest_extract = workflow["cheapest"]["stages"][1]

        self.assertEqual(best_ocr["stage"], "ocr")
        self.assertEqual(best_ocr["provider"], "glm")
        self.assertEqual(cheapest_extract["stage"], "extract")
        self.assertIn(cheapest_extract["provider"], {"glm", "ollama"})

    def test_single_model_mode_can_fall_back_to_one_model(self):
        from kendr.model_workflows import build_workflow_recommendations

        statuses = [
            {
                "provider": "openai",
                "ready": True,
                "model": "gpt-5.4-mini",
                "selectable_model_details": [
                    {
                        "name": "gpt-5.4-mini",
                        "family": "openai",
                        "context_window": 400000,
                        "capabilities": {
                            "tool_calling": True,
                            "vision": True,
                            "structured_output": True,
                            "reasoning": True,
                            "native_web_search": True,
                        },
                        "agent_capable": True,
                    }
                ],
            }
        ]

        payload = build_workflow_recommendations(statuses, multi_model=False)
        workflow = next(item for item in payload["workflows"] if item["id"] == "deep_research_report")

        self.assertFalse(payload["enabled"])
        self.assertEqual(payload["mode"], "single-model")
        self.assertTrue(workflow["best"]["available"])
        self.assertEqual(workflow["best"]["mode_used"], "single-model")
        self.assertFalse(workflow["best"]["uses_multiple_models"])

    def test_workflow_payload_includes_stage_options(self):
        from kendr.model_workflows import build_workflow_recommendations

        statuses = [
            {
                "provider": "openai",
                "ready": True,
                "model": "gpt-5.4-mini",
                "selectable_model_details": [
                    {
                        "name": "gpt-5.4-mini",
                        "family": "openai",
                        "context_window": 400000,
                        "capabilities": {
                            "tool_calling": True,
                            "vision": True,
                            "structured_output": True,
                            "reasoning": True,
                            "native_web_search": True,
                        },
                        "agent_capable": True,
                    }
                ],
            }
        ]

        payload = build_workflow_recommendations(statuses, multi_model=True)
        workflow = next(item for item in payload["workflows"] if item["id"] == "deep_research_report")
        stage_options = workflow.get("stage_options", [])

        self.assertIsInstance(stage_options, list)
        self.assertTrue(stage_options)
        route_option = next(item for item in stage_options if item["stage"] == "router")
        self.assertEqual(route_option["label"], "Route")
        self.assertIsInstance(route_option.get("candidates"), list)
        self.assertTrue(route_option["candidates"])
        self.assertEqual(route_option["candidates"][0]["provider"], "openai")


if __name__ == "__main__":
    unittest.main()
