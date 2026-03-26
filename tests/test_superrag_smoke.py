import os
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch


os.environ.setdefault("OPENAI_API_KEY", "test-openai-key")

import tasks.superrag_tasks as superrag_tasks


class SuperragSmokeTests(unittest.TestCase):
    def test_superrag_build_mode_completes_with_stubbed_ingestion(self):
        session_store: dict[str, dict] = {}

        def _upsert_session(session: dict) -> None:
            session_store[str(session["session_id"])] = dict(session)

        def _get_session(session_id: str) -> dict | None:
            return session_store.get(session_id)

        def _chunk_text(text: str, chunk_size: int = 1000, overlap: int = 120):  # noqa: ARG001
            return [text] if text else []

        with TemporaryDirectory() as tmp:
            doc_path = Path(tmp) / "product_notes.txt"
            state = {
                "user_query": "Create a reusable product operations knowledge session.",
                "working_directory": tmp,
                "run_output_dir": tmp,
                "superrag_mode": "build",
                "superrag_session_id": "product_ops_kb",
                "superrag_local_paths": [tmp],
                "superrag_include_working_directory": False,
            }

            with (
                patch("tasks.superrag_tasks.begin_agent_session", return_value=(None, state["user_query"], "orchestrator_agent")),
                patch("tasks.superrag_tasks.publish_agent_output", side_effect=lambda current_state, *_args, **_kwargs: current_state),
                patch("tasks.superrag_tasks.log_task_update"),
                patch("tasks.superrag_tasks.write_text_file"),
                patch("tasks.superrag_tasks._discover_local_files", return_value=([str(doc_path)], 1024)),
                patch(
                    "tasks.superrag_tasks._ingest_local_documents",
                    return_value=(
                        [
                            {
                                "source": str(doc_path),
                                "source_type": "local_file",
                                "text": "Revenue grew 40% year-over-year and customer churn fell.",
                                "metadata": {"source_type": "local_file"},
                            }
                        ],
                        {"roots": [tmp], "files": 1, "total_size_bytes": 1024},
                    ),
                ),
                patch(
                    "tasks.superrag_tasks._documents_to_records",
                    return_value=(
                        [
                            {
                                "id": "sr_record_1",
                                "source": str(doc_path),
                                "text": "Revenue grew 40% year-over-year and customer churn fell.",
                                "payload": {"source": str(doc_path), "source_type": "local_file"},
                            }
                        ],
                        1,
                    ),
                ),
                patch("tasks.superrag_tasks.upsert_memory_records", return_value={"indexed": 1}),
                patch("tasks.superrag_tasks.upsert_superrag_session", side_effect=_upsert_session),
                patch("tasks.superrag_tasks.get_superrag_session", side_effect=_get_session),
                patch("tasks.superrag_tasks._ingestion_event"),
                patch("tasks.superrag_tasks.chunk_text", side_effect=_chunk_text),
            ):
                result = superrag_tasks.superrag_agent(state)

        self.assertEqual(result["superrag_mode"], "build")
        self.assertEqual(result["superrag_status"], "ready")
        self.assertEqual(result["superrag_session_id"], "product_ops_kb")
        self.assertEqual(result["superrag_build_report"]["stats"]["indexed"], 1)
        self.assertIn("superRAG build completed", result["draft_response"])
        self.assertIn("Chunks indexed: 1", result["draft_response"])


if __name__ == "__main__":
    unittest.main()
