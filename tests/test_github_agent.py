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

    def test_git_env_uses_token_scheme_not_bearer(self):
        from tasks.github_client import GitHubClient
        client = GitHubClient(token="ghp_testtoken")
        env = client._git_env()
        val = env.get("GIT_CONFIG_VALUE_0", "")
        self.assertIn("Authorization: token ghp_testtoken", val)
        self.assertNotIn("Bearer", val)

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
    """Tests for _fallback_operations() deterministic sequence invariants."""

    def test_pr_task_includes_expected_ops(self):
        from tasks.github_tasks import _fallback_operations
        ops = _fallback_operations("fix the broken test and open a pull request")
        names = [o["op"] for o in ops]
        self.assertIn("clone_repo", names)
        self.assertIn("create_branch", names)
        self.assertIn("commit", names)
        self.assertIn("push", names)
        self.assertIn("create_pr", names)

    def test_pr_task_ops_in_correct_order(self):
        from tasks.github_tasks import _fallback_operations
        ops = _fallback_operations("fix the broken test and open a pull request")
        names = [o["op"] for o in ops]
        clone_i = names.index("clone_repo")
        commit_i = names.index("commit")
        push_i = names.index("push")
        pr_i = names.index("create_pr")
        self.assertLess(clone_i, commit_i)
        self.assertLess(commit_i, push_i)
        self.assertLess(push_i, pr_i)

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


if __name__ == "__main__":
    unittest.main()
