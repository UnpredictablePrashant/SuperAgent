"""GitHub REST API client and local git operation wrapper for kendr's github_agent."""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path
from typing import Any
from urllib.error import HTTPError
from urllib.request import Request, urlopen


GITHUB_API_BASE = "https://api.github.com"
_DEFAULT_TIMEOUT = 30


class GitHubClient:
    """Thin wrapper around the GitHub REST API plus local git operations."""

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

    def _request(self, method: str, path: str, body: dict | None = None, timeout: int = _DEFAULT_TIMEOUT) -> Any:
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

    def _get(self, path: str, timeout: int = _DEFAULT_TIMEOUT) -> Any:
        return self._request("GET", path, timeout=timeout)

    def _post(self, path: str, body: dict) -> Any:
        return self._request("POST", path, body=body)

    def _put(self, path: str, body: dict | None = None) -> Any:
        return self._request("PUT", path, body=body or {})

    def get_repo(self, owner: str, repo: str) -> dict:
        return self._get(f"/repos/{owner}/{repo}")

    def list_issues(self, owner: str, repo: str, state: str = "open", per_page: int = 30) -> list[dict]:
        result = self._get(f"/repos/{owner}/{repo}/issues?state={state}&per_page={per_page}")
        return result if isinstance(result, list) else []

    def get_issue(self, owner: str, repo: str, number: int) -> dict:
        return self._get(f"/repos/{owner}/{repo}/issues/{number}")

    def add_comment(self, owner: str, repo: str, issue_number: int, body: str) -> dict:
        return self._post(f"/repos/{owner}/{repo}/issues/{issue_number}/comments", {"body": body})

    def list_pull_requests(self, owner: str, repo: str, state: str = "open") -> list[dict]:
        result = self._get(f"/repos/{owner}/{repo}/pulls?state={state}&per_page=30")
        return result if isinstance(result, list) else []

    def get_pull_request(self, owner: str, repo: str, pr_number: int) -> dict:
        return self._get(f"/repos/{owner}/{repo}/pulls/{pr_number}")

    def create_pull_request(
        self,
        owner: str,
        repo: str,
        title: str,
        body: str,
        head: str,
        base: str = "main",
    ) -> dict:
        return self._post(
            f"/repos/{owner}/{repo}/pulls",
            {"title": title, "body": body, "head": head, "base": base},
        )

    def merge_pull_request(
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
        return self._put(f"/repos/{owner}/{repo}/pulls/{pr_number}/merge", payload)

    def list_branches(self, owner: str, repo: str) -> list[dict]:
        result = self._get(f"/repos/{owner}/{repo}/branches?per_page=50")
        return result if isinstance(result, list) else []

    @staticmethod
    def _run_git(args: list[str], cwd: Path, timeout: int = 120) -> str:
        result = subprocess.run(
            ["git"] + args,
            cwd=str(cwd),
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
        if result.returncode != 0:
            raise RuntimeError(
                result.stderr.strip() or result.stdout.strip() or f"git {' '.join(args)} failed"
            )
        return result.stdout.strip()

    def clone_repo(self, clone_url: str, to_dir: Path, depth: int = 0) -> Path:
        """Clone a repository to *to_dir*. Returns the cloned directory path."""
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
        )
        if result.returncode != 0:
            raise RuntimeError(result.stderr.strip() or result.stdout.strip() or "git clone failed")
        return to_dir

    def clone_repo_authenticated(self, owner: str, repo: str, to_dir: Path, depth: int = 0) -> Path:
        """Clone via HTTPS with GITHUB_TOKEN embedded in the URL."""
        if self.token:
            clone_url = f"https://{self.token}@github.com/{owner}/{repo}.git"
        else:
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
    def read_repo_file(repo_dir: Path, relative_path: str) -> str:
        return (repo_dir / relative_path).read_text(encoding="utf-8")

    @staticmethod
    def write_repo_file(repo_dir: Path, relative_path: str, content: str) -> None:
        target = repo_dir / relative_path
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
