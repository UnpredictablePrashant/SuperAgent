from __future__ import annotations

import concurrent.futures
import json
import os
from typing import Any

from tasks.a2a_agent_utils import begin_agent_session, publish_agent_output
from tasks.research_infra import (
    arxiv_search,
    llm_text,
    openalex_search,
    reddit_search,
    serp_patent_search,
    serp_scholar_search,
    serp_search,
)
from tasks.utils import OUTPUT_DIR, log_task_update, write_text_file


AGENT_METADATA = {
    "research_pipeline_agent": {
        "description": (
            "Multi-source research pipeline that fetches evidence from web, arXiv, Reddit, "
            "Google Scholar, patents, and OpenAlex. Assembles a combined evidence report "
            "and optionally pre-populates the long-document evidence bank."
        ),
        "skills": ["research", "pipeline", "arxiv", "reddit", "scholar", "patents", "multi-source"],
        "input_keys": [
            "research_sources",
            "pipeline_arxiv_max",
            "pipeline_reddit_limit",
            "pipeline_web_num",
            "pipeline_scholar_num",
            "pipeline_patents_num",
            "pipeline_openalex_per_page",
            "long_document_collect_sources_first",
        ],
        "output_keys": [
            "research_pipeline_report",
            "research_pipeline_sources_fetched",
            "research_pipeline_source_urls",
            "research_pipeline_errors",
            "long_document_sources_collected",
            "long_document_evidence_bank_path",
        ],
        "requirements": [],
    }
}

_VALID_SOURCES = {"web", "arxiv", "reddit", "scholar", "patents", "openalex"}
_DEFAULT_SOURCES = ["web"]

# Source aliases: map user-friendly names to canonical source IDs
_SOURCE_ALIASES: dict[str, str] = {
    "papers": "arxiv",
    "arxiv": "arxiv",
    "academic": "arxiv",
    "reddit": "reddit",
    "social": "reddit",
    "web": "web",
    "google": "web",
    "search": "web",
    "scholar": "scholar",
    "google_scholar": "scholar",
    "patents": "patents",
    "patent": "patents",
    "google_patents": "patents",
    "openalex": "openalex",
    # "local" is a valid alias but handled separately (local file scan, not a remote source)
    "local": "local",
}


def _parse_sources(raw: object) -> list[str]:
    """Parse a raw source list or comma-separated string and normalize to canonical names."""
    if isinstance(raw, list):
        tokens = [str(s).strip().lower() for s in raw if str(s).strip()]
    elif isinstance(raw, str) and raw.strip():
        tokens = [s.strip().lower() for s in raw.split(",") if s.strip()]
    else:
        return list(_DEFAULT_SOURCES)

    result: list[str] = []
    for t in tokens:
        canonical = _SOURCE_ALIASES.get(t, t)
        if canonical not in result:
            result.append(canonical)
    return result or list(_DEFAULT_SOURCES)


def _format_arxiv_results(entries: list[dict]) -> str:
    if not entries:
        return "No arXiv results returned."
    lines = [f"### arXiv Results ({len(entries)} papers)", ""]
    for index, entry in enumerate(entries, start=1):
        authors = ", ".join(entry.get("authors", [])[:3])
        if len(entry.get("authors", [])) > 3:
            authors += " et al."
        categories = ", ".join(entry.get("categories", [])[:3])
        lines.append(f"{index}. **{entry.get('title', 'Untitled')}**")
        lines.append(f"   Authors: {authors or 'Unknown'}")
        lines.append(f"   Published: {entry.get('published', 'Unknown')}")
        lines.append(f"   Categories: {categories or 'Unknown'}")
        lines.append(f"   URL: {entry.get('url', '')}")
        summary = str(entry.get("summary", "")).strip()
        if summary:
            lines.append(f"   Abstract: {summary[:300]}...")
        lines.append("")
    return "\n".join(lines).strip()


