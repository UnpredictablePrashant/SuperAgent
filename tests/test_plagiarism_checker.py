import os
import unittest

os.environ.setdefault("OPENAI_API_KEY", "test-openai-key")

from tasks.long_document_tasks import _plagiarism_report_markdown
from tasks.plagiarism_checker import build_plagiarism_report


class PlagiarismCheckerTests(unittest.TestCase):
    def test_build_plagiarism_report_flags_near_verbatim_overlap(self):
        report = build_plagiarism_report(
            [
                {
                    "title": "Health Effects",
                    "section_text": (
                        "Bananas contain potassium and dietary fiber that support digestive health "
                        "and help maintain normal muscle and nerve function in adults."
                    ),
                }
            ],
            [
                {
                    "label": "Nutrition source",
                    "url": "https://example.com/nutrition",
                    "text": (
                        "Bananas contain potassium and dietary fiber that support digestive health "
                        "and help maintain normal muscle and nerve function in adults."
                    ),
                }
            ],
        )

        self.assertGreaterEqual(report["overall_score"], 70.0)
        first_match = report["sections"][0]["flagged_passages"][0]
        self.assertEqual(first_match["type"], "near_verbatim")
        self.assertEqual(first_match["source_label"], "Nutrition source")

    def test_build_plagiarism_report_softens_score_when_overlap_is_cited(self):
        uncited = build_plagiarism_report(
            [
                {
                    "title": "Nutrition",
                    "section_text": (
                        "Bananas contain resistant starch and soluble fiber that may support satiety "
                        "and glycemic control in some dietary patterns."
                    ),
                }
            ],
            [
                {
                    "label": "Clinical review",
                    "url": "https://example.com/review",
                    "text": (
                        "Bananas contain resistant starch and soluble fiber that may support satiety "
                        "and glycemic control in some dietary patterns."
                    ),
                }
            ],
        )
        cited = build_plagiarism_report(
            [
                {
                    "title": "Nutrition",
                    "section_text": (
                        "Bananas contain resistant starch and soluble fiber that may support satiety "
                        "and glycemic control in some dietary patterns. [S1]"
                    ),
                }
            ],
            [
                {
                    "label": "Clinical review",
                    "url": "https://example.com/review",
                    "text": (
                        "Bananas contain resistant starch and soluble fiber that may support satiety "
                        "and glycemic control in some dietary patterns."
                    ),
                }
            ],
        )

        cited_match = cited["sections"][0]["flagged_passages"][0]
        self.assertEqual(cited_match["type"], "attributed_overlap")
        self.assertLess(cited["overall_score"], uncited["overall_score"])

    def test_build_plagiarism_report_detects_internal_duplication(self):
        duplicated_passage = (
            "Banana export volatility is shaped by weather shocks, shipping bottlenecks, and fertilizer input costs "
            "that directly affect farmgate margins and downstream retail pricing."
        )
        report = build_plagiarism_report(
            [
                {"title": "Supply", "section_text": duplicated_passage},
                {"title": "Pricing", "section_text": duplicated_passage},
            ],
            [],
        )

        flagged_types = [
            item["type"]
            for section in report["sections"]
            for item in section.get("flagged_passages", [])
        ]
        self.assertIn("internal_duplication", flagged_types)

    def test_build_plagiarism_report_ai_score_rises_for_repetitive_prose(self):
        repetitive = "\n\n".join(
            [
                (
                    "Moreover, the platform provides a consistent structure for teams and the platform provides "
                    "a consistent structure for teams through a predictable workflow and a predictable tone."
                ),
                (
                    "Moreover, the platform provides a consistent structure for teams and the platform provides "
                    "a consistent structure for teams with predictable language and predictable transitions."
                ),
                (
                    "Moreover, the platform provides a consistent structure for teams and the platform provides "
                    "a consistent structure for teams in a standardized process with standardized guidance."
                ),
            ]
        )
        varied = "\n\n".join(
            [
                (
                    "Regional banana markets respond differently to rainfall, shipping access, and retailer concentration, "
                    "so pricing pressure does not move in lockstep from one exporter to another."
                ),
                (
                    "Interviews with growers emphasize fertilizer volatility and crop disease risk, while importers focus "
                    "more on cold-chain reliability, customs delays, and seasonal demand spikes."
                ),
                (
                    "That split matters because the same headline export figure can mask very different operating conditions "
                    "across Ecuador, India, and smaller domestic supply chains."
                ),
            ]
        )

        repetitive_report = build_plagiarism_report([{"title": "Repetitive", "section_text": repetitive}], [])
        varied_report = build_plagiarism_report([{"title": "Varied", "section_text": varied}], [])

        self.assertGreater(repetitive_report["ai_content_score"], varied_report["ai_content_score"] + 10.0)

    def test_plagiarism_report_markdown_lists_matches_and_scores(self):
        report = build_plagiarism_report(
            [
                {
                    "title": "Health Effects",
                    "section_text": (
                        "Bananas contain potassium and dietary fiber that support digestive health "
                        "and help maintain normal muscle and nerve function in adults."
                    ),
                }
            ],
            [
                {
                    "label": "Nutrition source",
                    "url": "https://example.com/nutrition",
                    "text": (
                        "Bananas contain potassium and dietary fiber that support digestive health "
                        "and help maintain normal muscle and nerve function in adults."
                    ),
                }
            ],
        )

        markdown = _plagiarism_report_markdown(report)
        self.assertIn("Overall similarity score", markdown)
        self.assertIn("AI-writing risk score", markdown)
        self.assertIn("Matched passages:", markdown)
        self.assertIn("Recommendation:", markdown)
        self.assertIn("Nutrition source", markdown)


if __name__ == "__main__":
    unittest.main()
