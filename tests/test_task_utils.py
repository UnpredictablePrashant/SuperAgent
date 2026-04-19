import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch


class TaskUtilsTests(unittest.TestCase):
    def test_client_for_model_infers_provider_from_model_family(self):
        from tasks import utils

        utils._LLM_CLIENTS.clear()
        fake_client = object()

        with (
            patch("kendr.llm_router.get_active_provider", return_value="openai"),
            patch("kendr.llm_router.build_llm", return_value=fake_client) as mock_build_llm,
        ):
            client = utils._client_for_model("claude-sonnet-4-6")

        self.assertIs(client, fake_client)
        self.assertEqual(mock_build_llm.call_args.kwargs["provider"], "anthropic")
        self.assertEqual(mock_build_llm.call_args.kwargs["model"], "claude-sonnet-4-6")

    def test_client_for_model_keeps_explicit_runtime_provider_override(self):
        from tasks import utils

        utils._LLM_CLIENTS.clear()
        fake_client = object()

        with (
            utils.runtime_model_override("openai", ""),
            patch("kendr.llm_router.get_active_provider", return_value="anthropic"),
            patch("kendr.llm_router.build_llm", return_value=fake_client) as mock_build_llm,
        ):
            client = utils._client_for_model("gpt-5.1")

        self.assertIs(client, fake_client)
        self.assertEqual(mock_build_llm.call_args.kwargs["provider"], "openai")
        self.assertEqual(mock_build_llm.call_args.kwargs["model"], "gpt-5.1")

    def test_set_active_output_dir_isolated_per_thread_for_logs_and_writes(self):
        from tasks import utils

        with tempfile.TemporaryDirectory() as tmpdir:
            left_dir = Path(tmpdir) / "left"
            right_dir = Path(tmpdir) / "right"
            left_dir.mkdir(parents=True, exist_ok=True)
            right_dir.mkdir(parents=True, exist_ok=True)

            def _worker(target_dir: Path, tag: str) -> None:
                utils.set_active_output_dir(str(target_dir), append=False)
                utils.log_task_update("Thread Test", f"{tag} log entry")
                utils.write_text_file("payload.txt", f"{tag} payload")

            left_thread = threading.Thread(target=_worker, args=(left_dir, "left"))
            right_thread = threading.Thread(target=_worker, args=(right_dir, "right"))
            left_thread.start()
            right_thread.start()
            left_thread.join()
            right_thread.join()
            utils.set_active_output_dir("output")

            left_log = (left_dir / "execution.log").read_text(encoding="utf-8")
            right_log = (right_dir / "execution.log").read_text(encoding="utf-8")
            self.assertIn("left log entry", left_log)
            self.assertNotIn("right log entry", left_log)
            self.assertIn("right log entry", right_log)
            self.assertNotIn("left log entry", right_log)
            self.assertEqual((left_dir / "payload.txt").read_text(encoding="utf-8"), "left payload")
            self.assertEqual((right_dir / "payload.txt").read_text(encoding="utf-8"), "right payload")


if __name__ == "__main__":
    unittest.main()