def _format_reddit_results(posts: list[dict]) -> str:
    if not posts:
        return "No Reddit results returned."
    lines = [f"### Reddit Results ({len(posts)} posts)", ""]
    for index, post in enumerate(posts, start=1):
        lines.append(f"{index}. **{post.get('title', 'Untitled')}**")
        lines.append(f"   Subreddit: r/{post.get('subreddit', 'unknown')}")
        lines.append(f"   Score: {post.get('score', 0)} | Comments: {post.get('num_comments', 0)}")
        lines.append(f"   URL: {post.get('url', '')}")
        text = str(post.get("text", "")).strip()
        if text:
            lines.append(f"   Text: {text[:300]}...")
        lines.append("")
    return "\n".join(lines).strip()


def _format_web_results(payload: dict, query: str) -> str:
    organic = payload.get("organic_results", []) or []
    if not organic:
        return "No web search results returned."
    lines = [f"### Web Search Results for: {query}", ""]
    for index, result in enumerate(organic[:10], start=1):
        title = str(result.get("title") or "Untitled")
        link = str(result.get("link") or "")
        snippet = str(result.get("snippet") or "No snippet.")
        lines.append(f"{index}. **{title}**")
        lines.append(f"   URL: {link}")
        lines.append(f"   Snippet: {snippet}")
        lines.append("")
    return "\n".join(lines).strip()


def _format_scholar_results(payload: dict, query: str) -> str:
    organic = payload.get("organic_results", []) or []
    if not organic:
        return "No Google Scholar results returned."
    lines = [f"### Google Scholar Results for: {query}", ""]
    for index, result in enumerate(organic[:10], start=1):
        title = str(result.get("title") or "Untitled")
        link = str(result.get("link") or "")
        snippet = str(result.get("snippet") or "No snippet.")
        publication = str(result.get("publication_info", {}).get("summary", "") or "")
        lines.append(f"{index}. **{title}**")
        lines.append(f"   URL: {link}")
        if publication:
            lines.append(f"   Publication: {publication}")
        lines.append(f"   Snippet: {snippet}")
        lines.append("")
    return "\n".join(lines).strip()


def _format_patents_results(payload: dict, query: str) -> str:
    organic = payload.get("organic_results", []) or []
    if not organic:
        return "No patent results returned."
    lines = [f"### Patent Search Results for: {query}", ""]
    for index, result in enumerate(organic[:10], start=1):
        title = str(result.get("title") or "Untitled")
        link = str(result.get("link") or "")
        snippet = str(result.get("snippet") or "No snippet.")
        patent_id = str(result.get("patent_id") or "")
        lines.append(f"{index}. **{title}**")
        if patent_id:
            lines.append(f"   Patent ID: {patent_id}")
        lines.append(f"   URL: {link}")
        lines.append(f"   Snippet: {snippet}")
        lines.append("")
    return "\n".join(lines).strip()


def _format_openalex_results(payload: dict, query: str) -> str:
    works = payload.get("results", []) or []
    if not works:
        return "No OpenAlex results returned."
    lines = [f"### OpenAlex Academic Results for: {query}", ""]
    for index, work in enumerate(works[:10], start=1):
        title = str(work.get("title") or "Untitled")
        doi = str(work.get("doi") or "")
        year = work.get("publication_year") or "Unknown"
        cited_by = work.get("cited_by_count") or 0
        authors = [
            str(a.get("author", {}).get("display_name") or "")
            for a in (work.get("authorships") or [])[:3]
        ]
        author_str = ", ".join(a for a in authors if a) or "Unknown"
        lines.append(f"{index}. **{title}**")
        lines.append(f"   Authors: {author_str}")
        lines.append(f"   Year: {year} | Citations: {cited_by}")
        if doi:
            lines.append(f"   DOI: {doi}")
        lines.append("")
    return "\n".join(lines).strip()


