import json
import os
import unittest
from urllib.parse import parse_qs, urlparse
from unittest import mock

os.environ.setdefault("OPENAI_API_KEY", "test-openai-key")

from tasks.search_tasks import google_search_agent


class _FakeHTTPResponse:
    def __init__(self, payload: dict):
        self._payload = payload

    def read(self) -> bytes:
        return json.dumps(self._payload).encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


class GoogleSearchAgentTests(unittest.TestCase):
    def setUp(self) -> None:
        os.environ["SERP_API_KEY"] = "test-serp-key"

    def test_google_search_agent_prefers_task_objective_over_stale_search_query(self):
        calls: list[str] = []

        def _fake_urlopen(url: str, timeout: int = 30):
            calls.append(url)
            payload = {
                "search_metadata": {"status": "Success"},
                "search_parameters": {"engine": "google"},
                "organic_results": [
                    {
                        "title": "Twenty4 Jewelry",
                        "link": "https://twenty4.in/home",
                        "snippet": "Official website",
                    }
                ],
            }
            return _FakeHTTPResponse(payload)

        state = {
            "user_query": "Find official website for Twenty4 Jewelry.",
            "search_query": "stale query that should not be used",
            "a2a": {"messages": [], "tasks": [], "artifacts": [], "agent_cards": []},
        }

        with mock.patch("tasks.search_tasks.urlopen", side_effect=_fake_urlopen):
            updated = google_search_agent(state)

        self.assertTrue(calls)
        query = parse_qs(urlparse(calls[0]).query).get("q", [""])[0]
        self.assertEqual(query, "Find official website for Twenty4 Jewelry.")
        self.assertEqual(updated.get("search_query"), "Find official website for Twenty4 Jewelry.")

    def test_google_search_agent_writes_domain_assessment_and_crawl_targets(self):
        def _fake_urlopen(url: str, timeout: int = 30):
            payload = {
                "search_metadata": {"status": "Success"},
                "search_parameters": {"engine": "google"},
                "organic_results": [
                    {
                        "title": "Twenty4 Jewelry Official Store",
                        "link": "https://twenty4.in/home",
                        "snippet": "Shop the latest collections.",
                    },
                    {
                        "title": "Twenty4 on Instagram",
                        "link": "https://www.instagram.com/twenty4jewelry/",
                        "snippet": "Brand social profile",
                    },
                ],
            }
            return _FakeHTTPResponse(payload)

        state = {
            "user_query": "Analyze Twenty4 public presence from https://twenty4.in/home",
            "a2a": {"messages": [], "tasks": [], "artifacts": [], "agent_cards": []},
        }

        with mock.patch("tasks.search_tasks.urlopen", side_effect=_fake_urlopen):
            updated = google_search_agent(state)

        summary = str(updated.get("search_summary") or "")
        self.assertIn("Official Domain Assessment:", summary)
        self.assertIn("Relevant Public URLs (for crawl/validation):", summary)
        self.assertIn("Recommended Crawl URL Patterns:", summary)
        self.assertEqual(updated.get("official_domain_candidate"), "twenty4.in")
        self.assertTrue(updated.get("search_relevant_urls"))
        self.assertTrue(updated.get("crawl_seed_urls"))


if __name__ == "__main__":
    unittest.main()
