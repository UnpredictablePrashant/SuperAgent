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

_CRITICAL_OPS = frozenset({"clone_repo", "push", "commit", "create_pr", "merge_pr"})


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


def _resolve_target_file(task: str) -> str:
    """Ask the LLM to identify the single most relevant file path to modify for *task*.

    Returns a relative file path string (e.g. "src/utils.py") or "" if the LLM
    cannot determine one.  Used by the canonical PR planner to build a deterministic
    write_file operation without requiring the full operation planner.
    """
    prompt = f"""Given this GitHub task, identify the single most relevant file to modify.
Return ONLY the relative file path (e.g. 'src/utils.py' or 'tests/test_api.py').
If you cannot determine a specific file from the task description, return an empty string.

Task: {task}

File path:"""
    try:
        response = llm.invoke(prompt)
        raw = response.content if hasattr(response, "content") else str(response)
        path = normalize_llm_text(raw).strip().strip('"\'`').strip()
        if "\n" in path or len(path) > 200 or not path:
            return ""
        return path
    except Exception:
        return ""


_PR_INTENT_MARKERS = frozenset({"pr", "pull request", "open a pr", "submit a pr", "create a pr"})


def _wants_pr(task: str) -> bool:
    """Return True when the task text explicitly requests a pull request."""
    lower = task.lower()
    return any(m in lower for m in _PR_INTENT_MARKERS)


def _canonical_pr_plan(task: str, owner: str, repo: str) -> list[dict]:
    """Return a deterministic operation sequence for tasks that request a PR.

    Sequence: clone_repo -> create_branch -> write_file (LLM-identified path) ->
    commit -> push -> create_pr.

    If no target file can be determined, returns an empty list so the caller
    falls back to the LLM-planned or exploration paths.
    """
    target_file = _resolve_target_file(task)
    if not target_file:
        return []
    branch = f"kendr/fix-{int(__import__('time').time())}"
    return [
        {"op": "clone_repo", "params": {}},
        {"op": "create_branch", "params": {"branch": branch}},
        {"op": "write_file", "params": {"path": target_file}},
        {"op": "commit", "params": {"message": f"kendr: {task[:72]}"}},
        {"op": "push", "params": {}},
        {"op": "create_pr", "params": {"title": f"kendr: {task[:60]}", "head": branch, "base": "main"}},
    ]


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


def _generate_file_content(task: str, file_path: str, recent_log: str, existing_content: str = "") -> str:
    """Use the LLM to produce the full replacement content for *file_path*.

    Provides both the current file content (when available) and recent operation
    log so the LLM has the context needed to make a targeted, correct fix.
    """
    existing_section = (
        f"\nExisting file content (full):\n```\n{existing_content[:4000]}\n```"
        if existing_content
        else "\nExisting file content: (file does not exist yet)"
    )
    prompt = f"""
You are generating the complete replacement content for a file as part of an automated GitHub task.

Task: {task}
File: {file_path}
Recent operations context:
{recent_log}
{existing_section}

Instructions:
- Return ONLY the complete file content with the required change applied.
- Preserve all unrelated existing code/structure.
- No explanation, no markdown fences, no surrounding text.
""".strip()
    response = llm.invoke(prompt)
    raw = response.content if hasattr(response, "content") else str(response)
    return normalize_llm_text(raw).strip()