def _fetch_one_source(
    source: str,
    query: str,
    *,
    serp_key_available: bool,
    arxiv_max: int,
    reddit_limit: int,
    web_num: int,
    scholar_num: int,
    patents_num: int,
    openalex_per_page: int,
) -> tuple[str, Any, str | None]:
    """Fetch results from a single source. Returns (source, result_or_None, error_or_None)."""
    try:
        if source == "local":
            return (source, None, "local source requires --local-drive-paths; skipping remote fetch.")
        if source == "arxiv":
            log_task_update("Research Pipeline", f"[parallel] Fetching arXiv papers for: {query}")
            return (source, arxiv_search(query, max_results=arxiv_max), None)
        if source == "reddit":
            log_task_update("Research Pipeline", f"[parallel] Fetching Reddit posts for: {query}")
            return (source, reddit_search(query, limit=reddit_limit), None)
        if source == "openalex":
            log_task_update("Research Pipeline", f"[parallel] Fetching OpenAlex academic works for: {query}")
            return (source, openalex_search(query, per_page=openalex_per_page), None)
        if source in ("web", "scholar", "patents"):
            if not serp_key_available:
                return (source, None, f"SERP_API_KEY not set — {source} skipped.")
            if source == "web":
                log_task_update("Research Pipeline", f"[parallel] Fetching web search results for: {query}")
                return (source, serp_search(query, num=web_num), None)
            if source == "scholar":
                log_task_update("Research Pipeline", f"[parallel] Fetching Google Scholar results for: {query}")
                return (source, serp_scholar_search(query, num=scholar_num), None)
            if source == "patents":
                log_task_update("Research Pipeline", f"[parallel] Fetching patent results for: {query}")
                return (source, serp_patent_search(query, num=patents_num), None)
        return (source, None, f"Unknown source '{source}' — skipping.")
    except Exception as exc:
        return (source, None, str(exc))


def _collect_pipeline_sources(
    query: str,
    sources: list[str],
    *,
    arxiv_max: int = 10,
    reddit_limit: int = 10,
    web_num: int = 10,
    scholar_num: int = 10,
    patents_num: int = 10,
    openalex_per_page: int = 10,
) -> dict:
    """Fan-out source fetches in parallel using a thread pool, then collect results."""
    serp_key_available = bool(os.getenv("SERP_API_KEY", "").strip())
    results: dict[str, Any] = {}
    errors: dict[str, str] = {}

    # Filter out sources not in _VALID_SOURCES plus 'local'
    valid = [s for s in sources if s in _VALID_SOURCES or s == "local"]
    skipped = [s for s in sources if s not in _VALID_SOURCES and s != "local"]
    for s in skipped:
        log_task_update("Research Pipeline", f"Ignoring unrecognized source '{s}'.")

    with concurrent.futures.ThreadPoolExecutor(max_workers=min(len(valid) or 1, 6)) as pool:
        futures = {
            pool.submit(
                _fetch_one_source,
                source,
                query,
                serp_key_available=serp_key_available,
                arxiv_max=arxiv_max,
                reddit_limit=reddit_limit,
                web_num=web_num,
                scholar_num=scholar_num,
                patents_num=patents_num,
                openalex_per_page=openalex_per_page,
            ): source
            for source in valid
        }
        for future in concurrent.futures.as_completed(futures):
            src, data, err = future.result()
            if err:
                errors[src] = err
                log_task_update("Research Pipeline", f"Source '{src}' error: {err}")
            elif data is not None:
                results[src] = data

    return {"results": results, "errors": errors}


def _build_evidence_report(
    query: str,
    sources: list[str],
    collected: dict,
) -> str:
    results = collected.get("results", {})
    errors = collected.get("errors", {})
    lines = [
        f"# Multi-Source Research Report",
        f"",
        f"**Query:** {query}",
        f"**Sources requested:** {', '.join(sources)}",
        f"**Sources fetched:** {', '.join(results.keys()) or 'none'}",
        f"",
    ]
    if errors:
        lines.append("## Source Errors")
        lines.append("")
        for source, err in errors.items():
            lines.append(f"- **{source}**: {err}")
        lines.append("")

    if "arxiv" in results:
        lines.append(_format_arxiv_results(results["arxiv"]))
        lines.append("")
    if "openalex" in results:
        lines.append(_format_openalex_results(results["openalex"], query))
        lines.append("")
    if "scholar" in results:
        lines.append(_format_scholar_results(results["scholar"], query))
        lines.append("")
    if "web" in results:
        lines.append(_format_web_results(results["web"], query))
        lines.append("")
    if "reddit" in results:
        lines.append(_format_reddit_results(results["reddit"]))
        lines.append("")
    if "patents" in results:
        lines.append(_format_patents_results(results["patents"], query))
        lines.append("")

    return "\n".join(lines).strip() + "\n"


