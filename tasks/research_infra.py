import base64
import csv
import json
import mimetypes
import os
import re
from pathlib import Path
from urllib.parse import urlencode, urljoin, urlparse
from urllib.request import Request, urlopen

from tasks.utils import llm


DEFAULT_EMBEDDING_MODEL = os.getenv("OPENAI_EMBEDDING_MODEL", "text-embedding-3-small")
DEFAULT_VISION_MODEL = os.getenv(
    "OPENAI_VISION_MODEL",
    os.getenv("OPENAI_MODEL_GENERAL", os.getenv("OPENAI_MODEL", "gpt-4o-mini")),
)
DEFAULT_QDRANT_URL = os.getenv("QDRANT_URL", "http://localhost:6333")
DEFAULT_QDRANT_COLLECTION = os.getenv("QDRANT_COLLECTION", "research_memory")
SERP_API_URL = "https://serpapi.com/search.json"
OPENALEX_API_URL = "https://api.openalex.org/works"


def strip_code_fences(text: str) -> str:
    stripped = (text or "").strip()
    if stripped.startswith("```") and stripped.endswith("```"):
        lines = stripped.splitlines()
        if len(lines) >= 2:
            return "\n".join(lines[1:-1]).strip()
    return stripped


def llm_text(prompt: str) -> str:
    response = llm.invoke(prompt)
    return response.content.strip() if hasattr(response, "content") else str(response).strip()


def llm_json(prompt: str, fallback):
    try:
        return json.loads(strip_code_fences(llm_text(prompt)))
    except Exception:
        return fallback


def get_openai_client():
    from openai import OpenAI

    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise ValueError("OPENAI_API_KEY is required for this agent.")
    return OpenAI(api_key=api_key)


def chunk_text(text: str, chunk_size: int = 1200, overlap: int = 150) -> list[str]:
    cleaned = " ".join((text or "").split())
    if not cleaned:
        return []
    chunks = []
    start = 0
    while start < len(cleaned):
        end = min(len(cleaned), start + chunk_size)
        chunks.append(cleaned[start:end])
        if end >= len(cleaned):
            break
        start = max(0, end - overlap)
    return chunks


