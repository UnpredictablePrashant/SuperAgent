from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from kendr.extension_sandbox import prepare_extension_host_launch


class ExtensionSandboxTests(unittest.TestCase):
    def test_python_skill_is_blocked_when_bubblewrap_is_missing(self):
        with tempfile.TemporaryDirectory() as tmp:
            with patch("kendr.extension_sandbox.shutil.which", return_value=""):
                launch = prepare_extension_host_launch(
                    mode="python-skill",
                    payload={"permissions": {}},
                    base_command=["python3", "-m", "kendr.extension_host", "python-skill"],
                    base_env={"PATH": "/usr/bin"},
                    launch_root=tmp,
                )

        self.assertTrue(launch.blocked_error)
        self.assertEqual(launch.sandbox["mode"], "blocked")
        self.assertTrue(launch.sandbox["required"])

    def test_web_search_falls_back_to_process_isolation_when_bubblewrap_is_missing(self):
        with tempfile.TemporaryDirectory() as tmp:
            with patch("kendr.extension_sandbox.shutil.which", return_value=""):
                launch = prepare_extension_host_launch(
                    mode="web-search",
                    payload={"permissions": {"network": {"allow": True, "domains": ["duckduckgo.com"]}}},
                    base_command=["python3", "-m", "kendr.extension_host", "web-search"],
                    base_env={"PATH": "/usr/bin"},
                    launch_root=tmp,
                )

        self.assertFalse(launch.blocked_error)
        self.assertEqual(launch.sandbox["mode"], "process_isolated_only")
        self.assertFalse(launch.sandbox["required"])

    def test_bubblewrap_launch_copies_runtime_bundle_and_applies_net_unshare(self):
        with tempfile.TemporaryDirectory() as tmp:
            with patch("kendr.extension_sandbox.shutil.which", return_value="/usr/bin/bwrap"):
                launch = prepare_extension_host_launch(
                    mode="python-skill",
                    payload={"permissions": {}},
                    base_command=["python3", "-m", "kendr.extension_host", "python-skill"],
                    base_env={"PATH": "/usr/bin", "LANG": "C.UTF-8"},
                    launch_root=tmp,
                )

            bundle_root = Path(tmp) / "app" / "kendr"
            self.assertTrue(bundle_root.exists())
            self.assertTrue((bundle_root / "extension_host.py").exists())

        self.assertFalse(launch.blocked_error)
        self.assertEqual(launch.sandbox["mode"], "bubblewrap")
        self.assertIn("--unshare-net", launch.command)
        self.assertIn("--clearenv", launch.command)
        self.assertIn(str(Path(tmp).resolve()), launch.command)

    def test_desktop_full_access_bypasses_bubblewrap_and_marks_mode(self):
        with tempfile.TemporaryDirectory() as tmp:
            with patch("kendr.extension_sandbox.shutil.which", return_value="/usr/bin/bwrap"):
                launch = prepare_extension_host_launch(
                    mode="desktop-automation",
                    payload={"permissions": {"desktop": {"access_mode": "full_access"}}},
                    base_command=["python3", "-m", "kendr.extension_host", "desktop-automation"],
                    base_env={"PATH": "/usr/bin", "LANG": "C.UTF-8"},
                    launch_root=tmp,
                )

        self.assertFalse(launch.blocked_error)
        self.assertEqual(launch.sandbox["mode"], "full_access")
        self.assertEqual(launch.sandbox["provider"], "desktop_automation_broker")
        self.assertEqual(launch.command, ["python3", "-m", "kendr.extension_host", "desktop-automation"])


if __name__ == "__main__":
    unittest.main()
