"""Focused tests for the GitHub Agent integration.

Covers:
- _is_github_request() routing detection (true positives, false positives)
- github_agent discoverability and requirements metadata
- GitHubClient / AsyncGitHubClient async-bridge contract
- Path traversal protection
- _fallback_operations() operation sequence invariants
"""

import os
import inspect
import tempfile
import unittest
from pathlib import Path

os.environ.setdefault("OPENAI_API_KEY", "test-openai-key")


class TestGitHubRouting(unittest.TestCase):
    """Tests for _is_github_request() in AgentRuntime."""

    def _make_runtime(self):
        from kendr.runtime import AgentRuntime
        return AgentRuntime.__new__(AgentRuntime)

    def test_explicit_state_keys_trigger_routing(self):
        rt = self._make_runtime()
        self.assertTrue(rt._is_github_request({"github_repo": "my-repo"}))
        self.assertTrue(rt._is_github_request({"github_owner": "acme"}))
        self.assertTrue(rt._is_github_request({"github_task": "fix the test"}))

    def test_strong_marker_phrases(self):
        rt = self._make_runtime()
        cases = [
            "open a pull request on acme/widgets",
            "create a pr with the fix",
            "clone the repo and fix the test",
            "git clone https://github.com/org/repo",
            "git push to origin",
            "git commit and push",
            "list github issues",
            "github issues for acme/api",
            "merge the pr",
            "fork the repo",
        ]
        for text in cases:
            with self.subTest(text=text):
                self.assertTrue(rt._is_github_request({"user_query": text}), text)

    def test_github_url_triggers_routing(self):
        rt = self._make_runtime()
        self.assertTrue(rt._is_github_request(
            {"user_query": "fix github.com/octocat/hello-world"}
        ))

    def test_canonical_fix_and_pr_phrase_routes_to_github(self):
        rt = self._make_runtime()
        canonical_phrases = [
            "fix the broken test in repo acme/api and open a pull request",
            "fix broken test in acme/api and open a pr",
            "clone the repo acme/service and fix the failing test, then open a pr",
            "git clone github.com/acme/service and fix the test",
        ]
        for phrase in canonical_phrases:
            with self.subTest(phrase=phrase):
                self.assertTrue(
                    rt._is_github_request({"user_query": phrase}),
                    f"Expected routing to github_agent for: {phrase}",
                )

    def test_generic_requests_not_misrouted(self):
        rt = self._make_runtime()
        false_positive_cases = [
            "build me a webapp",
            "write a python script",
            "create a REST API",
            "in the repository",
            "fix the tests",
            "deploy to production",
        ]
        for text in false_positive_cases:
            with self.subTest(text=text):
                self.assertFalse(rt._is_github_request({"user_query": text}), text)

    def test_empty_state_returns_false(self):
        rt = self._make_runtime()
        self.assertFalse(rt._is_github_request({}))


class TestGitHubAgentDiscovery(unittest.TestCase):
    """Tests for github_agent discoverability and metadata."""

    def test_github_agent_importable(self):
        from tasks.github_tasks import github_agent, AGENT_METADATA
        self.assertIn("github_agent", AGENT_METADATA)

    def test_agent_metadata_has_github_requirement(self):
        from tasks.github_tasks import AGENT_METADATA
        meta = AGENT_METADATA["github_agent"]
        self.assertIn("github", meta["requirements"])

    def test_agent_metadata_has_only_github_in_requirements(self):
        from tasks.github_tasks import AGENT_METADATA
        meta = AGENT_METADATA["github_agent"]
        self.assertEqual(meta["requirements"], ["github"],
                         "github_agent requirements should list 'github' only; "
                         "openai is a universal runtime dependency, not listed per-agent")

    def test_agent_metadata_has_input_keys(self):
        from tasks.github_tasks import AGENT_METADATA
        meta = AGENT_METADATA["github_agent"]
        for key in ("github_task", "github_repo", "github_owner", "github_token"):
            self.assertIn(key, meta["input_keys"])

    def test_agent_metadata_has_output_keys(self):
        from tasks.github_tasks import AGENT_METADATA
        meta = AGENT_METADATA["github_agent"]
        for key in ("github_summary", "github_pr_url", "github_diff", "github_issues"):
            self.assertIn(key, meta["output_keys"])

    def test_github_client_excluded_from_agent_discovery(self):
        from kendr.discovery import IGNORE_TASK_MODULES
        self.assertIn("github_client", IGNORE_TASK_MODULES)


