import os
import tempfile
import unittest
from pathlib import Path

from tasks.privileged_control import (
    build_privileged_policy,
    ensure_command_allowed,
    path_allowed,
)


class PrivilegedControlTests(unittest.TestCase):
    def test_path_allowed(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            child = root / "a" / "b"
            child.mkdir(parents=True, exist_ok=True)
            self.assertTrue(path_allowed(str(child), [str(root)]))
            self.assertFalse(path_allowed("/tmp", [str(root)]))

    def test_command_blocked_without_approval(self):
        with tempfile.TemporaryDirectory() as tmp:
            state = {
                "working_directory": tmp,
                "privileged_mode": True,
                "privileged_require_approvals": True,
                "privileged_approved": False,
                "privileged_approval_note": "",
                "privileged_allowed_paths": [tmp],
            }
            policy = build_privileged_policy(state)
            with self.assertRaises(PermissionError):
                ensure_command_allowed("mkdir test-folder", tmp, policy)

    def test_read_only_blocks_mutation(self):
        with tempfile.TemporaryDirectory() as tmp:
            state = {
                "working_directory": tmp,
                "privileged_mode": True,
                "privileged_require_approvals": True,
                "privileged_approved": True,
                "privileged_approval_note": "Ticket OPS-123",
                "privileged_read_only": True,
                "privileged_allowed_paths": [tmp],
            }
            policy = build_privileged_policy(state)
            with self.assertRaises(PermissionError):
                ensure_command_allowed("rm -rf build", tmp, policy)

    def test_allows_safe_command_with_approval(self):
        with tempfile.TemporaryDirectory() as tmp:
            state = {
                "working_directory": tmp,
                "privileged_mode": True,
                "privileged_require_approvals": True,
                "privileged_approved": True,
                "privileged_approval_note": "Ticket OPS-789",
                "privileged_allowed_paths": [tmp],
            }
            policy = build_privileged_policy(state)
            ensure_command_allowed("ls -la", tmp, policy)


if __name__ == "__main__":
    unittest.main()