# Maximum characters of raw evidence text fed to the LLM synthesis prompt
_SYNTHESIS_MAX_CHARS = int(os.getenv("PIPELINE_SYNTHESIS_MAX_CHARS", "12000"))


def _synthesize_evidence(query: str, raw_report: str) -> str:
    """
    Run a structured LLM synthesis pass over the raw multi-source evidence report.

    Produces a deduplicated, ranked, cross-source synthesis with:
    - Key findings with provenance citations per source
    - Agreements / convergences across sources
    - Contradictions / gaps
    - Ranked top items by relevance and credibility
    Returns empty string if LLM is unavailable (caller falls back to raw_report).
    """
    truncated = raw_report[:_SYNTHESIS_MAX_CHARS]
    prompt = f"""You are a research synthesis expert.

Below is a multi-source evidence report collected for the query:
"{query}"

Evidence report:
---
{truncated}
---

Your task:
1. Write a concise **Synthesis Summary** (3-5 paragraphs) that:
   - Integrates the key findings across all sources
   - Identifies convergences (where multiple sources agree) and marks them as high-confidence
   - Flags contradictions or data gaps between sources
   - Cites provenance (source name) for every specific claim
2. Write a **Ranked Key Evidence** section (numbered list, up to 15 items):
   - Each item: one specific finding, with [Source] tag, ranked by relevance + credibility
3. Write a **Gaps & Recommended Next Steps** section (bullet list):
   - What remains unclear, what sources to consult next

Format your response in clean Markdown with the three sections clearly labeled.
Do NOT repeat raw search result text verbatim — synthesize and paraphrase.
"""
    try:
        synthesis = llm_text(prompt)
        return synthesis.strip()
    except Exception as exc:
        log_task_update("Research Pipeline", f"LLM synthesis failed (falling back to raw report): {exc}")
        return ""


def _extract_source_urls(collected: dict) -> list[dict]:
    results = collected.get("results", {})
    entries = []
    seen: set[str] = set()

    def _add(url: str, label: str, source: str) -> None:
        if not url or url in seen:
            return
        seen.add(url)
        entries.append({"url": url, "label": label, "source": source})

    arxiv = results.get("arxiv", []) or []
    for item in arxiv:
        _add(str(item.get("url", "")), str(item.get("title", "arXiv paper")), "arxiv")

    reddit = results.get("reddit", []) or []
    for item in reddit:
        _add(str(item.get("url", "")), str(item.get("title", "Reddit post")), "reddit")

    for src in ("web", "scholar", "patents"):
        payload = results.get(src, {}) or {}
        for result in payload.get("organic_results", []) or []:
            _add(str(result.get("link", "")), str(result.get("title", src + " result")), src)

    openalex = results.get("openalex", {}) or {}
    for work in openalex.get("results", []) or []:
        doi = str(work.get("doi") or "")
        title = str(work.get("title") or "OpenAlex work")
        if doi:
            _add(doi, title, "openalex")

    return entries


