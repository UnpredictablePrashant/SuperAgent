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
        self.assertIn("superRAG Build Summary", result["draft_response"])
        self.assertIn("superRAG build completed", result["draft_response"])
        self.assertIn("Coverage:", result["draft_response"])
        self.assertIn("Chunks indexed: 1", result["draft_response"])
        self.assertIn("local: 1 file(s)", result["draft_response"])
        self.assertIn("Recommended Next Steps:", result["draft_response"])
        self.assertIn(str(doc_path), result["draft_response"])
        self.assertIn("- local: 1 file(s)", "\n".join(result["superrag_build_report"]["source_mix_summary"]))

    def test_superrag_chat_mode_appends_sources_section_and_exposes_source_summary(self):
        session = {
            "session_id": "product_ops_kb",
            "collection_name": "superrag_product_ops_kb",
            "owner_key": "webchat:default:local_user",
            "title": "Product Ops KB",
            "status": "ready",
            "source_summary": {
                "local": {"files": 2, "roots": ["/tmp/a", "/tmp/b"]},
                "urls": {"pages_with_text": 1, "requested_urls": 1},
            },
            "stats": {"documents": 3, "chunks": 4, "indexed": 4},
            "schema_kb": {},
            "created_at": "2026-04-16T00:00:00+00:00",
            "updated_at": "2026-04-16T00:00:00+00:00",
            "last_used_at": "2026-04-16T00:00:00+00:00",
        }

        state = {
            "user_query": "What changed in operations?",
            "superrag_mode": "chat",
            "superrag_session_id": "product_ops_kb",
        }

        hits = [
            {
                "source": "file:///tmp/product_notes.txt",
                "text": "Revenue grew 40% year-over-year.",
                "score": 0.91,
                "metadata": {"source_type": "local_file"},
            },
            {
                "source": "https://example.com/ops-brief",
                "text": "Churn fell and onboarding improved.",
                "score": 0.88,
                "metadata": {"source_type": "url"},
            },
        ]

        with (
            patch("tasks.superrag_tasks.begin_agent_session", return_value=(None, state["user_query"], "orchestrator_agent")),
            patch("tasks.superrag_tasks.publish_agent_output", side_effect=lambda current_state, *_args, **_kwargs: current_state),
            patch("tasks.superrag_tasks.log_task_update"),
            patch("tasks.superrag_tasks.write_text_file"),
            patch("tasks.superrag_tasks.get_superrag_session", return_value=session),
            patch("tasks.superrag_tasks.search_memory", return_value=hits),
            patch("tasks.superrag_tasks.llm_text", return_value="Operations improved across revenue and churn metrics."),
            patch("tasks.superrag_tasks.insert_superrag_chat_message") as insert_chat_message,
            patch("tasks.superrag_tasks.upsert_superrag_session"),
        ):
            result = superrag_tasks.superrag_agent(state)

        self.assertEqual(result["superrag_mode"], "chat")
        self.assertIn("Sources:", result["draft_response"])
        self.assertIn("file:///tmp/product_notes.txt", result["draft_response"])
        self.assertIn("https://example.com/ops-brief", result["draft_response"])
        self.assertEqual(result["superrag_chat_result"]["raw_hit_count"], 2)
        self.assertEqual(result["superrag_chat_result"]["hit_count"], 2)
        self.assertEqual(result["superrag_chat_result"]["source_summary"], session["source_summary"])
        self.assertIn("local: 2 file(s)", "\n".join(result["superrag_chat_result"]["source_mix_summary"]))
        self.assertEqual(result["superrag_chat_result"]["retrieval_summary"]["distinct_source_count"], 2)
        persisted_assistant_message = insert_chat_message.call_args_list[1].args[0]
        self.assertIn("Sources:", persisted_assistant_message["content"])
        self.assertIn("file:///tmp/product_notes.txt", persisted_assistant_message["content"])

    def test_superrag_end_to_end_build_then_chat_diversifies_sources(self):
        session_store: dict[str, dict] = {}
        memory_store: dict[str, list[dict]] = {}

        def _upsert_session(session: dict) -> None:
            session_store[str(session["session_id"])] = dict(session)

        def _get_session(session_id: str) -> dict | None:
            return session_store.get(session_id)

        def _chunk_text(text: str, chunk_size: int = 1000, overlap: int = 120):  # noqa: ARG001
            return [text] if text else []

        def _upsert_memory(records: list[dict], collection_name: str):
            memory_store[collection_name] = [dict(record) for record in records]
            return {"indexed": len(records)}

        def _search_memory(query: str, top_k: int = 5, collection_name: str = ""):  # noqa: ARG001
            records = memory_store.get(collection_name, [])
            hits = []
            scores = [0.98, 0.97, 0.96]
            for index, record in enumerate(records[:3]):
                hits.append(
                    {
                        "source": record["source"],
                        "text": record["text"],
                        "score": scores[index],
                        "metadata": dict(record.get("payload", {})),
                    }
                )
            return hits[:top_k]

        with TemporaryDirectory() as tmp:
            doc_path = Path(tmp) / "product_notes.txt"
            benchmark_url = "https://example.com/benchmark"
            build_state = {
                "user_query": "Create a reusable product operations knowledge session.",
                "working_directory": tmp,
                "run_output_dir": tmp,
                "superrag_mode": "build",
                "superrag_session_id": "product_ops_kb",
                "superrag_local_paths": [tmp],
                "superrag_urls": [benchmark_url],
                "superrag_include_working_directory": False,
            }
            chat_state = {
                "user_query": "What changed in operations and churn?",
                "working_directory": tmp,
                "run_output_dir": tmp,
                "superrag_mode": "chat",
                "superrag_session_id": "product_ops_kb",
                "superrag_top_k": 2,
            }

            local_doc = {
                "source": str(doc_path),
                "source_type": "local_file",
                "text": "Revenue grew 40% year-over-year and customer churn fell.",
                "metadata": {"source_type": "local_file"},
            }
            url_doc = {
                "source": benchmark_url,
                "source_type": "url",
                "text": "External benchmark confirms improved onboarding and reduced churn.",
                "metadata": {"source_type": "url"},
            }
            records = [
                {
                    "id": "sr_record_1",
                    "source": str(doc_path),
                    "text": "Revenue grew 40% year-over-year and customer churn fell.",
                    "payload": {"source": str(doc_path), "source_type": "local_file", "chunk_index": 0},
                },
                {
                    "id": "sr_record_2",
                    "source": str(doc_path),
                    "text": "Onboarding improved and support escalations declined.",
                    "payload": {"source": str(doc_path), "source_type": "local_file", "chunk_index": 1},
                },
                {
                    "id": "sr_record_3",
                    "source": benchmark_url,
                    "text": "Independent benchmark also shows churn reduction.",
                    "payload": {"source": benchmark_url, "source_type": "url", "chunk_index": 0},
                },
            ]

            with (
                patch(
                    "tasks.superrag_tasks.begin_agent_session",
                    side_effect=[
                        (None, build_state["user_query"], "orchestrator_agent"),
                        (None, chat_state["user_query"], "orchestrator_agent"),
                    ],
                ),
                patch("tasks.superrag_tasks.publish_agent_output", side_effect=lambda current_state, *_args, **_kwargs: current_state),
                patch("tasks.superrag_tasks.log_task_update"),
                patch("tasks.superrag_tasks.write_text_file"),
                patch("tasks.superrag_tasks._discover_local_files", return_value=([str(doc_path)], 1024)),
                patch("tasks.superrag_tasks._ingest_local_documents", return_value=([local_doc], {"roots": [tmp], "files": 1, "total_size_bytes": 1024})),
                patch(
                    "tasks.superrag_tasks._ingest_url_documents",
                    return_value=([url_doc], {"requested_urls": 1, "pages_fetched": 1, "pages_with_text": 1, "max_pages": 20}),
                ),
                patch("tasks.superrag_tasks._documents_to_records", return_value=(records, 3)),
                patch("tasks.superrag_tasks.upsert_memory_records", side_effect=_upsert_memory),
                patch("tasks.superrag_tasks.search_memory", side_effect=_search_memory),
                patch("tasks.superrag_tasks.upsert_superrag_session", side_effect=_upsert_session),
                patch("tasks.superrag_tasks.get_superrag_session", side_effect=_get_session),
                patch("tasks.superrag_tasks._ingestion_event"),
                patch("tasks.superrag_tasks.chunk_text", side_effect=_chunk_text),
                patch("tasks.superrag_tasks.llm_text", return_value="Operations improved across churn and onboarding metrics."),
                patch("tasks.superrag_tasks.insert_superrag_chat_message") as insert_chat_message,
            ):
                built = superrag_tasks.superrag_agent(build_state)
                result = superrag_tasks.superrag_agent(chat_state)

        self.assertEqual(built["superrag_mode"], "build")
        self.assertEqual(result["superrag_mode"], "chat")
        self.assertIn("superrag_product_ops_kb", memory_store)
        self.assertEqual(result["superrag_chat_result"]["raw_hit_count"], 3)
        self.assertEqual(result["superrag_chat_result"]["hit_count"], 2)
        self.assertEqual(result["superrag_chat_result"]["retrieval_summary"]["distinct_source_count"], 2)
        self.assertEqual(
            [item["source"] for item in result["superrag_chat_result"]["citations"]],
            [str(doc_path), benchmark_url],
        )
        self.assertIn(str(doc_path), result["draft_response"])
        self.assertIn(benchmark_url, result["draft_response"])
        persisted_assistant_message = insert_chat_message.call_args_list[1].args[0]
        self.assertIn("Sources:", persisted_assistant_message["content"])
        self.assertIn(benchmark_url, persisted_assistant_message["content"])


if __name__ == "__main__":
    unittest.main()
