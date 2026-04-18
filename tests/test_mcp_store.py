import unittest

from kendr.persistence.mcp_store import (
    _DEFAULT_MCP_SERVERS,
    _migrated_flag_path,
    _parse_registry_payload,
    _registry_payload_from_rows,
    _unwrap_fastmcp_connection,
)


class MCPStoreTests(unittest.TestCase):
    def test_migrated_flag_path_is_db_specific(self):
        a = _migrated_flag_path("/tmp/a.sqlite3")
        b = _migrated_flag_path("/tmp/b.sqlite3")
        self.assertNotEqual(a, b)
        self.assertIn("mcp_migrated_", a)
        self.assertTrue(a.endswith(".flag"))

    def test_parse_registry_payload_supports_cursor_style_stdio(self):
        entries = _parse_registry_payload({
            "mcpServers": {
                "aws-knowledge-mcp-server": {
                    "command": "uvx",
                    "args": ["fastmcp", "run", "https://knowledge-mcp.global.api.aws"],
                }
            }
        })

        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0]["name"], "aws-knowledge-mcp-server")
        self.assertEqual(entries[0]["type"], "http")
        self.assertEqual(entries[0]["connection"], "https://knowledge-mcp.global.api.aws")

    def test_unwrap_fastmcp_connection_promotes_wrapper_to_http(self):
        self.assertEqual(
            _unwrap_fastmcp_connection("uvx fastmcp run https://knowledge-mcp.global.api.aws"),
            ("http", "https://knowledge-mcp.global.api.aws"),
        )

    def test_registry_payload_from_rows_exports_unified_mcpservers_shape(self):
        payload = _registry_payload_from_rows([{
            "id": "srv1",
            "name": "aws-knowledge-mcp-server",
            "type": "http",
            "connection": "https://knowledge-mcp.global.api.aws",
            "description": "",
            "auth_token": "",
            "enabled": True,
        }])

        self.assertIn("mcpServers", payload)
        self.assertEqual(
            payload["mcpServers"]["aws-knowledge-mcp-server"]["url"],
            "https://knowledge-mcp.global.api.aws",
        )
        self.assertEqual(payload["mcpServers"]["aws-knowledge-mcp-server"]["disabled"], False)

    def test_default_servers_do_not_include_browser_use(self):
        ids = {item["id"] for item in _DEFAULT_MCP_SERVERS}
        self.assertNotIn("browser-use-mcp", ids)
        self.assertIn("scpr-web-scraper", ids)


if __name__ == "__main__":
    unittest.main()
