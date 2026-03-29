import json
import os
import re
from collections import Counter
from urllib.parse import urlparse
from urllib.parse import urlencode
from urllib.request import urlopen

from tasks.a2a_agent_utils import begin_agent_session, publish_agent_output
from tasks.utils import OUTPUT_DIR, log_task_update, write_text_file


SERP_API_URL = "https://serpapi.com/search.json"
_NOISE_DOMAINS = {
    "facebook.com",
    "instagram.com",
    "linkedin.com",
    "youtube.com",
    "twitter.com",
    "x.com",
    "wikipedia.org",
    "amazon.com",
    "flipkart.com",
}


def _domain_from_url(url: str) -> str:
    try:
        parsed = urlparse(url or "")
    except Exception:
        return ""
    host = (parsed.netloc or "").strip().lower()
    if host.startswith("www."):
        host = host[4:]
    return host


def _extract_domains_from_text(text: str) -> list[str]:
    if not text:
        return []
    urls = re.findall(r"https?://[^\s)>\"]+", text, flags=re.IGNORECASE)
    domains: list[str] = []
    seen: set[str] = set()
    for url in urls:
        domain = _domain_from_url(url)
        if domain and domain not in seen:
            seen.add(domain)
            domains.append(domain)
    return domains


def _brand_tokens(query: str) -> list[str]:
    tokens = re.findall(r"[a-zA-Z0-9]+", (query or "").lower())
    stop_words = {
        "the",
        "and",
        "for",
        "with",
        "from",
        "into",
        "that",
        "this",
        "using",
        "about",
        "build",
        "create",
        "company",
        "brand",
        "official",
        "website",
        "page",
    }
    return [token for token in tokens if len(token) >= 3 and token not in stop_words]


def _analyze_domains(query: str, payload: dict, explicit_domains: list[str]) -> dict:
    organic_results = payload.get("organic_results", []) or []
    domain_scores: Counter[str] = Counter()
    evidence_map: dict[str, list[str]] = {}
    brand = _brand_tokens(query)

    for result in organic_results[:10]:
        link = str(result.get("link") or "").strip()
        if not link:
            continue
        domain = _domain_from_url(link)
        if not domain:
            continue
        title = str(result.get("title") or "").lower()
        snippet = str(result.get("snippet") or "").lower()
        score = 1
        for token in brand:
            if token in domain:
                score += 3
            if token in title:
                score += 1
            if token in snippet:
                score += 1
        if domain in _NOISE_DOMAINS:
            score -= 2
        if domain in explicit_domains:
            score += 4
        domain_scores[domain] += score
        evidence_map.setdefault(domain, []).append(
            f"{result.get('title') or 'Untitled result'} | {link}"
        )

    selected_domain = ""
    selected_score = 0
    if domain_scores:
        selected_domain, selected_score = domain_scores.most_common(1)[0]
    if not selected_domain and explicit_domains:
        selected_domain = explicit_domains[0]
        selected_score = 1

    confidence = "low"
    if selected_score >= 8:
        confidence = "high"
    elif selected_score >= 4:
        confidence = "medium"

    corroborating = evidence_map.get(selected_domain, [])[:5] if selected_domain else []
    if selected_domain and not corroborating and explicit_domains:
        corroborating = [f"Explicit domain provided in objective/query: {selected_domain}"]

    relevant_urls: list[str] = []
    seen_urls: set[str] = set()
    for result in organic_results[:10]:
        link = str(result.get("link") or "").strip()
        if not link or link in seen_urls:
            continue
        seen_urls.add(link)
        relevant_urls.append(link)

    crawl_patterns: list[str] = []
    if selected_domain:
        crawl_patterns.extend(
            [
                f"https://{selected_domain}/",
                f"https://{selected_domain}/*",
                f"https://{selected_domain}/about*",
                f"https://{selected_domain}/products*",
                f"https://{selected_domain}/collections*",
            ]
        )
    for url in relevant_urls[:5]:
        domain = _domain_from_url(url)
        if not domain or domain == selected_domain:
            continue
        crawl_patterns.append(f"https://{domain}/*")
    deduped_patterns: list[str] = []
    seen_patterns: set[str] = set()
    for pattern in crawl_patterns:
        if pattern in seen_patterns:
            continue
        seen_patterns.add(pattern)
        deduped_patterns.append(pattern)

    return {
        "official_domain": selected_domain,
        "official_domain_confidence": confidence,
        "official_domain_score": selected_score,
        "official_domain_evidence": corroborating,
        "relevant_urls": relevant_urls,
        "crawl_url_patterns": deduped_patterns[:12],
    }


