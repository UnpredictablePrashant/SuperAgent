import os
import importlib.util
import unittest


os.environ.setdefault("OPENAI_API_KEY", "test-openai-key")


class ImportSmokeTests(unittest.TestCase):
    def test_import_runtime_entrypoints(self):
        import app  # noqa: F401
        import gateway_server  # noqa: F401
        import setup_ui  # noqa: F401
        import plugin_templates.project_stacks  # noqa: F401
        import kendr.domain.local_drive  # noqa: F401
        import kendr.setup.catalog  # noqa: F401

    def test_legacy_persistence_imports_remain_compatible(self):
        import kendr.persistence as persistence
        import tasks.sqlite_store as legacy_store

        self.assertIs(legacy_store.initialize_db, persistence.initialize_db)
        self.assertIs(legacy_store.list_recent_runs, persistence.list_recent_runs)

    @unittest.skipUnless(importlib.util.find_spec("fastmcp") is not None, "fastmcp is not installed in the active interpreter")
    def test_import_mcp_servers(self):
        import mcp_servers.cve_server  # noqa: F401
        import mcp_servers.http_fuzzing_server  # noqa: F401
        import mcp_servers.nmap_server  # noqa: F401
        import mcp_servers.research_server  # noqa: F401
        import mcp_servers.screenshot_server  # noqa: F401
        import mcp_servers.vector_server  # noqa: F401
        import mcp_servers.zap_server  # noqa: F401


if __name__ == "__main__":
    unittest.main()
