from __future__ import annotations

import math
import re
from collections import Counter
from difflib import SequenceMatcher
from typing import Any


_CITATION_RE = re.compile(r"\[[A-Z]\d+\]")
_CODE_FENCE_RE = re.compile(r"```.*?```", re.S)
_LINK_RE = re.compile(r"\[([^\]]+)\]\(([^)]+)\)")
_IMAGE_RE = re.compile(r"!\[([^\]]*)\]\(([^)]+)\)")
_TRANSITION_PHRASES = (
    "additionally",
    "furthermore",
    "moreover",
    "in addition",
    "notably",
    "overall",
    "in conclusion",
    "in summary",
    "however",
    "therefore",
    "consequently",
    "meanwhile",
)
_STOPWORDS = {
    "a", "an", "the", "and", "or", "but", "if", "then", "else", "when", "while", "for", "to", "of", "in", "on",
    "at", "by", "with", "from", "into", "over", "under", "between", "through", "during", "before", "after", "about",
    "against", "among", "is", "are", "was", "were", "be", "been", "being", "it", "its", "this", "that", "these",
    "those", "as", "than", "such", "can", "could", "should", "would", "may", "might", "will", "shall", "do", "does",
    "did", "doing", "have", "has", "had", "having", "their", "there", "which", "who", "whom", "whose", "what", "why",
    "how", "also", "very", "more", "most", "less", "least", "not", "no", "nor", "so", "too", "up", "down", "out",
    "off", "again", "further", "once", "all", "any", "both", "each", "few", "other", "some", "own", "same",
}


def _clamp(value: float, minimum: float = 0.0, maximum: float = 100.0) -> float:
    return max(minimum, min(maximum, value))


def _tokenize_words(text: str) -> list[str]:
    return re.findall(r"[a-z0-9]+", str(text or "").lower())


def _strip_markdown(text: str) -> str:
    raw = str(text or "")
    raw = _CODE_FENCE_RE.sub(" ", raw)
    raw = _IMAGE_RE.sub(r"\1", raw)
    raw = _LINK_RE.sub(r"\1", raw)
    raw = re.sub(r"`([^`]*)`", r"\1", raw)
    raw = re.sub(r"^#{1,6}\s*", "", raw, flags=re.M)
    raw = re.sub(r"^\s*[-*+]\s+", "", raw, flags=re.M)
    raw = re.sub(r"^\s*\d+\.\s+", "", raw, flags=re.M)
    raw = raw.replace("|", " ")
    raw = _CITATION_RE.sub(" ", raw)
    raw = re.sub(r"\s+", " ", raw)
    return raw.strip()


def _section_text_blocks(text: str) -> list[str]:
    blocks: list[str] = []
    for part in re.split(r"\n\s*\n", str(text or "").strip()):
        cleaned = _strip_markdown(part)
        if cleaned:
            blocks.append(cleaned)
    return blocks


def _content_tokens(tokens: list[str]) -> list[str]:
    return [token for token in tokens if token not in _STOPWORDS]


def _word_shingles(tokens: list[str], n: int = 5) -> set[tuple[str, ...]]:
    if len(tokens) < n:
        return set()
    return {tuple(tokens[index : index + n]) for index in range(0, len(tokens) - n + 1)}


def _fingerprints(tokens: list[str], *, n: int = 6, window: int = 4) -> set[int]:
    if len(tokens) < n:
        return set()
    hashes = [hash(tuple(tokens[index : index + n])) for index in range(0, len(tokens) - n + 1)]
    if len(hashes) <= window:
        return set(hashes)
    selected: set[int] = set()
    for start in range(0, len(hashes) - window + 1):
        selected.add(min(hashes[start : start + window]))
    return selected


def _set_ratio(left: set[Any], right: set[Any]) -> float:
    if not left or not right:
        return 0.0
    return len(left & right) / max(1, len(left))


def _sequence_ratio(left: str, right: str) -> float:
    if not left or not right:
        return 0.0
    return SequenceMatcher(None, left, right).ratio()