def _format_search_summary(query: str, payload: dict, max_results: int, domain_analysis: dict) -> str:
    lines = [f"Google Search Query: {query}", ""]

    search_metadata = payload.get("search_metadata", {})
    search_parameters = payload.get("search_parameters", {})
    answer_box = payload.get("answer_box")
    knowledge_graph = payload.get("knowledge_graph")
    organic_results = payload.get("organic_results", [])
    related_questions = payload.get("related_questions", [])

    lines.append(f"Status: {search_metadata.get('status', 'unknown')}")
    lines.append(f"Engine: {search_parameters.get('engine', 'google')}")
    lines.append("")

    if answer_box:
        lines.append("Answer Box:")
        answer_title = answer_box.get("title") or answer_box.get("type") or "Direct answer"
        answer_value = (
            answer_box.get("answer")
            or answer_box.get("snippet")
            or answer_box.get("result")
            or answer_box.get("displayed_link")
            or "No direct answer text returned."
        )
        lines.append(f"- {answer_title}: {answer_value}")
        lines.append("")

    if knowledge_graph:
        lines.append("Knowledge Graph:")
        kg_title = knowledge_graph.get("title") or "Knowledge graph"
        kg_description = knowledge_graph.get("description") or "No description returned."
        lines.append(f"- {kg_title}: {kg_description}")
        lines.append("")

    lines.append("Official Domain Assessment:")
    official_domain = domain_analysis.get("official_domain") or "not confidently identified"
    confidence = domain_analysis.get("official_domain_confidence") or "low"
    lines.append(f"- Candidate: {official_domain}")
    lines.append(f"- Confidence: {confidence}")
    evidence = domain_analysis.get("official_domain_evidence") or []
    if evidence:
        lines.append("- Corroborating search evidence:")
        for item in evidence[:5]:
            lines.append(f"  - {item}")
    else:
        lines.append("- Corroborating search evidence: none")
    lines.append("")

    lines.append("Top Organic Results:")
    if not organic_results:
        lines.append("- No organic results returned.")
    else:
        for index, result in enumerate(organic_results[:max_results], start=1):
            title = result.get("title") or "Untitled result"
            link = result.get("link") or "No link returned"
            snippet = result.get("snippet") or "No snippet returned."
            lines.append(f"{index}. {title}")
            lines.append(f"   Link: {link}")
            lines.append(f"   Snippet: {snippet}")

    if related_questions:
        lines.append("")
        lines.append("Related Questions:")
        for question in related_questions[:3]:
            question_text = question.get("question") or "Unknown question"
            snippet = question.get("snippet") or "No snippet returned."
            lines.append(f"- {question_text}")
            lines.append(f"  {snippet}")

    relevant_urls = domain_analysis.get("relevant_urls") or []
    lines.append("")
    lines.append("Relevant Public URLs (for crawl/validation):")
    if relevant_urls:
        for index, url in enumerate(relevant_urls[:10], start=1):
            lines.append(f"{index}. {url}")
    else:
        lines.append("- No candidate URLs returned.")

    patterns = domain_analysis.get("crawl_url_patterns") or []
    lines.append("")
    lines.append("Recommended Crawl URL Patterns:")
    if patterns:
        for pattern in patterns:
            lines.append(f"- {pattern}")
    else:
        lines.append("- No crawl patterns derived.")

    if payload.get("error"):
        lines.append("")
        lines.append(f"API Error: {payload['error']}")

    return "\n".join(lines).strip()


