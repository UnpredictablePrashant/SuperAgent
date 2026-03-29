import os
import unittest
from tempfile import TemporaryDirectory

os.environ.setdefault("OPENAI_API_KEY", "test-openai-key")

from kendr.persistence import (
    get_superrag_session,
    initialize_db,
    insert_superrag_chat_message,
    insert_superrag_ingestion,
    list_superrag_chat_messages,
    list_superrag_ingestions,
    list_superrag_sessions,
    upsert_superrag_session,
)


class SuperragStoreTests(unittest.TestCase):
    def test_superrag_session_roundtrip(self):
        with TemporaryDirectory() as tmp:
            db_path = os.path.join(tmp, "store.sqlite3")
            initialize_db(db_path)

            upsert_superrag_session(
                {
                    "session_id": "s1",
                    "collection_name": "superrag_s1",
                    "owner_key": "webchat:default:u1",
                    "title": "Session One",
                    "status": "ready",
                    "source_summary": {"local": {"files": 2}},
                    "stats": {"documents": 2, "chunks": 5, "indexed": 5},
                    "schema_kb": {"schemas": []},
                    "created_at": "2026-03-26T00:00:00+00:00",
                    "updated_at": "2026-03-26T00:00:00+00:00",
                    "last_used_at": "2026-03-26T00:00:00+00:00",
                },
                db_path=db_path,
            )

            session = get_superrag_session("s1", db_path=db_path)
            self.assertIsNotNone(session)
            self.assertEqual(session["collection_name"], "superrag_s1")
            self.assertEqual(session["stats"].get("indexed"), 5)

            owner_sessions = list_superrag_sessions(limit=10, owner_key="webchat:default:u1", db_path=db_path)
            self.assertEqual(len(owner_sessions), 1)
            self.assertEqual(owner_sessions[0]["session_id"], "s1")

    def test_superrag_ingestion_and_chat_logs(self):
        with TemporaryDirectory() as tmp:
            db_path = os.path.join(tmp, "store.sqlite3")
            initialize_db(db_path)

            insert_superrag_ingestion(
                {
                    "ingestion_id": "ing_1",
                    "session_id": "s1",
                    "run_id": "r1",
                    "source_type": "url",
                    "source_ref": "https://example.com",
                    "item_count": 3,
                    "chunk_count": 9,
                    "status": "ok",
                    "detail": {"pages": 3},
                    "created_at": "2026-03-26T00:00:01+00:00",
                },
                db_path=db_path,
            )
            ingestions = list_superrag_ingestions(session_id="s1", limit=10, db_path=db_path)
            self.assertEqual(len(ingestions), 1)
            self.assertEqual(ingestions[0]["chunk_count"], 9)
            self.assertEqual(ingestions[0]["detail"].get("pages"), 3)

            insert_superrag_chat_message(
                {
                    "message_id": "m1",
                    "session_id": "s1",
                    "run_id": "r1",
                    "role": "user",
                    "content": "What is in my data?",
                    "citations": [],
                    "created_at": "2026-03-26T00:00:02+00:00",
                },
                db_path=db_path,
            )
            insert_superrag_chat_message(
                {
                    "message_id": "m2",
                    "session_id": "s1",
                    "run_id": "r1",
                    "role": "assistant",
                    "content": "You have three web pages indexed.",
                    "citations": [{"source": "https://example.com"}],
                    "created_at": "2026-03-26T00:00:03+00:00",
                },
                db_path=db_path,
            )

            messages = list_superrag_chat_messages("s1", limit=10, db_path=db_path)
            self.assertEqual(len(messages), 2)
            self.assertEqual(messages[0]["role"], "assistant")
            self.assertEqual(messages[0]["citations"][0]["source"], "https://example.com")


if __name__ == "__main__":
    unittest.main()
