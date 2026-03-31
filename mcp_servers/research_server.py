import json
import os

from fastmcp import FastMCP

from tasks.research_infra import (
    arxiv_search,
    crawl_urls,
    llm_json,
    llm_text,
    openai_ocr_image,
    parse_document,
    reddit_search,
    search_result_urls,
    serp_search,
    summarize_pages,
)


mcp = FastMCP("super-agent-research")


@mcp.tool
def web_search(query: str, num_results: int = 5) -> dict:
    payload = serp_search(query, num=num_results)
    return {
        "query": query,
        "urls": search_result_urls(payload),
        "payload": payload,
    }


@mcp.tool
def news_search(query: str, num_results: int = 10) -> dict:
    payload = serp_search(query, num=num_results, extra_params={"tbm": "nws"})
    return {
        "query": query,
        "articles": payload.get("news_results", []) or payload.get("organic_results", []),
    }


@mcp.tool
def crawl_site(url: str, max_pages: int = 4, same_domain: bool = True) -> dict:
    pages = crawl_urls([url], max_pages=max_pages, same_domain=same_domain)
    summary = summarize_pages(pages, f"Crawl {url}", "MCP client")
    return {"pages": pages, "summary": summary}


@mcp.tool
def ingest_document(path: str) -> dict:
    document = parse_document(path)
    summary = llm_text(
        f"Summarize this document for research use.\n\nDocument:\n{json.dumps(document, indent=2, ensure_ascii=False)[:22000]}"
    )
    return {"document": document, "summary": summary}


@mcp.tool
def ocr_image(path: str, instruction: str = "") -> dict:
    return openai_ocr_image(path, instruction or None)


@mcp.tool
def arxiv_papers(query: str, max_results: int = 10, sort_by: str = "relevance") -> dict:
    papers = arxiv_search(query, max_results=max_results, sort_by=sort_by)
    return {"query": query, "count": len(papers), "papers": papers}


@mcp.tool
def reddit_posts(query: str, subreddit: str = "", sort: str = "relevance", limit: int = 10) -> dict:
    posts = reddit_search(query, subreddit=subreddit, sort=sort, limit=limit)
    return {"query": query, "subreddit": subreddit or "all", "count": len(posts), "posts": posts}


@mcp.tool
def entity_brief(query: str, evidence_json: str = "") -> dict:
    evidence = evidence_json or "{}"
    return llm_json(
        f"""
You are an entity research helper.

Target:
{query}

Evidence JSON:
{evidence}

Return valid JSON:
{{
  "name": "entity name",
  "entity_type": "person|company|organization|group|unknown",
  "summary": "brief summary",
  "aliases": ["alias"],
  "risks": ["risk or uncertainty"]
}}
""",
        {
            "name": query,
            "entity_type": "unknown",
            "summary": "No summary generated.",
            "aliases": [],
            "risks": [],
        },
    )


if __name__ == "__main__":
    host = os.getenv("MCP_HOST", "0.0.0.0")
    port = int(os.getenv("MCP_PORT", "8001"))
    transport = os.getenv("MCP_TRANSPORT", "http")
    mcp.run(transport=transport, host=host, port=port)
