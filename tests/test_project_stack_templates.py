import os
import unittest

os.environ.setdefault("OPENAI_API_KEY", "test-openai-key")

from plugin_templates.project_stacks import available_stacks, load_stack_template
from tasks.project_blueprint_tasks import _detect_stack, _extract_stack_requirements


class ProjectStackTemplateTests(unittest.TestCase):
    def test_mern_microservices_template_is_registered(self):
        stacks = available_stacks()
        self.assertIn("mern_microservices_mongodb", stacks)

    def test_mern_microservices_template_shape(self):
        template = load_stack_template("mern_microservices_mongodb")
        self.assertIsInstance(template, dict)
        self.assertEqual(template["tech_stack"]["database"], "mongodb")
        self.assertEqual(template["tech_stack"]["orm"], "mongoose")
        self.assertIn("services/auth-service/src/index.ts", template["base_directory_structure"])
        self.assertIn("frontend/src/main.tsx", template["base_directory_structure"])

    def test_detect_stack_prefers_mern_for_mern_prompt(self):
        detected = _detect_stack(
            "Build a MERN microservices ecommerce platform with React frontend, Express APIs, and MongoDB."
        )
        self.assertEqual(detected, "mern_microservices_mongodb")

    def test_extract_stack_requirements_from_context(self):
        requirements = _extract_stack_requirements(
            "Use React on the frontend, Express on the backend, and MongoDB. Prefer TypeScript."
        )
        self.assertEqual(requirements.get("framework"), "express+react")
        self.assertEqual(requirements.get("database"), "mongodb")
        self.assertEqual(requirements.get("language"), "typescript")


if __name__ == "__main__":
    unittest.main()