def google_search_agent(state):
    active_task, task_content, _ = begin_agent_session(state, "google_search_agent")
    state["google_search_calls"] = state.get("google_search_calls", 0) + 1

    query = (
        task_content
        or state.get("current_objective")
        or state.get("search_query")
        or state.get("user_query", "")
    ).strip()
    if not query:
        raise ValueError("google_search_agent requires 'search_query' or 'user_query' in state.")

    api_key = os.getenv("SERP_API_KEY")
    if not api_key:
        raise ValueError("SERP_API_KEY is not set. Add it to .env before running google_search_agent.")

    params = {
        "engine": "google",
        "q": query,
        "api_key": api_key,
        "hl": state.get("search_hl", "en"),
        "gl": state.get("search_gl", "us"),
        "num": int(state.get("search_num", 5)),
    }

    if state.get("search_location"):
        params["location"] = state["search_location"]
    if state.get("search_start") is not None:
        params["start"] = int(state["search_start"])
    if state.get("search_safe"):
        params["safe"] = state["search_safe"]

    request_url = f"{SERP_API_URL}?{urlencode(params)}"
    call_number = state["google_search_calls"]

    log_task_update("Google Search", f"Search pass #{call_number} started.")
    log_task_update(
        "Google Search",
        "Querying SerpAPI Google Search with the configured parameters.",
        f"Query: {query}",
    )

    with urlopen(request_url, timeout=int(state.get("search_timeout", 30))) as response:
        payload = json.loads(response.read().decode("utf-8"))

    explicit_domains = _extract_domains_from_text(
        " ".join(
            [
                str(state.get("user_query") or ""),
                str(state.get("current_objective") or ""),
                str(task_content or ""),
            ]
        )
    )
    domain_analysis = _analyze_domains(query, payload, explicit_domains)
    summary = _format_search_summary(query, payload, params["num"], domain_analysis)
    summary_filename = f"google_search_output_{call_number}.txt"
    raw_filename = f"google_search_raw_{call_number}.json"
    domain_filename = f"google_search_domains_{call_number}.json"

    write_text_file(summary_filename, summary)
    write_text_file(raw_filename, json.dumps(payload, indent=2, ensure_ascii=False))
    write_text_file(domain_filename, json.dumps(domain_analysis, indent=2, ensure_ascii=False))

    state["search_query"] = query
    state["search_results"] = payload
    state["search_summary"] = summary
    state["official_domain_candidate"] = domain_analysis.get("official_domain", "")
    state["official_domain_confidence"] = domain_analysis.get("official_domain_confidence", "low")
    state["official_domain_evidence"] = domain_analysis.get("official_domain_evidence", [])
    state["search_relevant_urls"] = domain_analysis.get("relevant_urls", [])
    state["search_domain_patterns"] = domain_analysis.get("crawl_url_patterns", [])
    if state["search_relevant_urls"]:
        max_seed_urls = int(state.get("crawl_seed_from_search_max", 8) or 8)
        state["crawl_seed_urls"] = state["search_relevant_urls"][:max(1, min(max_seed_urls, 20))]
    state["draft_response"] = summary

    log_task_update(
        "Google Search",
        (
            f"Search results saved to {OUTPUT_DIR}/{summary_filename}, "
            f"{OUTPUT_DIR}/{raw_filename}, and {OUTPUT_DIR}/{domain_filename}."
        ),
        summary,
    )
    state = publish_agent_output(
        state,
        "google_search_agent",
        summary,
        f"google_search_result_{call_number}",
        recipients=["orchestrator_agent", "worker_agent"],
    )
    return state
