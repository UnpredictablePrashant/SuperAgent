"""GitHub REST API client and local git operation wrapper for kendr's github_agent.

Architecture — async-first with sync bridge:
    REST API calls are implemented in ``AsyncGitHubClient`` using Python's
    standard-library ``asyncio`` with thread-executor offloading for the
    blocking ``urllib.request`` calls.  This gives a true async interface for
    callers that run inside an event loop.

    ``GitHubClient`` is a thin synchronous bridge that delegates every REST
    method to its async counterpart via ``asyncio.run()``.  kendr's multi-agent
    runtime is fully synchronous (no running event loop), so ``asyncio.run()``
    is always safe here.  Any future migration to an async runtime can simply
    use ``AsyncGitHubClient`` directly.

    Local git operations (subprocess) remain synchronous in both classes
    because subprocess.run() is not made meaningfully faster by wrapping in
    asyncio, and git commands are short-lived.
"""

from __future__ import annotations

import asyncio
import json
import os
import subprocess
from pathlib import Path
from typing import Any
from urllib.error import HTTPError
from urllib.request import Request, urlopen


GITHUB_API_BASE = "https://api.github.com"
_DEFAULT_TIMEOUT = 30


class AsyncGitHubClient:
    """Async GitHub REST API wrapper.

    All REST methods are ``async def`` and run HTTP I/O in a thread executor so
    callers inside an event loop are never blocked.  Local git operations are
    provided as regular (synchronous) methods because subprocess is
    process-level and not meaningfully improved by async wrapping.
    """

    def __init__(self, token: str | None = None, api_base: str = GITHUB_API_BASE) -> None:
        self.token = token or os.getenv("GITHUB_TOKEN") or ""
        self.api_base = api_base.rstrip("/")

    def _headers(self) -> dict[str, str]:
        headers = {
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "Content-Type": "application/json",
        }
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        return headers

    def _request_sync(self, method: str, path: str, body: dict | None, timeout: int) -> Any:
        url = f"{self.api_base}/{path.lstrip('/')}"
        data = json.dumps(body).encode("utf-8") if body is not None else None
        req = Request(url, data=data, headers=self._headers(), method=method)
        try:
            with urlopen(req, timeout=timeout) as resp:
                raw = resp.read().decode("utf-8")
                return json.loads(raw) if raw.strip() else {}
        except HTTPError as exc:
            err_body = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"GitHub API {method} {path} → HTTP {exc.code}: {err_body}") from exc

    async def _request(self, method: str, path: str, body: dict | None = None, timeout: int = _DEFAULT_TIMEOUT) -> Any:
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, self._request_sync, method, path, body, timeout)

    async def _get(self, path: str, timeout: int = _DEFAULT_TIMEOUT) -> Any:
        return await self._request("GET", path, timeout=timeout)

    async def _post(self, path: str, body: dict) -> Any:
        return await self._request("POST", path, body=body)

    async def _put(self, path: str, body: dict | None = None) -> Any:
        return await self._request("PUT", path, body=body or {})

    async def get_repo(self, owner: str, repo: str) -> dict:
        return await self._get(f"/repos/{owner}/{repo}")

    async def test_connection(self) -> dict:
        """Test the stored token by calling GET /user."""
        if not self.token:
            return {"ok": False, "error": "GITHUB_TOKEN is not configured."}
        try:
            user = await self._get("/user")
            login = str(user.get("login") or "")
            return {"ok": True, "login": login, "detail": f"Authenticated as {login}"}
        except RuntimeError as exc:
            return {"ok": False, "error": str(exc)}

    async def list_issues(self, owner: str, repo: str, state: str = "open", per_page: int = 30) -> list[dict]:
        result = await self._get(f"/repos/{owner}/{repo}/issues?state={state}&per_page={per_page}")
        return result if isinstance(result, list) else []

    async def get_issue(self, owner: str, repo: str, number: int) -> dict:
        return await self._get(f"/repos/{owner}/{repo}/issues/{number}")

    async def add_comment(self, owner: str, repo: str, issue_number: int, body: str) -> dict:
        return await self._post(f"/repos/{owner}/{repo}/issues/{issue_number}/comments", {"body": body})

    async def list_pull_requests(self, owner: str, repo: str, state: str = "open") -> list[dict]:
        result = await self._get(f"/repos/{owner}/{repo}/pulls?state={state}&per_page=30")
        return result if isinstance(result, list) else []

    async def get_pull_request(self, owner: str, repo: str, pr_number: int) -> dict:
        return await self._get(f"/repos/{owner}/{repo}/pulls/{pr_number}")

    async def create_pull_request(
        self,
        owner: str,
        repo: str,
        title: str,
        body: str,
        head: str,
        base: str = "main",
    ) -> dict:
        return await self._post(
            f"/repos/{owner}/{repo}/pulls",
            {"title": title, "body": body, "head": head, "base": base},
        )

    async def merge_pull_request(
        self,
        owner: str,
        repo: str,
        pr_number: int,
        commit_title: str = "",
        merge_method: str = "merge",
    ) -> dict:
        payload: dict[str, str] = {"merge_method": merge_method}
        if commit_title:
            payload["commit_title"] = commit_title
        return await self._put(f"/repos/{owner}/{repo}/pulls/{pr_number}/merge", payload)

    async def list_branches(self, owner: str, repo: str) -> list[dict]:
        result = await self._get(f"/repos/{owner}/{repo}/branches?per_page=50")
        return result if isinstance(result, list) else []

    def _git_env(self) -> dict[str, str]:
        """Return a subprocess environment with git auth configured via HTTP extra-header.

        The token is passed through git's environment-variable config mechanism
        (GIT_CONFIG_COUNT / GIT_CONFIG_KEY_* / GIT_CONFIG_VALUE_*), which means it is
        never embedded in any remote URL, never written to .git/config, and is not
        visible in ``ps aux`` output (environment vars, not process args).
        """
        env = os.environ.copy()
        env["GIT_TERMINAL_PROMPT"] = "0"
        if self.token:
            env["GIT_CONFIG_COUNT"] = "1"
            env["GIT_CONFIG_KEY_0"] = "http.extraHeader"
            env["GIT_CONFIG_VALUE_0"] = f"Authorization: Bearer {self.token}"
        return env

    def _run_git(self, args: list[str], cwd: Path, timeout: int = 120) -> str:
        result = subprocess.run(
            ["git"] + args,
            cwd=str(cwd),
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
            env=self._git_env(),
        )
        if result.returncode != 0:
            raise RuntimeError(
                result.stderr.strip() or result.stdout.strip() or f"git {' '.join(args)} failed"
            )
        return result.stdout.strip()

    def clone_repo(self, clone_url: str, to_dir: Path, depth: int = 0) -> Path:
        args = ["clone"]
        if depth:
            args += ["--depth", str(depth)]
        args += [clone_url, str(to_dir)]
        result = subprocess.run(
            ["git"] + args,
            capture_output=True,
            text=True,
            timeout=300,
            check=False,
            env=self._git_env(),
        )
        if result.returncode != 0:
            raise RuntimeError(result.stderr.strip() or result.stdout.strip() or "git clone failed")
        return to_dir

    def clone_repo_authenticated(self, owner: str, repo: str, to_dir: Path, depth: int = 0) -> Path:
        """Clone via HTTPS injecting the token as an HTTP Authorization header env-var."""
        clone_url = f"https://github.com/{owner}/{repo}.git"
        return self.clone_repo(clone_url, to_dir, depth=depth)

    def pull(self, repo_dir: Path) -> str:
        return self._run_git(["pull"], repo_dir)

    def create_branch(self, repo_dir: Path, branch: str) -> str:
        return self._run_git(["checkout", "-b", branch], repo_dir)

    def switch_branch(self, repo_dir: Path, branch: str) -> str:
        return self._run_git(["checkout", branch], repo_dir)

    def diff(self, repo_dir: Path) -> str:
        return self._run_git(["diff", "HEAD"], repo_dir)

    def diff_staged(self, repo_dir: Path) -> str:
        return self._run_git(["diff", "--cached"], repo_dir)

    def has_uncommitted_changes(self, repo_dir: Path) -> bool:
        """Return True if there are staged or unstaged changes in the working tree."""
        result = subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=str(repo_dir),
            capture_output=True,
            text=True,
            timeout=15,
            check=False,
        )
        return bool(result.stdout.strip())

    def commit(self, repo_dir: Path, message: str, add_all: bool = True) -> str:
        if add_all:
            self._run_git(["add", "-A"], repo_dir)
        result = subprocess.run(
            ["git", "commit", "-m", message],
            cwd=str(repo_dir),
            capture_output=True,
            text=True,
            timeout=60,
            check=False,
            env=self._git_env(),
        )
        combined = result.stdout.strip() + result.stderr.strip()
        if result.returncode != 0 and "nothing to commit" not in combined:
            raise RuntimeError(combined or "git commit failed")
        return combined

    def push(self, repo_dir: Path, remote: str = "origin", branch: str = "") -> str:
        args = ["push", remote]
        if branch:
            args.append(branch)
        return self._run_git(args, repo_dir, timeout=120)

    def push_set_upstream(self, repo_dir: Path, branch: str, remote: str = "origin") -> str:
        return self._run_git(["push", "--set-upstream", remote, branch], repo_dir, timeout=120)

    @staticmethod
    def _safe_repo_path(repo_dir: Path, relative_path: str) -> Path:
        """Resolve *relative_path* inside *repo_dir* and reject any path-traversal attempts."""
        resolved = (repo_dir / relative_path).resolve()
        repo_resolved = repo_dir.resolve()
        try:
            resolved.relative_to(repo_resolved)
        except ValueError:
            raise PermissionError(
                f"Path traversal denied: '{relative_path}' escapes the repository root."
            )
        return resolved

    @staticmethod
    def read_repo_file(repo_dir: Path, relative_path: str) -> str:
        target = AsyncGitHubClient._safe_repo_path(repo_dir, relative_path)
        return target.read_text(encoding="utf-8")

    @staticmethod
    def write_repo_file(repo_dir: Path, relative_path: str, content: str) -> None:
        target = AsyncGitHubClient._safe_repo_path(repo_dir, relative_path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")

    @staticmethod
    def current_branch(repo_dir: Path) -> str:
        result = subprocess.run(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            cwd=str(repo_dir),
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
        return result.stdout.strip() if result.returncode == 0 else "unknown"


class GitHubClient(AsyncGitHubClient):
    """Synchronous bridge over ``AsyncGitHubClient``.

    Every async REST method is surfaced as a synchronous call via
    ``asyncio.run()``.  This is safe because kendr's multi-agent runtime
    does not maintain a running event loop on the calling thread.
    Callers inside an event loop should use ``AsyncGitHubClient`` directly.
    """

    def test_connection(self) -> dict:
        return asyncio.run(super().test_connection())

    def get_repo(self, owner: str, repo: str) -> dict:
        return asyncio.run(super().get_repo(owner, repo))

    def list_issues(self, owner: str, repo: str, state: str = "open", per_page: int = 30) -> list[dict]:
        return asyncio.run(super().list_issues(owner, repo, state=state, per_page=per_page))

    def get_issue(self, owner: str, repo: str, number: int) -> dict:
        return asyncio.run(super().get_issue(owner, repo, number))

    def add_comment(self, owner: str, repo: str, issue_number: int, body: str) -> dict:
        return asyncio.run(super().add_comment(owner, repo, issue_number, body))

    def list_pull_requests(self, owner: str, repo: str, state: str = "open") -> list[dict]:
        return asyncio.run(super().list_pull_requests(owner, repo, state=state))

    def get_pull_request(self, owner: str, repo: str, pr_number: int) -> dict:
        return asyncio.run(super().get_pull_request(owner, repo, pr_number))

    def create_pull_request(
        self,
        owner: str,
        repo: str,
        title: str,
        body: str,
        head: str,
        base: str = "main",
    ) -> dict:
        return asyncio.run(super().create_pull_request(owner, repo, title, body, head, base))

    def merge_pull_request(
        self,
        owner: str,
        repo: str,
        pr_number: int,
        commit_title: str = "",
        merge_method: str = "merge",
    ) -> dict:
        return asyncio.run(super().merge_pull_request(owner, repo, pr_number, commit_title, merge_method))

    def list_branches(self, owner: str, repo: str) -> list[dict]:
        return asyncio.run(super().list_branches(owner, repo))
