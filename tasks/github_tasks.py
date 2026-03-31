"""GitHub agent for kendr multi-agent runtime.

Supports: clone, pull, push, branch create/switch, commit with message,
diff, file read/write in repo, issue list/read, PR create/merge, comments.
"""

from __future__ import annotations

import json
import os
import re
import tempfile
from pathlib import Path

from tasks.a2a_agent_utils import begin_agent_session, publish_agent_output
from tasks.github_client import GitHubClient
from tasks.utils import llm, log_task_update, normalize_llm_text, write_text_file


AGENT_METADATA = {
    "github_agent": {
        "description": (
            "Operates on GitHub repositories autonomously: clones repos, creates branches, "
            "edits files, commits, pushes, opens and merges pull requests, lists and reads issues, "
            "and adds comments — all from a natural language task description."
        ),
        "skills": [
            "github",
            "git",
            "pull request",
            "code review",
            "repository management",
            "issue tracking",
            "version control",
            "branch management",
        ],
        "input_keys": [
            "github_task",
            "github_repo",
            "github_owner",
            "github_token",
            "github_base_branch",
            "github_work_dir",
        ],
        "output_keys": [
            "github_summary",
            "github_pr_url",
            "github_diff",
            "github_issues",
            "github_operations_log",
        ],
        "requirements": ["github"],
    },
}

_AVAILABLE_OPERATIONS = [
    "clone_repo",
    "pull",
    "create_branch",
    "switch_branch",
    "read_file",
    "write_file",
    "commit",
    "push",
    "diff",
    "list_issues",
    "get_issue",
    "create_pr",
    "merge_pr",
    "add_comment",
]


def _strip_fences(text: str) -> str:
    stripped = normalize_llm_text(text).strip()
    if stripped.startswith("```") and stripped.endswith("```"):
        lines = stripped.splitlines()
        if len(lines) >= 2:
            return "\n".join(lines[1:-1]).strip()
    return stripped


def _parse_repo_slug(text: str) -> tuple[str, str] | None:
    """Extract (owner, repo) from a GitHub URL or an 'owner/repo' slug in *text*."""
    url_match = re.search(
        r"github\.com[/:]([A-Za-z0-9_.-]+)/([A-Za-z0-9_.-]+?)(?:\.git)?(?:[/?#]|$)",
        text,
    )
    if url_match:
        return url_match.group(1), url_match.group(2)
    slug_match = re.search(r"\b([A-Za-z0-9_.-]+)/([A-Za-z0-9_.-]+)\b", text)
    if slug_match:
        return slug_match.group(1), slug_match.group(2)
    return None


def _plan_operations(task: str) -> dict:
    """Ask the LLM to decompose *task* into a sequence of GitHub operations."""
    prompt = f"""
You are the github_agent in a multi-agent runtime. Parse the following task into a structured
GitHub operations plan.

Task:
{task}

Available operations: {json.dumps(_AVAILABLE_OPERATIONS)}

Respond ONLY with valid JSON (no markdown fences) using this exact schema:
{{
  "owner": "github-org-or-user",
  "repo": "repository-name",
  "operations": [
    {{
      "op": "operation-name",
      "params": {{}}
    }}
  ],
  "summary": "one-line plan summary"
}}

Operation names and params reference:
- clone_repo: {{}}
- pull: {{}}
- create_branch: {{"branch": "branch-name"}}
- switch_branch: {{"branch": "branch-name"}}
- read_file: {{"path": "relative/path"}}
- write_file: {{"path": "relative/path", "content": "actual content or __GENERATE__"}}
- commit: {{"message": "commit message"}}
- push: {{"branch": "branch-name"}}
- diff: {{}}
- list_issues: {{"state": "open"}}
- get_issue: {{"number": 1}}
- create_pr: {{"title": "PR title", "body": "PR description", "head": "feature-branch", "base": "main"}}
- merge_pr: {{"pr_number": 1}}
- add_comment: {{"issue_number": 1, "body": "comment text"}}

Rules:
- If write_file content is not specified exactly, set content to "__GENERATE__".
- If owner or repo cannot be inferred, use empty strings.
- Return only the JSON object, nothing else.
""".strip()

    response = llm.invoke(prompt)
    raw = response.content if hasattr(response, "content") else str(response)
    cleaned = _strip_fences(raw)
    try:
        plan = json.loads(cleaned)
    except Exception:
        plan = {}
    return plan if isinstance(plan, dict) else {}


