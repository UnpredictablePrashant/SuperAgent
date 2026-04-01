import os

from openai import AsyncOpenAI


def create_openai_client_from_env() -> AsyncOpenAI | None:
    api_key = os.environ.get("OPENAI_API_KEY", "")
    return AsyncOpenAI(api_key=api_key) if api_key else None


def _collect_openai_texts(value: object, out: list[str]) -> None:
    if isinstance(value, dict):
        if value.get("type") in {"output_text", "text"} and isinstance(value.get("text"), str):
            out.append(value["text"])
        for item in value.values():
            _collect_openai_texts(item, out)
        return

    if isinstance(value, list):
        for item in value:
            _collect_openai_texts(item, out)


def extract_openai_text(response: object) -> str:
    output_text = getattr(response, "output_text", "")
    if isinstance(output_text, str) and output_text.strip():
        return output_text.strip()

    if not hasattr(response, "model_dump"):
        return ""

    payload = response.model_dump(mode="json", exclude_none=True)
    texts: list[str] = []
    _collect_openai_texts(payload, texts)
    return texts[-1].strip() if texts else ""
