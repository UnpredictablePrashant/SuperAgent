from __future__ import annotations

import os
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

            with patch.dict(os.environ, {"KENDR_PROJECTS_STORE": str(store_path)}, clear=False):
                project = pm.add_project(str(project_root), "demo-app")
                service = pm.start_project_service(
                    project["id"],
                    name="frontend",
                    command="python3 -c \"import time; print('service-ready', flush=True); time.sleep(30)\"",
                    kind="frontend",
                    port=3000,
                )
                try:
                    self.assertEqual(service["name"], "frontend")
                    self.assertTrue(service["running"])
                    self.assertTrue(str(service["log_path"]).startswith(str(project_root / "logs" / "kendr" / "services")))

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
