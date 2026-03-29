import os
import unittest

os.environ.setdefault("OPENAI_API_KEY", "test-openai-key")

from tasks.planning_tasks import normalize_plan_data


class PlanningTaskTests(unittest.TestCase):
    def test_normalize_plan_data_excludes_planner_from_execution_steps(self):
        raw_plan = {
            "summary": "Test plan",
            "steps": [
                {
                    "id": "step-1",
                    "title": "Lock scope",
                    "agent": "planner_agent",
                    "task": "Refine the scope note.",
                    "substeps": [
                        {
                            "id": "step-1.1",
                            "title": "List requirements",
                            "agent": "planner_agent",
                            "task": "List the report requirements.",
                        }
                    ],
                },
                {
                    "id": "step-2",
                    "title": "Catalog files",
                    "agent": "local_drive_agent",
                    "task": "Catalog the local files and summarize the usable evidence.",
                    "success_criteria": "A file catalog and evidence summary exist.",
                },
            ],
        }

        plan_data = normalize_plan_data(raw_plan, "Build a fundraising report.")

        self.assertEqual(len(plan_data["steps"]), 2)
        self.assertEqual(len(plan_data["execution_steps"]), 1)
        self.assertEqual(plan_data["execution_steps"][0]["id"], "step-2")
        self.assertEqual(plan_data["execution_steps"][0]["agent"], "local_drive_agent")

    def test_normalize_plan_data_flattens_wrapper_steps_to_leaf_execution_steps(self):
        raw_plan = {
            "summary": "Test plan",
            "steps": [
                {
                    "id": "step-1",
                    "title": "Ingest documents",
                    "agent": "document_ingestion_agent",
                    "task": "Ingest and structure the document corpus.",
                    "success_criteria": "The corpus is ready for analysis.",
                    "substeps": [
                        {
                            "id": "step-1.1",
                            "title": "Catalog drive files",
                            "agent": "local_drive_agent",
                            "task": "Build the local file inventory.",
                            "success_criteria": "A file manifest exists.",
                        },
                        {
                            "id": "step-1.2",
                            "title": "OCR scans",
                            "agent": "ocr_agent",
                            "task": "OCR image-based documents.",
                            "success_criteria": "Scanned documents are readable.",
                        },
                        {
                            "id": "step-1.3",
                            "title": "Structure corpus",
                            "agent": "structured_data_agent",
                            "task": "Structure the extracted content for analysis.",
                            "depends_on": ["step-1.1", "step-1.2"],
                            "success_criteria": "Structured extracts are available.",
                        },
                    ],
                },
                {
                    "id": "step-2",
                    "title": "Map evidence",
                    "agent": "claim_evidence_mapping_agent",
                    "task": "Map the findings to report sections.",
                    "depends_on": ["step-1"],
                    "success_criteria": "Evidence is mapped to the report.",
                },
            ],
        }

        plan_data = normalize_plan_data(raw_plan, "Build a fundraising report.")

        execution_steps = plan_data["execution_steps"]
        self.assertEqual([step["id"] for step in execution_steps], ["step-1.1", "step-1.2", "step-1.3", "step-2"])
        self.assertEqual(execution_steps[0]["agent"], "local_drive_agent")
        self.assertEqual(execution_steps[1]["depends_on"], ["step-1.1"])
        self.assertEqual(execution_steps[2]["depends_on"], ["step-1.1", "step-1.2"])
        self.assertEqual(execution_steps[3]["depends_on"], ["step-1.1", "step-1.2", "step-1.3"])

    def test_parallel_substeps_keep_shared_parent_dependencies_when_flattened(self):
        raw_plan = {
            "summary": "Parallel OCR plan",
            "steps": [
                {
                    "id": "step-1",
                    "title": "Ingest documents",
                    "agent": "document_ingestion_agent",
                    "task": "Ingest documents.",
                    "substeps": [
                        {
                            "id": "step-1.1",
                            "title": "OCR invoices",
                            "agent": "ocr_agent",
                            "task": "OCR invoices.",
                            "parallel_group": "group-a",
                        },
                        {
                            "id": "step-1.2",
                            "title": "OCR bank statements",
                            "agent": "ocr_agent",
                            "task": "OCR bank statements.",
                            "parallel_group": "group-a",
                        },
                    ],
                },
                {
                    "id": "step-2",
                    "title": "Summarize evidence",
                    "agent": "structured_data_agent",
                    "task": "Summarize the extracted evidence.",
                    "depends_on": ["step-1"],
                },
            ],
        }

        plan_data = normalize_plan_data(raw_plan, "Build a fundraising report.")

        execution_steps = plan_data["execution_steps"]
        self.assertEqual([step["id"] for step in execution_steps], ["step-1.1", "step-1.2", "step-2"])
        self.assertEqual(execution_steps[0]["depends_on"], [])
        self.assertEqual(execution_steps[1]["depends_on"], [])
        self.assertEqual(execution_steps[2]["depends_on"], ["step-1.1", "step-1.2"])


if __name__ == "__main__":
    unittest.main()