def research_pipeline_agent(state: dict) -> dict:
    active_task, task_content, _ = begin_agent_session(state, "research_pipeline_agent")
    state["research_pipeline_calls"] = state.get("research_pipeline_calls", 0) + 1
    call_number = state["research_pipeline_calls"]

    query = str(
        state.get("current_objective")
        or task_content
        or state.get("user_query", "")
    ).strip()
    if not query:
        raise ValueError("research_pipeline_agent requires a non-empty query or objective.")

    raw_sources = state.get("research_sources") or state.get("pipeline_sources") or _DEFAULT_SOURCES
    # _parse_sources normalizes aliases (e.g. "papers" → "arxiv") and deduplicates
    sources = _parse_sources(raw_sources)
    # After alias expansion, filter to valid remote sources (+ "local" handled by _fetch_one_source)
    valid_and_local = _VALID_SOURCES | {"local"}
    unknown = [s for s in sources if s not in valid_and_local]
    if unknown:
        log_task_update("Research Pipeline", f"Ignoring unrecognized sources after alias expansion: {', '.join(unknown)}")
        sources = [s for s in sources if s in valid_and_local]
    if not sources:
        sources = list(_DEFAULT_SOURCES)

    arxiv_max = int(state.get("pipeline_arxiv_max", 10) or 10)
    reddit_limit = int(state.get("pipeline_reddit_limit", 10) or 10)
    web_num = int(state.get("pipeline_web_num", 10) or 10)
    scholar_num = int(state.get("pipeline_scholar_num", 10) or 10)
    patents_num = int(state.get("pipeline_patents_num", 10) or 10)
    openalex_per_page = int(state.get("pipeline_openalex_per_page", 10) or 10)

    log_task_update(
        "Research Pipeline",
        f"Pass #{call_number} — sources={sources}, query={query[:100]}",
    )

    collected = _collect_pipeline_sources(
        query,
        sources,
        arxiv_max=arxiv_max,
        reddit_limit=reddit_limit,
        web_num=web_num,
        scholar_num=scholar_num,
        patents_num=patents_num,
        openalex_per_page=openalex_per_page,
    )

    raw_report_md = _build_evidence_report(query, sources, collected)
    source_urls = _extract_source_urls(collected)

    # LLM synthesis pass — produces ranked, deduplicated, cross-source synthesis
    fetched_sources = list(collected.get("results", {}).keys())
    skip_synthesis = bool(state.get("pipeline_skip_synthesis", False))
    synthesis_md = ""
    if not skip_synthesis and fetched_sources:
        log_task_update("Research Pipeline", "Running LLM synthesis and reconciliation pass...")
        synthesis_md = _synthesize_evidence(query, raw_report_md)
        if synthesis_md:
            log_task_update("Research Pipeline", "Synthesis complete.")

    # Final report = synthesis (if available) + raw evidence appendix
    if synthesis_md:
        report_md = (
            f"# Research Synthesis: {query}\n\n"
            f"{synthesis_md}\n\n"
            f"---\n\n"
            f"## Appendix: Raw Evidence Collected\n\n"
            f"{raw_report_md}"
        )
    else:
        report_md = raw_report_md

    report_filename = f"research_pipeline_report_{call_number}.md"
    raw_filename = f"research_pipeline_raw_{call_number}.json"
    write_text_file(report_filename, report_md)
    write_text_file(raw_filename, json.dumps(collected, indent=2, ensure_ascii=False, default=str))

    state["research_pipeline_report"] = report_md
    state["research_pipeline_raw_report"] = raw_report_md
    state["research_pipeline_synthesis"] = synthesis_md
    state["research_pipeline_sources_fetched"] = fetched_sources
    state["research_pipeline_source_urls"] = source_urls
    state["research_pipeline_errors"] = collected.get("errors", {})
    state["draft_response"] = report_md

    if bool(state.get("long_document_collect_sources_first", False)) and not state.get("long_document_sources_collected"):
        evidence_bank_filename = f"research_pipeline_evidence_bank_{call_number}.md"
        write_text_file(evidence_bank_filename, report_md)
        state["long_document_sources_collected"] = True
        state["long_document_evidence_bank_path"] = f"{OUTPUT_DIR}/{evidence_bank_filename}"
        state["long_document_evidence_bank_excerpt"] = report_md[:18000]
        state["long_document_evidence_sources"] = [
            {"id": f"P{i + 1}", "url": item["url"], "label": item["label"]}
            for i, item in enumerate(source_urls[:60])
        ]
        log_task_update(
            "Research Pipeline",
            f"Evidence bank written to {OUTPUT_DIR}/{evidence_bank_filename} ({len(source_urls)} source URLs).",
        )

    errors = collected.get("errors", {})
    if errors:
        log_task_update(
            "Research Pipeline",
            f"Fetch errors for sources: {', '.join(f'{k}: {v[:80]}' for k, v in errors.items())}",
        )

    fetched = list(collected.get("results", {}).keys())
    log_task_update(
        "Research Pipeline",
        (
            f"Pipeline complete. Fetched from: {', '.join(fetched) or 'none'}. "
            f"Report saved to {OUTPUT_DIR}/{report_filename}."
        ),
        report_md[:500],
    )

    state = publish_agent_output(
        state,
        "research_pipeline_agent",
        report_md,
        f"research_pipeline_result_{call_number}",
        recipients=["orchestrator_agent", "long_document_agent"],
    )
    return state