def _longest_common_run(left_tokens: list[str], right_tokens: list[str]) -> tuple[int, list[str]]:
    if not left_tokens or not right_tokens:
        return 0, []
    positions: dict[str, list[int]] = {}
    for index, token in enumerate(right_tokens):
        positions.setdefault(token, []).append(index)
    best = 0
    best_end = -1
    previous: dict[int, int] = {}
    for left_index, token in enumerate(left_tokens):
        current: dict[int, int] = {}
        for right_index in positions.get(token, []):
            current[right_index] = previous.get(right_index - 1, 0) + 1
            if current[right_index] > best:
                best = current[right_index]
                best_end = left_index
        previous = current
    if best <= 0 or best_end < 0:
        return 0, []
    start = best_end - best + 1
    return best, left_tokens[start : best_end + 1]


def _sentence_split(text: str) -> list[str]:
    plain = _strip_markdown(text)
    if not plain:
        return []
    pieces = re.split(r"(?<=[.!?])\s+(?=[A-Z0-9])", plain)
    return [piece.strip() for piece in pieces if len(_tokenize_words(piece)) >= 5]


def _passage_summary(text: str, *, max_chars: int = 240) -> str:
    plain = _strip_markdown(text)
    if len(plain) <= max_chars:
        return plain
    return plain[: max_chars - 1].rstrip() + "…"


def _match_severity(similarity: float) -> str:
    if similarity >= 0.82:
        return "high"
    if similarity >= 0.62:
        return "medium"
    return "low"


def _match_type(*, citation_present: bool, source_kind: str, sequence_ratio: float, longest_run_ratio: float, shingle_ratio: float) -> str:
    if source_kind == "report_section":
        return "internal_duplication"
    if citation_present and max(sequence_ratio, longest_run_ratio, shingle_ratio) >= 0.55:
        return "attributed_overlap"
    if sequence_ratio >= 0.82 or longest_run_ratio >= 0.72:
        return "near_verbatim"
    if shingle_ratio >= 0.44 or longest_run_ratio >= 0.52:
        return "mosaic"
    return "paraphrase_heavy"


def _recommendation(match_type: str) -> str:
    if match_type == "internal_duplication":
        return "Consolidate repeated analysis across sections and keep the strongest version once."
    if match_type == "attributed_overlap":
        return "The overlap is cited, but the wording is still too close to the source. Paraphrase more aggressively or use a short quotation."
    if match_type == "near_verbatim":
        return "Rewrite this passage in original language and keep a citation to the underlying source."
    if match_type == "mosaic":
        return "Reduce patchwriting by synthesizing multiple sources into one original passage."
    return "Increase original synthesis and tighten attribution."


def _build_source_blocks(source_texts: list[dict]) -> list[dict[str, Any]]:
    blocks: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in source_texts or []:
        label = str(item.get("label", "")).strip() or "source"
        url = str(item.get("url", "")).strip()
        source_kind = str(item.get("kind", "")).strip() or "external_source"
        for passage_index, passage in enumerate(_section_text_blocks(item.get("text", "")), start=1):
            tokens = _tokenize_words(passage)
            if len(tokens) < 12:
                continue
            normalized = " ".join(tokens)
            if normalized in seen:
                continue
            seen.add(normalized)
            content_tokens = _content_tokens(tokens)
            blocks.append(
                {
                    "label": label,
                    "url": url,
                    "kind": source_kind,
                    "passage_index": passage_index,
                    "text": passage,
                    "tokens": tokens,
                    "content_tokens": set(content_tokens),
                    "shingles": _word_shingles(tokens, 5),
                    "fingerprints": _fingerprints(tokens),
                }
            )
    return blocks