def _fallback_operations(task: str) -> list[dict]:
    """Return a minimal deterministic operation sequence based on task keywords.

    Used only when the LLM plan produces zero operations.  commit/push/create_pr
    are intentionally absent: they require prior file modifications that this
    path cannot guarantee.  PR flows are handled by the LLM planner or the
    canonical deterministic planner (_canonical_pr_plan).
    """
    lower = task.lower()
    ops: list[dict] = []

    wants_code_action = any(w in lower for w in [
        "clone", "fix", "edit", "change", "update", "write", "commit", "push", "pr", "pull request",
    ])
    wants_issue_info = any(w in lower for w in ["issue", "bug", "error", "problem", "fail", "pr", "pull request"])

    if wants_code_action:
        ops.append({"op": "clone_repo", "params": {}})
        if any(w in lower for w in ["fix", "edit", "change", "update", "write"]):
            ops.append({"op": "create_branch", "params": {"branch": "kendr/fix"}})

    if wants_issue_info:
        if not any(o["op"] == "list_issues" for o in ops):
            ops.append({"op": "list_issues", "params": {"state": "open"}})

    if not ops:
        ops.append({"op": "list_issues", "params": {"state": "open"}})

    return ops


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

        try:  # noqa: SIM105 — inner try/except distinguishes critical vs. best-effort
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
                if not file_path:
                    log_lines.append("write_file: no path specified — skipped")
                else:
                    if content == "__GENERATE__":
                        existing_content = ""
                        try:
                            existing_content = client.read_repo_file(repo_dir, file_path)
                        except Exception:
                            pass
                        recent = "\n".join(log_lines[-5:])
                        content = _generate_file_content(task, file_path, recent, existing_content)
                    client.write_repo_file(repo_dir, file_path, content)
                    log_lines.append(f"write_file: wrote {file_path} ({len(content)} chars)")

            elif op == "commit":
                message = str(params.get("message") or "kendr automated commit")
                if not client.has_uncommitted_changes(repo_dir):
                    log_lines.append("commit: working tree is clean — no changes to commit; skipping")
                else:
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
                if repo_dir.exists() and not client.is_branch_ahead_of_base(repo_dir, head, base):
                    raise RuntimeError(
                        f"GitHub operation 'create_pr' aborted: branch '{head}' has no commits "
                        f"ahead of '{base}'. Commit and push changes first, or verify the correct "
                        "head/base branch names."
                    )
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
            if op in _CRITICAL_OPS:
                raise RuntimeError(f"GitHub operation '{op}' failed: {exc}") from exc
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

    if not token:
        log_task_update(
            "GitHub Agent",
            "WARNING: GITHUB_TOKEN is not set. Clone, push, and PR operations against "
            "private repos will fail. Set GITHUB_TOKEN via `kendr setup set github`.",
        )

    client = GitHubClient(token=token)

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

    if not operations:
        if not (resolved_owner and resolved_repo):
            raise ValueError(
                "github_agent: LLM plan produced no operations and no owner/repo could be identified. "
                "Provide 'github_owner'/'github_repo' in state or include 'owner/repo' in the task."
            )
        if _wants_pr(task):
            canon = _canonical_pr_plan(task, resolved_owner, resolved_repo)
            if canon:
                log_task_update("GitHub Agent", f"Using canonical fix+PR plan ({len(canon)} ops).")
                operations = canon
            else:
                log_task_update(
                    "GitHub Agent",
                    "Could not identify target file for PR; using exploration fallback.",
                )
                operations = _fallback_operations(task)
        else:
            operations = _fallback_operations(task)
            log_task_update(
                "GitHub Agent",
                f"LLM plan empty; using exploration fallback ({len(operations)} op(s)).",
            )

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

    if _wants_pr(task) and not pr_url:
        planned_has_pr = any(
            str(entry.get("op", "")) == "create_pr" for entry in operations
        )
        if planned_has_pr:
            raise RuntimeError(
                "github_agent: task requested a pull request but no PR URL was produced. "
                "Check operation log for failures (e.g. 'no commits ahead of base', auth errors, "
                "or network issues). Operations attempted: " + "; ".join(log_lines[:10])
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

    result = {
        "schema_version": "github_agent/v1",
        "task": task[:400],
        "plan_summary": plan_summary,
        "repo": f"{resolved_owner}/{resolved_repo}",
        "operations_executed": len(log_lines),
        "operations_log": log_lines,
        "pr_url": pr_url or None,
        "diff_excerpt": diff_text[:4000] if diff_text else None,
        "issues": issues if issues else None,
        "summary": summary,
    }
    result_json = json.dumps(result, indent=2, ensure_ascii=False)
    write_text_file("github_agent_result.json", result_json)

    publish_agent_output(
        state,
        "github_agent",
        summary,
        "github_agent_result.json",
        kind="json",
    )
    return state