def _generate_file_content(task: str, file_path: str, recent_log: str) -> str:
    """Use the LLM to produce file content when write_file params say __GENERATE__."""
    prompt = f"""
You are generating file content for a GitHub task.

Task: {task}
File to write: {file_path}
Recent operations context:
{recent_log}

Return ONLY the file content. No explanation, no markdown fences.
""".strip()
    response = llm.invoke(prompt)
    raw = response.content if hasattr(response, "content") else str(response)
    return normalize_llm_text(raw).strip()


def _execute_operations(
    client: GitHubClient,
    operations: list[dict],
    owner: str,
    repo: str,
    work_dir: Path,
    task: str,
) -> tuple[list[str], str, str, list[dict]]:
    """Execute *operations* in order and collect results.

    Returns:
        (log_lines, pr_url, diff_text, issues)
    """
    log_lines: list[str] = []
    pr_url = ""
    diff_text = ""
    issues: list[dict] = []
    repo_dir = work_dir / repo if repo else work_dir

    for entry in operations:
        op = str(entry.get("op", "")).strip()
        params: dict = entry.get("params", {}) or {}

        try:
            if op == "clone_repo":
                log_task_update("GitHub Agent", f"Cloning {owner}/{repo} …")
                if repo_dir.exists() and (repo_dir / ".git").exists():
                    log_lines.append(f"clone_repo: {repo_dir} already cloned; skipping.")
                else:
                    client.clone_repo_authenticated(owner, repo, repo_dir)
                    log_lines.append(f"clone_repo: cloned {owner}/{repo} → {repo_dir}")

            elif op == "pull":
                log_task_update("GitHub Agent", "Pulling latest changes …")
                out = client.pull(repo_dir)
                log_lines.append(f"pull: {out or 'up to date'}")

            elif op == "create_branch":
                branch = str(params.get("branch") or f"kendr/task-{abs(hash(task)) % 100000}")
                log_task_update("GitHub Agent", f"Creating branch {branch} …")
                try:
                    client.create_branch(repo_dir, branch)
                    log_lines.append(f"create_branch: created '{branch}'")
                except RuntimeError as exc:
                    client.switch_branch(repo_dir, branch)
                    log_lines.append(f"create_branch: switched to existing '{branch}' ({exc})")

            elif op == "switch_branch":
                branch = str(params.get("branch") or "main")
                client.switch_branch(repo_dir, branch)
                log_lines.append(f"switch_branch: checked out '{branch}'")

            elif op == "read_file":
                file_path = str(params.get("path") or "")
                if file_path:
                    content = client.read_repo_file(repo_dir, file_path)
                    log_lines.append(f"read_file: {file_path} ({len(content)} chars)")
                else:
                    log_lines.append("read_file: no path specified — skipped")

            elif op == "write_file":
                file_path = str(params.get("path") or "")
                content = str(params.get("content") or "__GENERATE__")
                if content == "__GENERATE__":
                    recent = "\n".join(log_lines[-5:])
                    content = _generate_file_content(task, file_path, recent)
                if file_path:
                    client.write_repo_file(repo_dir, file_path, content)
                    log_lines.append(f"write_file: wrote {file_path} ({len(content)} chars)")
                else:
                    log_lines.append("write_file: no path specified — skipped")

            elif op == "commit":
                message = str(params.get("message") or "kendr automated commit")
                result = client.commit(repo_dir, message)
                log_lines.append(f"commit: {result[:200] if result else 'committed'}")

            elif op == "push":
                branch = str(params.get("branch") or client.current_branch(repo_dir))
                log_task_update("GitHub Agent", f"Pushing branch '{branch}' …")
                try:
                    out = client.push_set_upstream(repo_dir, branch)
                    log_lines.append(f"push: {out[:200] if out else 'pushed'}")
                except RuntimeError as exc:
                    out = client.push(repo_dir, branch=branch)
                    log_lines.append(f"push: {out[:200] if out else str(exc)[:200]}")

            elif op == "diff":
                diff_text = client.diff(repo_dir)
                log_lines.append(f"diff: {len(diff_text)} chars captured")

            elif op == "list_issues":
                state_filter = str(params.get("state") or "open")
                issues = client.list_issues(owner, repo, state=state_filter)
                log_lines.append(f"list_issues: {len(issues)} {state_filter} issue(s) returned")

            elif op == "get_issue":
                number = int(params.get("number") or 1)
                issue = client.get_issue(owner, repo, number)
                issues = [issue]
                log_lines.append(f"get_issue #{number}: {issue.get('title', 'no title')}")

            elif op == "create_pr":
                title = str(params.get("title") or f"kendr: {task[:60]}")
                body = str(params.get("body") or "Automated PR created by kendr's github_agent.")
                head = str(params.get("head") or client.current_branch(repo_dir))
                base = str(params.get("base") or "main")
                log_task_update("GitHub Agent", f"Opening PR: {title} …")
                pr = client.create_pull_request(owner, repo, title, body, head, base)
                pr_url = pr.get("html_url", "")
                log_lines.append(f"create_pr: {pr_url or 'created (no URL returned)'}")

            elif op == "merge_pr":
                pr_number = int(params.get("pr_number") or 0)
                if pr_number:
                    result = client.merge_pull_request(owner, repo, pr_number)
                    log_lines.append(f"merge_pr #{pr_number}: {result.get('message', 'merged')}")
                else:
                    log_lines.append("merge_pr: pr_number missing — skipped")

            elif op == "add_comment":
                issue_number = int(params.get("issue_number") or 0)
                comment_body = str(params.get("body") or "")
                if issue_number and comment_body:
                    client.add_comment(owner, repo, issue_number, comment_body)
                    log_lines.append(f"add_comment: posted on issue/PR #{issue_number}")
                else:
                    log_lines.append("add_comment: missing issue_number or body — skipped")

            else:
                log_lines.append(f"unknown op '{op}' — skipped")

        except Exception as exc:
            log_lines.append(f"{op}: ERROR — {exc}")

    return log_lines, pr_url, diff_text, issues