def _regex_html_to_text(html: str) -> str:
    text = re.sub(r"(?is)<(script|style).*?>.*?</\\1>", " ", html)
    text = re.sub(r"(?s)<[^>]+>", " ", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def html_to_text(html: str) -> str:
    try:
        from bs4 import BeautifulSoup

        soup = BeautifulSoup(html, "html.parser")
        for tag in soup(["script", "style", "noscript"]):
            tag.decompose()
        return re.sub(r"\s+", " ", soup.get_text(" ")).strip()
    except Exception:
        return _regex_html_to_text(html)


def fetch_url_content(url: str, timeout: int = 20) -> dict:
    request = Request(
        url,
        headers={
            "User-Agent": os.getenv(
                "RESEARCH_USER_AGENT",
                "multi-agent-research-bot/1.0 (+https://localhost)",
            )
        },
    )
    with urlopen(request, timeout=timeout) as response:
        body = response.read()
        content_type = response.headers.get("Content-Type", "")
    text = body.decode("utf-8", errors="ignore")
    return {
        "url": url,
        "content_type": content_type,
        "text": html_to_text(text) if "html" in content_type else text,
        "raw_text": text,
    }


def extract_links(base_url: str, html: str, limit: int = 20, same_domain: bool = True) -> list[str]:
    matches = re.findall(r'href=["\\\'](.*?)["\\\']', html or "", flags=re.IGNORECASE)
    links = []
    base_domain = urlparse(base_url).netloc
    for href in matches:
        absolute = urljoin(base_url, href)
        parsed = urlparse(absolute)
        if parsed.scheme not in {"http", "https"}:
            continue
        if same_domain and parsed.netloc != base_domain:
            continue
        if absolute not in links:
            links.append(absolute)
        if len(links) >= limit:
            break
    return links


def crawl_urls(urls: list[str], max_pages: int = 5, same_domain: bool = True) -> list[dict]:
    queue = list(urls)
    visited = []
    pages = []
    while queue and len(pages) < max_pages:
        url = queue.pop(0)
        if url in visited:
            continue
        visited.append(url)
        try:
            page = fetch_url_content(url)
            pages.append(
                {
                    "url": page["url"],
                    "content_type": page["content_type"],
                    "text": page["text"][:12000],
                }
            )
            if "html" in page["content_type"]:
                queue.extend(link for link in extract_links(url, page["raw_text"], same_domain=same_domain) if link not in visited)
        except Exception as exc:
            pages.append({"url": url, "error": str(exc), "content_type": "", "text": ""})
    return pages


def serp_search(query: str, *, engine: str = "google", num: int = 5, extra_params: dict | None = None) -> dict:
    api_key = os.getenv("SERP_API_KEY")
    if not api_key:
        raise ValueError("SERP_API_KEY is required for search-based agents.")
    params = {
        "engine": engine,
        "q": query,
        "api_key": api_key,
        "num": num,
        "hl": "en",
        "gl": "us",
    }
    if extra_params:
        params.update({k: v for k, v in extra_params.items() if v is not None})
    request_url = f"{SERP_API_URL}?{urlencode(params)}"
    with urlopen(request_url, timeout=30) as response:
        return json.loads(response.read().decode("utf-8"))


def serp_scholar_search(query: str, *, num: int = 10, start: int = 0, extra_params: dict | None = None) -> dict:
    params = {"start": start}
    if extra_params:
        params.update(extra_params)
    return serp_search(query, engine="google_scholar", num=num, extra_params=params)


def serp_patent_search(
    query: str,
    *,
    num: int = 10,
    page: int = 1,
    include_scholar: bool = False,
    extra_params: dict | None = None,
) -> dict:
    params = {
        "page": page,
        "num": num,
        "patents": "true",
        "scholar": "true" if include_scholar else "false",
    }
    if extra_params:
        params.update(extra_params)
    return serp_search(query, engine="google_patents", num=num, extra_params=params)


def openalex_search(query: str, per_page: int = 10, filters: str | None = None) -> dict:
    params = {
        "search": query,
        "per-page": per_page,
    }
    if filters:
        params["filter"] = filters
    request = Request(
        f"{OPENALEX_API_URL}?{urlencode(params)}",
        headers={
            "User-Agent": os.getenv(
                "RESEARCH_USER_AGENT",
                "multi-agent-research-bot/1.0 (+https://localhost)",
            )
        },
    )
    with urlopen(request, timeout=30) as response:
        return json.loads(response.read().decode("utf-8"))


def search_result_urls(payload: dict) -> list[str]:
    urls = []
    for result in payload.get("organic_results", []):
        link = result.get("link")
        if link and link not in urls:
            urls.append(link)
    return urls


def summarize_pages(pages: list[dict], objective: str, audience: str) -> str:
    prompt = f"""
You are a web research summarizer.

Objective:
{objective}

Audience:
{audience}

Pages:
{json.dumps(pages, indent=2, ensure_ascii=False)}

Produce a concise but evidence-oriented summary. Mention important facts, conflicts, and missing pieces.
"""
    return llm_text(prompt)


def parse_document(path_str: str) -> dict:
    path = Path(path_str)
    suffix = path.suffix.lower()
    if suffix in {".txt", ".md", ".json", ".html", ".htm"}:
        text = path.read_text(encoding="utf-8", errors="ignore")
        if suffix in {".html", ".htm"}:
            text = html_to_text(text)
        return {"path": str(path), "text": text, "metadata": {"type": suffix.lstrip(".")}}
    if suffix == ".csv":
        with open(path, "r", encoding="utf-8", errors="ignore", newline="") as handle:
            reader = csv.reader(handle)
            rows = list(reader)
        text = "\n".join(", ".join(row) for row in rows[:200])
        return {"path": str(path), "text": text, "metadata": {"type": "csv", "rows": len(rows)}}
    if suffix == ".pdf":
        from pypdf import PdfReader

        reader = PdfReader(str(path))
        text = "\n".join((page.extract_text() or "") for page in reader.pages)
        return {"path": str(path), "text": text, "metadata": {"type": "pdf", "pages": len(reader.pages)}}
    if suffix == ".docx":
        from docx import Document

        doc = Document(str(path))
        text = "\n".join(paragraph.text for paragraph in doc.paragraphs)
        return {"path": str(path), "text": text, "metadata": {"type": "docx", "paragraphs": len(doc.paragraphs)}}
    raise ValueError(f"Unsupported document type for ingestion: {path}")


def parse_documents(paths: list[str]) -> list[dict]:
    documents = []
    for path in paths:
        documents.append(parse_document(path))
    return documents


def openai_ocr_image(path_str: str, instruction: str | None = None) -> dict:
    client = get_openai_client()
    path = Path(path_str)
    mime_type = mimetypes.guess_type(path.name)[0] or "image/png"
    image_b64 = base64.b64encode(path.read_bytes()).decode("ascii")
    response = client.responses.create(
        model=DEFAULT_VISION_MODEL,
        input=[
            {
                "role": "user",
                "content": [
                    {
                        "type": "input_text",
                        "text": instruction
                        or "Extract all visible text and key structured details from this image. Return plain text.",
                    },
                    {
                        "type": "input_image",
                        "image_url": f"data:{mime_type};base64,{image_b64}",
                    },
                ],
            }
        ],
    )
    output_text = getattr(response, "output_text", "") or ""
    payload = response.model_dump() if hasattr(response, "model_dump") else {"response": str(response)}
    return {"path": str(path), "text": output_text.strip(), "raw": payload}


def openai_analyze_image(path_str: str, instruction: str | None = None) -> dict:
    client = get_openai_client()
    path = Path(path_str)
    mime_type = mimetypes.guess_type(path.name)[0] or "image/png"
    image_b64 = base64.b64encode(path.read_bytes()).decode("ascii")
    response = client.responses.create(
        model=DEFAULT_VISION_MODEL,
        input=[
            {
                "role": "user",
                "content": [
                    {
                        "type": "input_text",
                        "text": instruction
                        or (
                            "Analyze this image and extract meaningful information. "
                            "Describe the scene, objects, text, layout, visual signals, "
                            "data patterns, probable context, and actionable insights if present."
                        ),
                    },
                    {
                        "type": "input_image",
                        "image_url": f"data:{mime_type};base64,{image_b64}",
                    },
                ],
            }
        ],
    )
    output_text = getattr(response, "output_text", "") or ""
    payload = response.model_dump() if hasattr(response, "model_dump") else {"response": str(response)}
    return {"path": str(path), "analysis": output_text.strip(), "raw": payload}


def get_qdrant_client():
    from qdrant_client import QdrantClient

    return QdrantClient(url=DEFAULT_QDRANT_URL)


def ensure_vector_collection(collection_name: str = DEFAULT_QDRANT_COLLECTION, vector_size: int = 1536):
    from qdrant_client.models import Distance, VectorParams

    client = get_qdrant_client()
    existing = [item.name for item in client.get_collections().collections]
    if collection_name not in existing:
        client.create_collection(
            collection_name=collection_name,
            vectors_config=VectorParams(size=vector_size, distance=Distance.COSINE),
        )
    return client


def embed_texts(texts: list[str], model: str = DEFAULT_EMBEDDING_MODEL) -> list[list[float]]:
    if not texts:
        return []
    client = get_openai_client()
    response = client.embeddings.create(model=model, input=texts)
    return [item.embedding for item in response.data]


def upsert_memory_records(records: list[dict], collection_name: str = DEFAULT_QDRANT_COLLECTION):
    from qdrant_client.models import PointStruct

    if not records:
        return {"indexed": 0, "collection": collection_name}
    vectors = embed_texts([record["text"] for record in records])
    client = ensure_vector_collection(collection_name, vector_size=len(vectors[0]) if vectors else 1536)
    points = []
    for index, record in enumerate(records):
        payload = dict(record.get("payload", {}))
        payload["text"] = record["text"]
        payload["source"] = record.get("source", "")
        points.append(
            PointStruct(
                id=record.get("id") or abs(hash(f"{record.get('source', '')}:{index}:{record['text'][:64]}")),
                vector=vectors[index],
                payload=payload,
            )
        )
    client.upsert(collection_name=collection_name, points=points)
    return {"indexed": len(points), "collection": collection_name}


def search_memory(query: str, top_k: int = 5, collection_name: str = DEFAULT_QDRANT_COLLECTION) -> list[dict]:
    client = ensure_vector_collection(collection_name)
    query_vector = embed_texts([query])[0]
    results = client.query_points(collection_name=collection_name, query=query_vector, limit=top_k)
    points = getattr(results, "points", results)
    matches = []
    for item in points:
        payload = getattr(item, "payload", {}) or {}
        matches.append(
            {
                "score": getattr(item, "score", None),
                "source": payload.get("source", ""),
                "text": payload.get("text", ""),
                "metadata": payload,
            }
        )
    return matches


def build_evidence_bundle(state: dict) -> dict:
    return {
        "user_query": state.get("user_query", ""),
        "current_objective": state.get("current_objective", ""),
        "search_summary": state.get("search_summary", ""),
        "research_result": state.get("research_result", ""),
        "web_crawl_summary": state.get("web_crawl_summary", ""),
        "document_summary": state.get("document_summary", ""),
        "ocr_summary": state.get("ocr_summary", ""),
        "entity_resolution": state.get("entity_resolution", {}),
        "knowledge_graph": state.get("knowledge_graph", {}),
        "timeline": state.get("timeline", []),
        "people_profile": state.get("people_profile", {}),
        "company_profile": state.get("company_profile", {}),
        "relationship_map": state.get("relationship_map", {}),
        "compliance_risk_report": state.get("compliance_risk_report", {}),
        "verification_report": state.get("verification_report", {}),
        "citations": state.get("citations", []),
        "structured_facts": state.get("structured_facts", []),
        "agent_history": state.get("agent_history", [])[-10:],
    }


def evidence_text(evidence: dict) -> str:
    return json.dumps(evidence, indent=2, ensure_ascii=False)
