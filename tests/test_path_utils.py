from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

from kendr.path_utils import application_root, normalize_host_path_str


class PathUtilsTests(unittest.TestCase):
    def test_normalize_relative_path_uses_base_directory(self):
        result = normalize_host_path_str("logs/kendr", base_dir="/tmp")
        self.assertEqual(result, str(Path("/tmp/logs/kendr").resolve()))

    def test_normalize_windows_drive_path_on_non_windows_hosts(self):
        source = "D:/repo/subdir"
        result = normalize_host_path_str(source)
        if os.name == "nt":
            self.assertTrue(result.lower().endswith("\\repo\\subdir"))
        else:
            self.assertEqual(result, str(Path("/mnt/d/repo/subdir").resolve()))

    def test_application_root_defaults_to_repo_root(self):
        with patch.object(sys, "frozen", False, create=True):
            root = application_root()

        self.assertTrue((root / "pyproject.toml").exists())

    def test_application_root_prefers_bundle_root_when_frozen(self):
        fake_root = Path("/tmp/kendr-bundle").resolve()
        with (
            patch.object(sys, "frozen", True, create=True),
            patch.object(sys, "_MEIPASS", str(fake_root), create=True),
        ):
            self.assertEqual(application_root(), fake_root)


if __name__ == "__main__":
    unittest.main()