def github_agent(state):
    """Autonomous GitHub agent: clone, edit, commit, push, open PRs, manage issues."""
    active_task, task_content, _ = begin_agent_session(state, "github_agent")
    state["github_agent_calls"] = state.get("github_agent_calls", 0) + 1

    task = (
        state.get("github_task")
        or task_content
        or state.get("current_objective")
        or state.get("user_query", "")
    ).strip()

    if not task:
        raise ValueError("github_agent requires 'github_task' or 'user_query' in state.")

    token = state.get("github_token") or os.getenv("GITHUB_TOKEN") or ""
    api_base = os.getenv("GITHUB_API_URL", "https://api.github.com")
    client = GitHubClient(token=token, api_base=api_base)

    owner = str(state.get("github_owner") or "").strip()
    repo = str(state.get("github_repo") or "").strip()
    if not owner or not repo:
        parsed = _parse_repo_slug(task)
        if parsed:
            owner, repo = parsed

    work_dir_str = (
        state.get("github_work_dir")
        or state.get("coding_working_directory")
        or tempfile.mkdtemp(prefix="kendr_github_")
    )
    work_dir = Path(str(work_dir_str))
    work_dir.mkdir(parents=True, exist_ok=True)

    log_task_update("GitHub Agent", f"Planning operations for: {task[:120]}")
    plan = _plan_operations(task)

    resolved_owner = str(plan.get("owner") or owner).strip() or owner
    resolved_repo = str(plan.get("repo") or repo).strip() or repo
    operations = plan.get("operations") or []
    plan_summary = str(plan.get("summary") or "").strip()

    if not isinstance(operations, list):
        operations = []

    log_task_update(
        "GitHub Agent",
        f"Executing {len(operations)} operation(s) on {resolved_owner}/{resolved_repo}: {plan_summary}",
    )

    log_lines, pr_url, diff_text, issues = _execute_operations(
        client=client,
        operations=operations,
        owner=resolved_owner,
        repo=resolved_repo,
        work_dir=work_dir,
        task=task,
    )

    ops_log = "\n".join(log_lines)
    issues_text = json.dumps(issues, indent=2, ensure_ascii=False) if issues else ""

    summary_lines = [f"Task: {task[:200]}"]
    if plan_summary:
        summary_lines.append(f"Plan: {plan_summary}")
    summary_lines.append(f"Operations completed: {len(log_lines)}")
    if pr_url:
        summary_lines.append(f"Pull Request: {pr_url}")
    if issues:
        summary_lines.append(f"Issues fetched: {len(issues)}")
    if diff_text:
        summary_lines.append(f"Diff captured: {len(diff_text)} chars")
    summary = "\n".join(summary_lines)

    state["github_summary"] = summary
    state["github_pr_url"] = pr_url
    state["github_diff"] = diff_text
    state["github_issues"] = issues
    state["github_operations_log"] = ops_log

    report_parts = [summary, "", "--- Operations Log ---", ops_log]
    if diff_text:
        report_parts += ["", "--- Diff ---", diff_text[:4000]]
    if issues_text:
        report_parts += ["", "--- Issues ---", issues_text[:2000]]
    write_text_file("github_agent_output.txt", "\n".join(report_parts))

    publish_agent_output(
        state,
        "github_agent",
        summary,
        "github_agent_result.txt",
        kind="text",
    )
    return state
