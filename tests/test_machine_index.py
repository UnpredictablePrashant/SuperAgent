import tempfile
import unittest
from pathlib import Path

from kendr.machine_index import machine_sync_details, machine_sync_status, run_file_index_sync, run_machine_sync, run_software_inventory_sync


class MachineIndexTests(unittest.TestCase):
    def test_file_index_sync_tracks_create_modify_delete(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            f1 = root / "alpha.txt"
            f1.write_text("one", encoding="utf-8")

            first = run_file_index_sync(working_directory=tmp, roots=[tmp], max_files=1000)
            self.assertEqual(first["created"], 1)
            self.assertEqual(first["modified"], 0)
            self.assertEqual(first["deleted"], 0)

            f1.write_text("two", encoding="utf-8")
            f2 = root / "beta.txt"
            f2.write_text("new", encoding="utf-8")
            second = run_file_index_sync(working_directory=tmp, roots=[tmp], max_files=1000)
            self.assertGreaterEqual(second["modified"], 1)
            self.assertGreaterEqual(second["created"], 1)

            f2.unlink()
            third = run_file_index_sync(working_directory=tmp, roots=[tmp], max_files=1000)
            self.assertGreaterEqual(third["deleted"], 1)

            status = machine_sync_status(tmp)
            self.assertGreaterEqual(status["indexed_files"], 1)
            self.assertTrue(status["file_index_last_synced"])

    def test_software_inventory_sync_writes_snapshot(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = run_software_inventory_sync(tmp)
            self.assertTrue(result["software_inventory_last_synced"])
            self.assertIn("software", result)
            self.assertIn("git", result["software"])

            status = machine_sync_status(tmp)
            self.assertTrue(status["software_inventory_last_synced"])
            self.assertIn("discovered_apps", status)
            self.assertIsInstance(status["discovered_apps"], list)

    def test_run_machine_sync_returns_combined_status(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "x.txt").write_text("hello", encoding="utf-8")
            result = run_machine_sync(working_directory=tmp, scope="machine", roots=[tmp], max_files=1000)
            self.assertEqual(result["scope"], "machine")
            self.assertIn("status", result)
            self.assertGreaterEqual(int(result["status"].get("indexed_files", 0) or 0), 1)
            self.assertIn("system_info", result["status"])

    def test_machine_sync_details_returns_tree(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            nested = root / "docs"
            nested.mkdir()
            (nested / "guide.txt").write_text("hello", encoding="utf-8")
            run_file_index_sync(working_directory=tmp, roots=[tmp], max_files=1000)

            details = machine_sync_details(tmp, max_files=1000)

        self.assertIn("tree", details)
        self.assertTrue(details["tree"])
        self.assertIn("system_info", details)
        root_node = details["tree"][0]
        self.assertEqual(root_node["type"], "directory")
        self.assertTrue(any(child.get("name") == "docs" for child in root_node.get("children", [])))


if __name__ == "__main__":
    unittest.main()
