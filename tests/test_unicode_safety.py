from __future__ import annotations

import io
import json
import tempfile
import unittest


class TestUnicodeSafety(unittest.TestCase):
    def test_run_store_sanitizes_surrogates_for_sqlite_writes(self):
        from kendr.persistence.run_store import get_channel_session, get_run, insert_run, upsert_channel_session

        bad_text = "bad \ud83c text"

        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = f"{tmpdir}/agent_workflow.sqlite3"
            insert_run(
                "run-utf8",
                bad_text,
                "2026-04-17T00:00:00+00:00",
                "running",
                db_path=db_path,
            )
            upsert_channel_session(
                "session-utf8",
                {
                    "channel": "webchat",
                    "chat_id": "chat-1",
                    "sender_id": "user-1",
                    "workspace_id": "default",
                    "updated_at": "2026-04-17T00:00:00+00:00",
                    "state": {"last_text": bad_text},
                },
                db_path=db_path,
            )

            run_row = get_run("run-utf8", db_path=db_path)
            session_row = get_channel_session("session-utf8", db_path=db_path)

        self.assertIsNotNone(run_row)
        self.assertIsNotNone(session_row)
        self.assertEqual(run_row["user_query"], "bad \uFFFD text")
        self.assertEqual(session_row["state"]["last_text"], "bad \uFFFD text")

    def test_ui_json_response_sanitizes_surrogates(self):
        import kendr.ui_server as ui_server

        handler = object.__new__(ui_server.KendrUIHandler)
        handler.path = "/api/health"
        handler.send_response = lambda code: None
        handler.send_header = lambda *args, **kwargs: None
        handler.end_headers = lambda: None
        handler.wfile = io.BytesIO()

        handler._json(200, {"error": "bad \ud83c text"})

        payload = json.loads(handler.wfile.getvalue().decode("utf-8"))
        self.assertEqual(payload["error"], "bad \uFFFD text")

    def test_ui_sse_sanitizes_surrogates(self):
        import kendr.ui_server as ui_server

        handler = object.__new__(ui_server.KendrUIHandler)
        handler.send_response = lambda code: None
        handler.send_header = lambda *args, **kwargs: None
        handler.end_headers = lambda: None

        class _Writer:
            def __init__(self):
                self.parts: list[str] = []

            def write(self, data):
                self.parts.append(data.decode("utf-8"))

            def flush(self):
                pass

        writer = _Writer()
        handler.wfile = writer

        pending = {
            "run_id": "run-utf8",
            "status": "completed",
            "result": {
                "run_id": "run-utf8",
                "status": "completed",
                "final_output": "bad \ud83c text",
            },
        }

        from unittest.mock import patch

        with patch.dict("kendr.ui_server._run_event_queues", {}, clear=True), patch.dict("kendr.ui_server._pending_runs", {"run-utf8": pending}, clear=True):
            handler._handle_sse("run-utf8")

        stream = "".join(writer.parts)
        self.assertIn("bad \uFFFD text", stream)
        self.assertNotIn("\\ud83c", stream)

    def test_gateway_json_response_sanitizes_surrogates(self):
        import kendr.gateway_server as gateway

        handler = object.__new__(gateway.GatewayHandler)
        handler.send_response = lambda code: None
        handler.send_header = lambda *args, **kwargs: None
        handler.end_headers = lambda: None
        handler.wfile = io.BytesIO()

        handler._send_json(200, {"error": "bad \ud83c text"})

        payload = json.loads(handler.wfile.getvalue().decode("utf-8"))
        self.assertEqual(payload["error"], "bad \uFFFD text")