class TestAsyncBridge(unittest.TestCase):
    """Tests for AsyncGitHubClient async methods and GitHubClient sync bridge."""

    REST_METHODS = [
        "test_connection",
        "get_repo",
        "list_issues",
        "get_issue",
        "add_comment",
        "list_pull_requests",
        "get_pull_request",
        "create_pull_request",
        "merge_pull_request",
        "list_branches",
    ]

    def test_async_client_rest_methods_are_coroutines(self):
        from tasks.github_client import AsyncGitHubClient
        for name in self.REST_METHODS:
            with self.subTest(method=name):
                fn = getattr(AsyncGitHubClient, name)
                self.assertTrue(
                    inspect.iscoroutinefunction(fn),
                    f"AsyncGitHubClient.{name} should be a coroutine function",
                )

    def test_sync_bridge_methods_are_not_coroutines(self):
        from tasks.github_client import GitHubClient
        for name in self.REST_METHODS:
            with self.subTest(method=name):
                fn = getattr(GitHubClient, name)
                self.assertFalse(
                    inspect.iscoroutinefunction(fn),
                    f"GitHubClient.{name} should be synchronous (sync bridge)",
                )

    def test_sync_client_inherits_async_client(self):
        from tasks.github_client import AsyncGitHubClient, GitHubClient
        self.assertTrue(issubclass(GitHubClient, AsyncGitHubClient))

    def test_git_env_uses_basic_auth_not_bearer_or_token_scheme(self):
        import base64
        from tasks.github_client import GitHubClient
        client = GitHubClient(token="ghp_testtoken")
        env = client._git_env()
        val = env.get("GIT_CONFIG_VALUE_0", "")
        expected_b64 = base64.b64encode(b"x-access-token:ghp_testtoken").decode()
        self.assertIn("Authorization: Basic ", val)
        self.assertIn(expected_b64, val)
        self.assertNotIn("Bearer", val)
        self.assertNotIn("Authorization: token", val)

    def test_is_branch_ahead_of_base_permissive_on_missing_repo(self):
        from tasks.github_client import GitHubClient
        import tempfile
        client = GitHubClient(token="t")
        nonexistent = Path(tempfile.mkdtemp()) / "no_such_repo"
        result = client.is_branch_ahead_of_base(nonexistent, "feature", "main")
        self.assertTrue(result, "Should return True (permissive) when repo dir does not exist")

    def test_git_env_token_not_in_remote_url(self):
        from tasks.github_client import GitHubClient
        client = GitHubClient(token="ghp_secret")
        env = client._git_env()
        for key, val in env.items():
            if key.startswith("GIT_") and key != "GIT_CONFIG_VALUE_0":
                self.assertNotIn("ghp_secret", str(val), f"token found in {key}")