def _evaluate_match(report_passage: dict[str, Any], source_block: dict[str, Any]) -> dict[str, Any] | None:
    overlap = _set_ratio(report_passage["content_tokens"], source_block["content_tokens"])
    if overlap < 0.18:
        return None
    sequence_ratio = _sequence_ratio(report_passage["normalized"], source_block["text"])
    longest_run, run_tokens = _longest_common_run(report_passage["tokens"], source_block["tokens"])
    longest_run_ratio = longest_run / max(1, len(report_passage["tokens"]))
    shingle_ratio = _set_ratio(report_passage["shingles"], source_block["shingles"])
    fingerprint_ratio = _set_ratio(report_passage["fingerprints"], source_block["fingerprints"])
    composite = (
        0.34 * sequence_ratio
        + 0.31 * longest_run_ratio
        + 0.23 * shingle_ratio
        + 0.07 * fingerprint_ratio
        + 0.05 * overlap
    )
    if max(sequence_ratio, longest_run_ratio, shingle_ratio, composite) < 0.42:
        return None
    match_type = _match_type(
        citation_present=report_passage["citation_present"],
        source_kind=source_block["kind"],
        sequence_ratio=sequence_ratio,
        longest_run_ratio=longest_run_ratio,
        shingle_ratio=shingle_ratio,
    )
    penalty_factor = 0.5 if match_type in {"attributed_overlap", "internal_duplication"} else 1.0
    similarity = max(sequence_ratio, longest_run_ratio, shingle_ratio, composite)
    return {
        "match_type": match_type,
        "severity": _match_severity(similarity),
        "similarity": round(similarity, 3),
        "sequence_ratio": round(sequence_ratio, 3),
        "longest_run_ratio": round(longest_run_ratio, 3),
        "shingle_ratio": round(shingle_ratio, 3),
        "fingerprint_ratio": round(fingerprint_ratio, 3),
        "content_overlap": round(overlap, 3),
        "penalty_factor": penalty_factor,
        "matched_phrase": " ".join(run_tokens[:18]).strip(),
        "source_label": source_block["label"],
        "source_url": source_block["url"],
        "source_kind": source_block["kind"],
        "source_passage_index": source_block["passage_index"],
        "recommendation": _recommendation(match_type),
    }


def _transition_density(sentences: list[str]) -> float:
    if not sentences:
        return 0.0
    count = 0
    for sentence in sentences:
        lowered = sentence.lower()
        if any(lowered.startswith(phrase + " ") or lowered == phrase for phrase in _TRANSITION_PHRASES):
            count += 1
    return count / max(1, len(sentences))


def _repeated_opening_ratio(sentences: list[str]) -> float:
    openings = [" ".join(_tokenize_words(sentence)[:3]) for sentence in sentences if len(_tokenize_words(sentence)) >= 3]
    if not openings:
        return 0.0
    counts = Counter(openings)
    repeated = sum(value for value in counts.values() if value > 1)
    return repeated / max(1, len(openings))


def _repeated_ngram_ratio(tokens: list[str], *, n: int = 4) -> float:
    if len(tokens) < n:
        return 0.0
    ngrams = [tuple(tokens[index : index + n]) for index in range(0, len(tokens) - n + 1)]
    counts = Counter(ngrams)
    repeated = sum(count - 1 for count in counts.values() if count > 1)
    return repeated / max(1, len(ngrams))


def _adjacent_sentence_similarity(sentences: list[str]) -> float:
    if len(sentences) < 2:
        return 0.0
    scores: list[float] = []
    for left, right in zip(sentences, sentences[1:]):
        scores.append(_sequence_ratio(left, right))
    return sum(scores) / max(1, len(scores))


def _variation_ratio(lengths: list[int]) -> float:
    if len(lengths) < 2:
        return 0.0
    mean = sum(lengths) / max(1, len(lengths))
    if mean <= 0:
        return 0.0
    variance = sum((length - mean) ** 2 for length in lengths) / len(lengths)
    return math.sqrt(variance) / mean


