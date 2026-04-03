from __future__ import annotations

import os
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch


class TestProjectServices(unittest.TestCase):
    def test_start_stop_and_read_project_service_log(self):
        from kendr import project_manager as pm

        with tempfile.TemporaryDirectory() as tmpdir:
            project_root = Path(tmpdir) / "demo-app"
            project_root.mkdir()
            store_path = Path(tmpdir) / "state" / "projects.json"
            service_script = project_root / "service_probe.py"
            service_script.write_text(
                "import time\nprint('service-ready', flush=True)\ntime.sleep(30)\n",
                encoding="utf-8",
            )

            with patch.dict(os.environ, {"KENDR_PROJECTS_STORE": str(store_path)}, clear=False):
                project = pm.add_project(str(project_root), "demo-app")
                service = pm.start_project_service(
                    project["id"],
                    name="frontend",
                    command=f'"{sys.executable}" "{service_script}"',
                    kind="frontend",
                    port=3000,
                )
                try:
                    self.assertEqual(service["name"], "frontend")
                    self.assertTrue(service["running"])
                    expected_log_root = os.path.normcase(os.path.realpath(str(project_root / "logs" / "kendr" / "services")))
                    actual_log_path = os.path.normcase(os.path.realpath(str(service["log_path"])))
                    self.assertTrue(actual_log_path.startswith(expected_log_root))
                    self.assertTrue(service.get("shell_argv"))

                    time.sleep(0.4)
                    listed = pm.list_project_services(project["id"])
                    self.assertEqual(len(listed), 1)
                    self.assertEqual(listed[0]["kind"], "frontend")

                    log_result = pm.read_project_service_log(project["id"], service["id"])
                    self.assertTrue(log_result["ok"])
                    self.assertIn("service-ready", log_result["content"])
                finally:
                    stopped = pm.stop_project_service(project["id"], service["id"])

                self.assertFalse(stopped["running"])
                self.assertEqual(pm.list_running_project_services(), [])

    def test_run_shell_reports_duration_and_shell_argv(self):
        from kendr import project_manager as pm

        with tempfile.TemporaryDirectory() as tmpdir:
            script_path = Path(tmpdir) / "probe.py"
            script_path.write_text("print('ok')\n", encoding="utf-8")
            result = pm.run_shell(f'"{sys.executable}" "{script_path}"', tmpdir, timeout=10)

        self.assertTrue(result["ok"])
        self.assertEqual(result["stdout"].strip(), "ok")
        self.assertTrue(result["shell_argv"])
        self.assertTrue(result["started_at"])
        self.assertTrue(result["completed_at"])
        self.assertIn("duration_ms", result)
        self.assertIn("duration_label", result)