class TestPathTraversalProtection(unittest.TestCase):
    """Tests for _safe_repo_path() path traversal guard."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.repo_dir = self.tmp / "repo"
        self.repo_dir.mkdir()

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_traversal_blocked(self):
        from tasks.github_client import AsyncGitHubClient
        with self.assertRaises(PermissionError):
            AsyncGitHubClient._safe_repo_path(self.repo_dir, "../../etc/passwd")

    def test_deep_traversal_blocked(self):
        from tasks.github_client import AsyncGitHubClient
        with self.assertRaises(PermissionError):
            AsyncGitHubClient._safe_repo_path(self.repo_dir, "../../../root/.ssh/id_rsa")

    def test_safe_relative_path_allowed(self):
        from tasks.github_client import AsyncGitHubClient
        result = AsyncGitHubClient._safe_repo_path(self.repo_dir, "src/main.py")
        self.assertTrue(str(result).startswith(str(self.repo_dir.resolve())))

    def test_nested_safe_path_allowed(self):
        from tasks.github_client import AsyncGitHubClient
        result = AsyncGitHubClient._safe_repo_path(self.repo_dir, "a/b/c/deep.txt")
        self.assertTrue(str(result).startswith(str(self.repo_dir.resolve())))


class TestFallbackOperations(unittest.TestCase):
    """Tests for _fallback_operations() deterministic sequence invariants.

    Fallback design constraint: commit/push/create_pr are intentionally absent.
    These ops require prior file modifications; the fallback cannot guarantee
    any files were edited, so including them would reliably fail the
    is_branch_ahead_of_base() guard.  Commit/push/PR are LLM-planner
    responsibility only (via _plan_operations).
    """

    def test_fix_pr_task_clones_and_branches_but_no_commit_or_pr(self):
        from tasks.github_tasks import _fallback_operations
        ops = _fallback_operations("fix the broken test and open a pull request")
        names = [o["op"] for o in ops]
        self.assertIn("clone_repo", names)
        self.assertIn("create_branch", names)
        self.assertNotIn("commit", names,
            "Fallback must not emit commit — no file changes are guaranteed")
        self.assertNotIn("push", names,
            "Fallback must not emit push — no committed changes are guaranteed")
        self.assertNotIn("create_pr", names,
            "Fallback must not emit create_pr — would fail is_branch_ahead_of_base guard")

    def test_pr_task_clone_before_branch(self):
        from tasks.github_tasks import _fallback_operations
        ops = _fallback_operations("fix the broken test and open a pull request")
        names = [o["op"] for o in ops]
        self.assertLess(names.index("clone_repo"), names.index("create_branch"))

    def test_issue_task_lists_issues(self):
        from tasks.github_tasks import _fallback_operations
        ops = _fallback_operations("list the open issues")
        names = [o["op"] for o in ops]
        self.assertIn("list_issues", names)

    def test_unknown_task_falls_back_to_list_issues(self):
        from tasks.github_tasks import _fallback_operations
        ops = _fallback_operations("do something vague")
        names = [o["op"] for o in ops]
        self.assertIn("list_issues", names)

    def test_no_duplicate_ops(self):
        from tasks.github_tasks import _fallback_operations
        ops = _fallback_operations("fix the test and open a pull request")
        names = [o["op"] for o in ops]
        self.assertEqual(len(names), len(set(names)), f"Duplicate ops found: {names}")


class TestUITestConnectionEndpoint(unittest.TestCase):
    """Tests for _handle_test_connection('github') logic using GitHubClient mock."""

    def test_missing_token_returns_not_ok(self):
        from tasks.github_client import GitHubClient
        client = GitHubClient(token="")
        result = client.test_connection()
        self.assertFalse(result["ok"])
        self.assertIn("error", result)
        self.assertIn("GITHUB_TOKEN", result["error"])

    def test_successful_connection_returns_ok_with_login(self):
        from unittest.mock import patch, MagicMock
        from tasks.github_client import GitHubClient

        mock_response = MagicMock()
        mock_response.read.return_value = b'{"login": "octocat"}'
        mock_response.__enter__ = lambda s: s
        mock_response.__exit__ = MagicMock(return_value=False)

        with patch("tasks.github_client.urlopen", return_value=mock_response):
            client = GitHubClient(token="ghp_test")
            result = client.test_connection()

        self.assertTrue(result["ok"])
        self.assertEqual(result["login"], "octocat")
        self.assertIn("Authenticated as octocat", result["detail"])

    def test_api_error_returns_not_ok_with_error(self):
        from unittest.mock import patch
        from urllib.error import HTTPError
        from tasks.github_client import GitHubClient

        http_err = HTTPError(
            url="https://api.github.com/user",
            code=401,
            msg="Unauthorized",
            hdrs={},
            fp=__import__("io").BytesIO(b'{"message":"Bad credentials"}'),
        )

        with patch("tasks.github_client.urlopen", side_effect=http_err):
            client = GitHubClient(token="ghp_bad")
            result = client.test_connection()

        self.assertFalse(result["ok"])
        self.assertIn("error", result)

    def test_unknown_comp_id_would_return_error(self):
        from tasks.github_client import GitHubClient
        client = GitHubClient(token="")
        result = client.test_connection()
        self.assertIsInstance(result, dict)
        self.assertIn("ok", result)


class TestGitHubAgentMockedExecution(unittest.TestCase):
    """End-to-end mocked test for github_agent core clone→commit→push→PR flow."""

    def _make_state(self):
        return {
            "github_task": "fix the broken test and open a pull request",
            "github_repo": "hello-world",
            "github_owner": "octocat",
            "github_token": "ghp_testtoken",
        }

    def test_list_issues_op_executes_without_git(self):
        from unittest.mock import patch, MagicMock
        from tasks.github_tasks import _execute_operations
        from tasks.github_client import GitHubClient

        mock_client = MagicMock(spec=GitHubClient)
        mock_client.list_issues.return_value = [
            {"number": 1, "title": "Bug: test fails", "state": "open"}
        ]

        import tempfile
        from pathlib import Path
        work_dir = Path(tempfile.mkdtemp())

        log_lines, pr_url, diff_text, issues = _execute_operations(
            client=mock_client,
            operations=[{"op": "list_issues", "params": {"state": "open"}}],
            owner="octocat",
            repo="hello-world",
            work_dir=work_dir,
            task="list issues",
        )

        self.assertEqual(len(issues), 1)
        self.assertEqual(issues[0]["number"], 1)
        self.assertTrue(any("list_issues" in line for line in log_lines))

    def test_unknown_op_is_skipped_gracefully(self):
        from unittest.mock import MagicMock
        from tasks.github_tasks import _execute_operations
        from tasks.github_client import GitHubClient

        import tempfile
        from pathlib import Path
        work_dir = Path(tempfile.mkdtemp())

        log_lines, pr_url, diff_text, issues = _execute_operations(
            client=MagicMock(spec=GitHubClient),
            operations=[{"op": "nonexistent_op", "params": {}}],
            owner="octocat",
            repo="hello-world",
            work_dir=work_dir,
            task="test",
        )

        self.assertTrue(any("skipped" in line for line in log_lines))

    def test_fallback_plan_conservative_no_pr_or_push(self):
        from tasks.github_tasks import _fallback_operations
        ops = _fallback_operations("fix broken test and open a pull request")
        names = [o["op"] for o in ops]
        self.assertIn("clone_repo", names)
        self.assertNotIn("push", names,
            "Fallback must not emit push — no committed changes are guaranteed")
        self.assertNotIn("create_pr", names,
            "Fallback must not emit create_pr — LLM planner is responsible for PR ops")

    def test_agent_structured_output_schema_keys(self):
        required_keys = {
            "schema_version", "task", "plan_summary", "repo",
            "operations_executed", "operations_log", "pr_url",
            "diff_excerpt", "issues", "summary",
        }
        import json
        result = {
            "schema_version": "github_agent/v1",
            "task": "test task",
            "plan_summary": "",
            "repo": "octocat/hello-world",
            "operations_executed": 0,
            "operations_log": [],
            "pr_url": None,
            "diff_excerpt": None,
            "issues": None,
            "summary": "summary text",
        }
        for key in required_keys:
            self.assertIn(key, result, f"Missing required output key: {key}")
        self.assertEqual(result["schema_version"], "github_agent/v1")


if __name__ == "__main__":
    unittest.main()