def _estimate_ai_signals(text: str) -> dict[str, Any]:
    plain = _strip_markdown(text)
    tokens = _tokenize_words(plain)
    if len(tokens) < 40:
        return {
            "score": 0.0,
            "signals": {
                "lexical_diversity": 0.0,
                "sentence_length_variation": 0.0,
                "paragraph_length_variation": 0.0,
                "repeated_opening_ratio": 0.0,
                "transition_density": 0.0,
                "adjacent_sentence_similarity": 0.0,
                "repeated_ngram_ratio": 0.0,
                "hapax_ratio": 0.0,
            },
            "components": {},
        }

    sentences = _sentence_split(plain)
    paragraphs = _section_text_blocks(plain)
    content_tokens = _content_tokens(tokens)
    lexical_diversity = len(set(content_tokens)) / max(1, len(content_tokens))
    sentence_lengths = [len(_tokenize_words(sentence)) for sentence in sentences]
    paragraph_lengths = [len(_tokenize_words(paragraph)) for paragraph in paragraphs]
    repeated_openings = _repeated_opening_ratio(sentences)
    transition_density = _transition_density(sentences)
    adjacent_similarity = _adjacent_sentence_similarity(sentences)
    repeated_ngram_ratio = _repeated_ngram_ratio(tokens, n=4)
    hapax_ratio = sum(1 for value in Counter(content_tokens).values() if value == 1) / max(1, len(content_tokens))
    sentence_variation = _variation_ratio(sentence_lengths)
    paragraph_variation = _variation_ratio(paragraph_lengths)

    components = {
        "low_lexical_diversity": min(18.0, max(0.0, 0.46 - lexical_diversity) * 75.0),
        "low_sentence_burstiness": min(17.0, max(0.0, 0.58 - sentence_variation) * 35.0),
        "low_paragraph_burstiness": min(10.0, max(0.0, 0.72 - paragraph_variation) * 20.0),
        "repeated_openings": min(16.0, repeated_openings * 28.0),
        "transition_saturation": min(12.0, transition_density * 20.0),
        "adjacent_sentence_similarity": min(17.0, max(0.0, adjacent_similarity - 0.38) * 40.0),
        "repeated_ngrams": min(14.0, repeated_ngram_ratio * 55.0),
        "low_hapax_ratio": min(8.0, max(0.0, 0.23 - hapax_ratio) * 28.0),
    }
    score = round(_clamp(sum(components.values())), 1)
    return {
        "score": score,
        "signals": {
            "lexical_diversity": round(lexical_diversity, 3),
            "sentence_length_variation": round(sentence_variation, 3),
            "paragraph_length_variation": round(paragraph_variation, 3),
            "repeated_opening_ratio": round(repeated_openings, 3),
            "transition_density": round(transition_density, 3),
            "adjacent_sentence_similarity": round(adjacent_similarity, 3),
            "repeated_ngram_ratio": round(repeated_ngram_ratio, 3),
            "hapax_ratio": round(hapax_ratio, 3),
        },
        "components": {key: round(value, 2) for key, value in components.items()},
    }


