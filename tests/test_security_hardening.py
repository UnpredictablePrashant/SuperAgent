from __future__ import annotations

import os
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from kendr import extension_sandbox
from kendr.persistence.approval_store import (
    consume_approval_grant,
    create_approval_grant,
    find_matching_approval_grant,
)
from kendr.persistence.mcp_store import add_mcp_server, get_mcp_server, _registry_payload_from_rows
from kendr.persistence.setup_store import (
    get_setup_config_value,
    get_setup_provider_tokens,
    list_setup_config_values,
    list_setup_provider_tokens,
    set_setup_provider_tokens,
    upsert_setup_config_value,
)
from kendr.skill_manager import _run_python_skill, execute_skill_by_slug, get_marketplace, grant_skill_approval, resolve_runtime_skill, test_skill


def _process_only_sandbox_launch(*, base_command, base_env, **_kwargs):
    return extension_sandbox.SandboxLaunch(
        command=list(base_command),
        env=dict(base_env),
        sandbox={
            "mode": "process_isolated_only",
            "provider": "test",
            "required": False,
            "available": False,
            "reason": "Unit test bypass",
        },
    )


class SecretStorageTests(unittest.TestCase):
    def test_setup_secret_values_are_stored_as_vault_refs(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = str(Path(tmp) / "agent_workflow.sqlite3")
            with patch.dict(os.environ, {"KENDR_HOME": tmp}, clear=False):
                upsert_setup_config_value(
                    "openai",
                    "OPENAI_API_KEY",
                    "sk-secret-value",
                    is_secret=True,
                    db_path=db_path,
                )

                with sqlite3.connect(db_path) as conn:
                    raw_value = conn.execute(
                        "SELECT config_value FROM setup_config_values WHERE component_id=? AND config_key=?",
                        ("openai", "OPENAI_API_KEY"),
                    ).fetchone()[0]

                self.assertTrue(str(raw_value).startswith("vault://"))
                self.assertNotIn("sk-secret-value", str(raw_value))

                row = get_setup_config_value("openai", "OPENAI_API_KEY", db_path=db_path)
                self.assertEqual(row["config_value"], "sk-secret-value")

                masked = list_setup_config_values(include_secrets=False, db_path=db_path)
                self.assertEqual(masked[0]["config_value"], "********")

    def test_provider_tokens_are_moved_out_of_general_sqlite_payloads(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = str(Path(tmp) / "agent_workflow.sqlite3")
            with patch.dict(os.environ, {"KENDR_HOME": tmp}, clear=False):
                set_setup_provider_tokens(
                    "google",
                    {"access_token": "tok-123", "refresh_token": "ref-456"},
                    updated_at="123",
                    db_path=db_path,
                )

                with sqlite3.connect(db_path) as conn:
                    raw_value = conn.execute(
                        "SELECT token_json FROM setup_provider_tokens WHERE provider=?",
                        ("google",),
                    ).fetchone()[0]

                self.assertIn("secret_ref", str(raw_value))
                self.assertNotIn("tok-123", str(raw_value))

                payload = get_setup_provider_tokens("google", db_path=db_path)
                self.assertEqual(payload["access_token"], "tok-123")

                listed = list_setup_provider_tokens(include_secrets=False, db_path=db_path)
                self.assertEqual(listed["google"]["token_payload"]["access_token"], "********")

    def test_mcp_auth_token_is_resolved_but_not_exported(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = str(Path(tmp) / "agent_workflow.sqlite3")
            with patch.dict(os.environ, {"KENDR_HOME": tmp}, clear=False):
                add_mcp_server(
                    "srv1",
                    "Secure MCP",
                    "https://example.test/mcp",
                    auth_token="super-secret-token",
                    db_path=db_path,
                )
                server = get_mcp_server("srv1", db_path=db_path)

                self.assertEqual(server["auth_token"], "super-secret-token")
                payload = _registry_payload_from_rows([server])
                self.assertNotIn("auth_token", payload["mcpServers"]["Secure MCP"])


class ApprovalGrantStoreTests(unittest.TestCase):
    def test_session_grant_matches_and_once_grant_is_consumed(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = str(Path(tmp) / "agent_workflow.sqlite3")
            once = create_approval_grant(
                subject_type="skill",
                subject_id="skill:demo",
                manifest_hash="hash-1",
                scope="once",
                actor="user",
                note="Allow once",
                db_path=db_path,
            )
            session = create_approval_grant(
                subject_type="skill",
                subject_id="skill:demo",
                manifest_hash="hash-2",
                scope="session",
                actor="user",
                note="Allow session",
                session_id="sess-1",
                db_path=db_path,
            )

            matched_once = find_matching_approval_grant(
                subject_type="skill",
                subject_id="skill:demo",
                manifest_hash="hash-1",
                db_path=db_path,
            )
            consumed_once = consume_approval_grant(once["grant_id"], db_path=db_path)
            matched_session = find_matching_approval_grant(
                subject_type="skill",
                subject_id="skill:demo",
                manifest_hash="hash-2",
                session_id="sess-1",
                db_path=db_path,
            )

        self.assertEqual(matched_once["grant_id"], once["grant_id"])
        self.assertEqual(consumed_once["status"], "used")
        self.assertEqual(matched_session["grant_id"], session["grant_id"])


class ExtensionHostIsolationTests(unittest.TestCase):
    def setUp(self):
        patcher = patch(
            "kendr.skill_manager.extension_sandbox.prepare_extension_host_launch",
            side_effect=_process_only_sandbox_launch,
        )
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_python_skills_run_out_of_process(self):
        os.environ.pop("KENDR_CHILD_ONLY", None)
        result = _run_python_skill(
            'os.environ["KENDR_CHILD_ONLY"]="1"\noutput = os.getenv("KENDR_CHILD_ONLY")',
            {},
        )

        self.assertTrue(result["success"], result.get("error"))
        self.assertEqual(result["output"], "1")
        self.assertNotIn("KENDR_CHILD_ONLY", os.environ)

    def test_python_skill_defaults_to_isolated_workspace(self):
        result = _run_python_skill(
            'output = os.getcwd()',
            {},
            permission_manifest={},
            approval={"approved": True, "note": "Run in isolated workspace"},
        )

        self.assertTrue(result["success"], result.get("error"))
        self.assertIsInstance(result["output"], str)
        self.assertIn("kendr-extension-", str(result["output"]))
        self.assertNotEqual(str(result["output"]), os.getcwd())

    def test_python_skill_only_exposes_explicit_environment_keys(self):
        with patch.dict(os.environ, {"KENDR_ALLOWED_ENV": "visible-value"}, clear=False):
            result = _run_python_skill(
                'output = {"allowed": os.getenv("KENDR_ALLOWED_ENV"), "path": os.getenv("PATH")}',
                {},
                permission_manifest={"environment": {"read": ["KENDR_ALLOWED_ENV"]}},
                approval={"approved": True, "note": "Allow named env key"},
            )

        self.assertTrue(result["success"], result.get("error"))
        self.assertEqual(result["output"]["allowed"], "visible-value")
        self.assertIsNone(result["output"]["path"])

    def test_custom_python_skill_requires_explicit_approval(self):
        skill_row = {
            "skill_id": "skill-1",
            "slug": "custom-python",
            "skill_type": "python",
            "catalog_id": "",
            "code": "output = 123",
            "metadata": {},
            "is_installed": True,
        }
        with patch("kendr.skill_manager.get_user_skill", return_value=skill_row):
            result = test_skill("skill-1", {})

        self.assertFalse(result["success"])
        self.assertIn("requires explicit approval", str(result["error"]))

    def test_shell_command_blocks_requested_cwd_outside_manifest_scope(self):
        with tempfile.TemporaryDirectory() as allowed_root, tempfile.TemporaryDirectory() as blocked_root:
            skill_row = {
                "skill_id": "skill-shell-cwd",
                "slug": "shell-command",
                "skill_type": "catalog",
                "catalog_id": "shell-command",
                "code": "",
                "metadata": {
                    "permissions": {
                        "filesystem": {
                            "read": [allowed_root],
                            "write": [allowed_root],
                        }
                    }
                },
                "is_installed": True,
            }
            with patch("kendr.skill_manager.get_user_skill", return_value=skill_row):
                result = test_skill(
                    "skill-shell-cwd",
                    {"command": "pwd", "cwd": blocked_root},
                    approval={"approved": True, "note": "Attempt blocked cwd"},
                )

        self.assertFalse(result["success"])
        self.assertIn("outside the allowed filesystem scope", str(result["error"]))

    def test_python_skill_respects_filesystem_permission_manifest(self):
        with tempfile.TemporaryDirectory() as tmp:
            file_path = Path(tmp) / "fixture.txt"
            file_path.write_text("hello", encoding="utf-8")
            skill_row = {
                "skill_id": "skill-2",
                "slug": "read-file",
                "skill_type": "python",
                "catalog_id": "",
                "code": "with open(input['path'], 'r', encoding='utf-8') as fh:\n    output = fh.read()",
                "metadata": {
                    "permissions": {
                        "filesystem": {
                            "read": [tmp],
                        }
                    }
                },
                "is_installed": True,
            }
            with patch("kendr.skill_manager.get_user_skill", return_value=skill_row):
                result = test_skill(
                    "skill-2",
                    {"path": str(file_path)},
                    approval={"approved": True, "note": "Read fixture file"},
                )

        self.assertTrue(result["success"], result.get("error"))
        self.assertEqual(result["output"], "hello")

    def test_python_skill_blocks_file_access_outside_manifest(self):
        with tempfile.TemporaryDirectory() as tmp:
            file_path = Path(tmp) / "fixture.txt"
            file_path.write_text("hello", encoding="utf-8")
            skill_row = {
                "skill_id": "skill-3",
                "slug": "read-file-blocked",
                "skill_type": "python",
                "catalog_id": "",
                "code": "with open(input['path'], 'r', encoding='utf-8') as fh:\n    output = fh.read()",
                "metadata": {},
                "is_installed": True,
            }
            with patch("kendr.skill_manager.get_user_skill", return_value=skill_row):
                result = test_skill(
                    "skill-3",
                    {"path": str(file_path)},
                    approval={"approved": True, "note": "Attempt read"},
                )

        self.assertFalse(result["success"])
        self.assertIn("Read access denied", str(result["error"]))

    def test_shell_command_skill_requires_approval(self):
        skill_row = {
            "skill_id": "skill-4",
            "slug": "shell-command",
            "skill_type": "catalog",
            "catalog_id": "shell-command",
            "code": "",
            "metadata": {},
            "is_installed": True,
        }
        with patch("kendr.skill_manager.get_user_skill", return_value=skill_row):
            result = test_skill("skill-4", {"command": "pwd"})

        self.assertFalse(result["success"])
        self.assertIn("requires explicit approval", str(result["error"]))

    def test_api_caller_blocks_hosts_outside_manifest_scope(self):
        skill_row = {
            "skill_id": "skill-5",
            "slug": "api-caller",
            "skill_type": "catalog",
            "catalog_id": "api-caller",
            "code": "",
            "metadata": {
                "permissions": {
                    "network": {
                        "allow": True,
                        "domains": ["allowed.example"],
                    }
                }
            },
            "is_installed": True,
        }
        with patch("kendr.skill_manager.get_user_skill", return_value=skill_row):
            result = test_skill(
                "skill-5",
                {"url": "https://blocked.example/api", "method": "GET"},
                approval={"approved": True, "note": "API smoke"},
            )

        self.assertFalse(result["success"])
        self.assertIn("outside the allowed domain scope", str(result["error"]))

    def test_web_search_is_available_as_core_skill_without_install(self):
        with patch("kendr.skill_manager.get_user_skill", return_value=None):
            with patch(
                "kendr.skill_manager._run_extension_host",
                return_value={"success": True, "output": {"query": "cats", "results": [{"title": "Cats"}]}, "stdout": "", "stderr": "", "error": None},
            ) as host:
                result = execute_skill_by_slug("web-search", {"query": "cats"})

        self.assertTrue(result["success"], result.get("error"))
        self.assertEqual(result["output"]["query"], "cats")
        payload = host.call_args.args[1]
        self.assertEqual(host.call_args.args[0], "web-search")
        self.assertEqual(payload["permissions"]["network"]["domains"], ["api.duckduckgo.com"])

    def test_desktop_automation_core_skill_runs_in_sandbox_preview_without_approval(self):
        with patch("kendr.skill_manager.get_user_skill", return_value=None):
            with patch(
                "kendr.skill_manager._run_extension_host",
                return_value={
                    "success": True,
                    "output": {"access_mode": "sandbox", "preview_only": True, "dispatched": False},
                    "stdout": "",
                    "stderr": "",
                    "error": None,
                    "sandbox": {"mode": "configurable", "provider": "desktop_automation_broker"},
                },
            ) as host:
                result = execute_skill_by_slug(
                    "desktop-automation",
                    {"action": "list_apps", "app": "generic", "access_mode": "sandbox"},
                )

        self.assertTrue(result["success"], result.get("error"))
        self.assertTrue(result["output"]["preview_only"])
        payload = host.call_args.args[1]
        self.assertEqual(host.call_args.args[0], "desktop-automation")
        self.assertEqual(payload["permissions"]["desktop"]["access_mode"], "sandbox")
        self.assertFalse(payload["permissions"]["requires_approval"])

    def test_desktop_automation_full_access_requires_explicit_approval(self):
        with patch("kendr.skill_manager.get_user_skill", return_value=None):
            result = execute_skill_by_slug(
                "desktop-automation",
                {"action": "open_app", "app": "telegram", "access_mode": "full_access"},
            )

        self.assertFalse(result["success"])
        self.assertEqual(result.get("error_type"), "approval_required")
        self.assertEqual(result.get("pending_user_input_kind"), "skill_approval")
        self.assertEqual(
            result.get("approval_request", {}).get("metadata", {}).get("skill_slug"),
            "desktop-automation",
        )

    def test_marketplace_marks_web_search_as_core_installed(self):
        with patch("kendr.skill_manager.list_user_skills", return_value=[]):
            marketplace = get_marketplace()

        web_search = next(item for item in marketplace["catalog"] if item["id"] == "web-search")
        self.assertTrue(web_search["is_core"])
        self.assertTrue(web_search["is_installed"])
        self.assertEqual(web_search["skill_id"], "core:web-search")
        self.assertIn("sandbox", web_search)

    def test_marketplace_exposes_desktop_automation_capability_metadata(self):
        with patch("kendr.skill_manager.list_user_skills", return_value=[]):
            marketplace = get_marketplace()

        desktop = next(item for item in marketplace["catalog"] if item["id"] == "desktop-automation")
        self.assertTrue(desktop["is_core"])
        self.assertTrue(desktop["is_installed"])
        self.assertIn("desktop_automation", desktop)
        self.assertEqual(desktop["desktop_automation"]["default_access_mode"], "sandbox")

    def test_marketplace_includes_sandbox_runtime_summary(self):
        with patch("kendr.skill_manager.list_user_skills", return_value=[]):
            marketplace = get_marketplace()

        self.assertIn("sandbox_runtime", marketplace)
        self.assertEqual(marketplace["sandbox_runtime"]["provider"], "bubblewrap")
        self.assertIn("install_hint", marketplace["sandbox_runtime"])

    def test_marketplace_hides_unusable_or_unimplemented_catalog_skills(self):
        def _sandbox(*, skill_type="", catalog_id=""):
            if catalog_id == "shell-command":
                return {"mode": "blocked"}
            return {"mode": "process_isolated_only"}

        with patch("kendr.skill_manager.list_user_skills", return_value=[]):
            with patch("kendr.skill_manager.extension_sandbox.describe_skill_sandbox", side_effect=_sandbox):
                marketplace = get_marketplace()

        ids = {item["id"] for item in marketplace["catalog"]}
        self.assertIn("web-search", ids)
        self.assertIn("pdf-reader", ids)
        self.assertIn("api-caller", ids)
        self.assertNotIn("shell-command", ids)
        self.assertNotIn("spreadsheet", ids)
        self.assertNotIn("image-analysis", ids)
        self.assertNotIn("data-analysis", ids)
        self.assertNotIn("doc-writer", ids)
        self.assertNotIn("image-gen", ids)

    def test_marketplace_uses_catalog_permissions_for_installed_core_skill(self):
        stale_installed = {
            "skill_id": "installed-web-search",
            "slug": "web-search",
            "name": "Web Search",
            "skill_type": "catalog",
            "catalog_id": "web-search",
            "metadata": {
                "permissions": {
                    "requires_approval": False,
                    "filesystem": {"read": [], "write": []},
                    "environment": {"read": []},
                    "network": {"allow": False, "domains": []},
                    "shell": {"allow": False, "allow_root": False, "allow_destructive": False},
                }
            },
            "is_installed": True,
        }

        def _list_user_skills(*args, **kwargs):
            return [stale_installed]

        with patch("kendr.skill_manager.list_user_skills", side_effect=_list_user_skills):
            with patch("kendr.skill_manager.get_user_skill", return_value=stale_installed):
                marketplace = get_marketplace()

        web_search = next(item for item in marketplace["catalog"] if item["id"] == "web-search")
        self.assertEqual(web_search["skill_id"], "installed-web-search")
        self.assertTrue(web_search["permission_manifest"]["network"]["allow"])
        self.assertEqual(web_search["permission_manifest"]["network"]["domains"], ["api.duckduckgo.com"])

    def test_resolve_runtime_skill_attaches_sandbox_metadata(self):
        skill_row = {
            "skill_id": "skill-8",
            "slug": "custom-prompt",
            "name": "Custom Prompt",
            "skill_type": "prompt",
            "catalog_id": "",
            "metadata": {},
            "is_installed": True,
        }
        with patch("kendr.skill_manager.get_user_skill", return_value=skill_row):
            resolved = resolve_runtime_skill(skill_id="skill-8")

        self.assertIsNotNone(resolved)
        self.assertIn("permission_manifest", resolved)
        self.assertIn("sandbox", resolved)
        self.assertEqual(resolved["sandbox"]["mode"], "in_process")

    def test_python_skill_returns_structured_approval_request(self):
        skill_row = {
            "skill_id": "skill-6",
            "slug": "approval-demo",
            "skill_type": "python",
            "catalog_id": "",
            "code": "output = 1",
            "metadata": {},
            "is_installed": True,
            "name": "Approval Demo",
        }
        with patch("kendr.skill_manager.get_user_skill", return_value=skill_row):
            result = test_skill("skill-6", {}, session_id="sess-1")

        self.assertFalse(result["success"])
        self.assertEqual(result["error_type"], "approval_required")
        self.assertTrue(result["awaiting_user_input"])
        self.assertEqual(result["pending_user_input_kind"], "skill_approval")
        self.assertIn("suggested_scopes", result["approval_request"]["metadata"])

    def test_once_grant_created_via_api_path_is_consumed_by_next_execution(self):
        skill_row = {
            "skill_id": "skill-7",
            "slug": "approval-once-demo",
            "skill_type": "python",
            "catalog_id": "",
            "code": "output = 7",
            "metadata": {},
            "is_installed": True,
            "name": "Approval Once Demo",
        }
        with patch("kendr.skill_manager.get_user_skill", return_value=skill_row):
            grant = grant_skill_approval(
                skill_id="skill-7",
                scope="once",
                note="Allow one execution",
                session_id="sess-2",
            )
            result = test_skill("skill-7", {}, session_id="sess-2")

        self.assertEqual(grant["status"], "active")
        self.assertTrue(result["success"], result.get("error"))
        self.assertEqual(result["output"], 7)


if __name__ == "__main__":
    unittest.main()