def build_plagiarism_report(section_outputs: list[dict], source_texts: list[dict]) -> dict:
    source_blocks = _build_source_blocks(source_texts)
    section_reports: list[dict[str, Any]] = []
    report_passages: list[dict[str, Any]] = []

    for section_index, section in enumerate(section_outputs or [], start=1):
        title = str(section.get("title", f"Section {section_index}")).strip() or f"Section {section_index}"
        raw_blocks = _section_text_blocks(section.get("section_text", ""))
        section_passages: list[dict[str, Any]] = []
        for passage_index, passage in enumerate(raw_blocks, start=1):
            tokens = _tokenize_words(passage)
            if len(tokens) < 12:
                continue
            normalized = " ".join(tokens)
            section_passages.append(
                {
                    "section_index": section_index,
                    "section_title": title,
                    "passage_index": passage_index,
                    "text": passage,
                    "normalized": normalized,
                    "tokens": tokens,
                    "content_tokens": set(_content_tokens(tokens)),
                    "shingles": _word_shingles(tokens, 5),
                    "fingerprints": _fingerprints(tokens),
                    "citation_present": bool(_CITATION_RE.search(str(section.get("section_text", "")).split("\n\n")[max(0, passage_index - 1)] if str(section.get("section_text", "")).strip() else "")),
                }
            )
        report_passages.extend(section_passages)
        section_reports.append(
            {
                "section_title": title,
                "passages": section_passages,
                "raw_text": str(section.get("section_text", "")).strip(),
            }
        )

    total_words = 0
    total_weighted_match_words = 0.0
    all_ai_scores: list[float] = []

    for section in section_reports:
        flagged_passages: list[dict[str, Any]] = []
        section_words = 0
        section_weighted_match_words = 0.0
        ai_payload = _estimate_ai_signals(section["raw_text"])
        ai_score = float(ai_payload["score"])
        all_ai_scores.append(ai_score)

        for passage in section["passages"]:
            passage_words = len(passage["tokens"])
            section_words += passage_words
            candidates = []
            for source_block in source_blocks:
                result = _evaluate_match(passage, source_block)
                if result is not None:
                    candidates.append(result)
            for peer in report_passages:
                if peer["section_index"] == passage["section_index"]:
                    continue
                peer_block = {
                    "label": peer["section_title"],
                    "url": "",
                    "kind": "report_section",
                    "passage_index": peer["passage_index"],
                    "text": peer["normalized"],
                    "tokens": peer["tokens"],
                    "content_tokens": peer["content_tokens"],
                    "shingles": peer["shingles"],
                    "fingerprints": peer["fingerprints"],
                }
                result = _evaluate_match(passage, peer_block)
                if result is not None:
                    candidates.append(result)

            if not candidates:
                continue
            candidates.sort(
                key=lambda item: (
                    item["penalty_factor"] * item["similarity"],
                    item["sequence_ratio"],
                    item["longest_run_ratio"],
                ),
                reverse=True,
            )
            best = candidates[0]
            weighted_similarity = best["penalty_factor"] * float(best["similarity"])
            section_weighted_match_words += passage_words * weighted_similarity
            flagged_passages.append(
                {
                    "passage_index": passage["passage_index"],
                    "text_excerpt": _passage_summary(passage["text"]),
                    "similarity": best["similarity"],
                    "weighted_similarity": round(weighted_similarity, 3),
                    "sequence_ratio": best["sequence_ratio"],
                    "longest_run_ratio": best["longest_run_ratio"],
                    "shingle_ratio": best["shingle_ratio"],
                    "fingerprint_ratio": best["fingerprint_ratio"],
                    "content_overlap": best["content_overlap"],
                    "source_label": best["source_label"],
                    "source_url": best["source_url"],
                    "source_kind": best["source_kind"],
                    "source_passage_index": best["source_passage_index"],
                    "type": best["match_type"],
                    "severity": best["severity"],
                    "citation_present": passage["citation_present"],
                    "matched_phrase": best["matched_phrase"],
                    "recommendation": best["recommendation"],
                }
            )

        total_words += section_words
        total_weighted_match_words += section_weighted_match_words
        section_score = round((section_weighted_match_words / max(1, section_words)) * 100.0, 1) if section_words else 0.0
        section["report"] = {
            "section_title": section["section_title"],
            "plagiarism_score": section_score,
            "ai_score": ai_score,
            "passages_scanned": len(section["passages"]),
            "words_scanned": section_words,
            "flagged_passages": flagged_passages[:10],
            "ai_signals": ai_payload["signals"],
            "ai_components": ai_payload["components"],
        }

    overall_similarity = round((total_weighted_match_words / max(1, total_words)) * 100.0, 1) if total_words else 0.0
    overall_ai = round(sum(all_ai_scores) / max(1, len(all_ai_scores)), 1) if all_ai_scores else 0.0
    status = "PASS"
    if overall_similarity >= 18 or overall_ai >= 75:
        status = "FAIL"
    elif overall_similarity >= 8 or overall_ai >= 45:
        status = "WARN"

    return {
        "version": "kendr-plagiarism-v2",
        "method": {
            "matching": [
                "citation-aware passage matching",
                "5-gram containment",
                "fingerprint overlap",
                "longest common token span",
                "internal duplication detection",
            ],
            "ai_scoring": [
                "lexical diversity",
                "sentence and paragraph burstiness",
                "repeated openings",
                "transition saturation",
                "adjacent sentence similarity",
                "repeated 4-grams",
                "hapax ratio",
            ],
        },
        "overall_score": overall_similarity,
        "ai_content_score": overall_ai,
        "status": status,
        "sections": [section["report"] for section in section_reports],
        "source_block_count": len(source_blocks),
        "summary": (
            f"Similarity score {overall_similarity}% and AI-writing risk {overall_ai}% "
            f"across {len(section_reports)} section(s)."
        ),
    }
