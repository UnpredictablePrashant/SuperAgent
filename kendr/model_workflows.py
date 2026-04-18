from __future__ import annotations

import os
from typing import Any

from kendr.llm_router import infer_model_family, supports_native_web_search

_OCR_COMPATIBLE_PROVIDERS = {
    "openai",
    "xai",
    "minimax",
    "qwen",
    "glm",
    "ollama",
    "openrouter",
    "custom",
}

def _env_flag(name: str, default: bool) -> bool:
    raw = str(os.getenv(name, "1" if default else "0") or "").strip().lower()
    if not raw:
        return default
    return raw not in {"0", "false", "no", "off"}


_STAGE_SPECS: dict[str, dict[str, Any]] = {
    "router": {
        "label": "Route",
        "required_capabilities": ["structured_output"],
        "preferred_capabilities": ["reasoning"],
        "min_context": 16000,
        "budget_class": "small",
        "family_bonus": {"openai": 3.0, "glm": 2.5, "google": 2.3, "anthropic": 2.0, "qwen": 1.7, "xai": 1.5},
        "name_bonus": [("mini", 0.5), ("flash", 0.4), ("haiku", 0.4), ("glm-4-flash", 0.6)],
    },
    "ocr": {
        "label": "OCR",
        "required_capabilities": ["vision"],
        "compatible_providers": _OCR_COMPATIBLE_PROVIDERS,
        "preferred_capabilities": ["structured_output"],
        "min_context": 8000,
        "budget_class": "small",
        "family_bonus": {"glm": 3.4, "google": 2.8, "openai": 2.6, "anthropic": 2.0, "qwen": 1.8, "xai": 1.3},
        "name_bonus": [("ocr", 2.0), ("vision", 1.0), ("flash", 0.5), ("4o", 0.7)],
    },
    "extract": {
        "label": "Extract",
        "required_capabilities": [],
        "preferred_capabilities": ["structured_output"],
        "min_context": 16000,
        "budget_class": "small",
        "family_bonus": {"ollama": 3.0, "qwen": 2.6, "glm": 2.2, "openai": 1.8, "google": 1.6, "anthropic": 1.4},
        "name_bonus": [("mini", 0.6), ("flash", 0.6), ("turbo", 0.5), ("haiku", 0.5)],
    },
    "summarize": {
        "label": "Summarize",
        "required_capabilities": [],
        "preferred_capabilities": ["structured_output"],
        "min_context": 16000,
        "budget_class": "small",
        "family_bonus": {"ollama": 2.8, "qwen": 2.5, "openai": 2.0, "glm": 1.8, "google": 1.6, "anthropic": 1.4},
        "name_bonus": [("mini", 0.6), ("flash", 0.6), ("turbo", 0.5), ("haiku", 0.5)],
    },
    "evidence": {
        "label": "Evidence",
        "required_capabilities": ["tool_calling", "reasoning"],
        "preferred_capabilities": ["structured_output"],
        "min_context": 32000,
        "budget_class": "medium",
        "family_bonus": {"openai": 3.7, "google": 2.9, "anthropic": 2.7, "glm": 2.3, "xai": 2.0, "qwen": 1.7},
        "name_bonus": [("deep-research", 2.0), ("gpt-5", 1.5), ("o3", 1.3), ("gemini-2.5", 0.9), ("glm-5", 0.8)],
    },
    "draft": {
        "label": "Draft",
        "required_capabilities": ["reasoning"],
        "preferred_capabilities": ["structured_output"],
        "min_context": 64000,
        "budget_class": "medium",
        "family_bonus": {"openai": 3.2, "anthropic": 3.0, "google": 2.8, "xai": 2.4, "glm": 2.2, "qwen": 1.8},
        "name_bonus": [("gpt-5", 1.6), ("o3", 1.4), ("opus", 1.3), ("sonnet", 1.1), ("gemini-2.5-pro", 1.0), ("glm-5", 0.9)],
    },
    "merge": {
        "label": "Merge",
        "required_capabilities": ["reasoning"],
        "preferred_capabilities": ["structured_output"],
        "min_context": 128000,
        "budget_class": "large",
        "family_bonus": {"openai": 3.4, "anthropic": 3.1, "google": 2.9, "xai": 2.5, "glm": 2.0, "qwen": 1.5},
        "name_bonus": [("gpt-5", 1.7), ("o3", 1.5), ("opus", 1.3), ("gemini-2.5-pro", 1.1), ("grok-4", 1.0)],
    },
    "answer": {
        "label": "Answer",
        "required_capabilities": ["reasoning"],
        "preferred_capabilities": [],
        "min_context": 32000,
        "budget_class": "medium",
        "family_bonus": {"openai": 2.8, "anthropic": 2.6, "google": 2.4, "glm": 2.1, "xai": 1.8, "qwen": 1.6},
        "name_bonus": [("gpt-5", 1.3), ("o3", 1.2), ("claude", 1.0), ("gemini", 0.8), ("glm-5", 0.7)],
    },
    "verify": {
        "label": "Verify",
        "required_capabilities": ["structured_output"],
        "preferred_capabilities": ["reasoning"],
        "min_context": 16000,
        "budget_class": "small",
        "family_bonus": {"openai": 3.1, "google": 2.9, "glm": 2.7, "anthropic": 2.4, "qwen": 1.8, "xai": 1.6},
        "name_bonus": [("mini", 0.5), ("flash", 0.4), ("haiku", 0.4), ("4o", 0.6), ("glm-4-flash", 0.7)],
    },
}

_WORKFLOW_TEMPLATES: list[dict[str, Any]] = [
    {
        "id": "ocr_ingestion",
        "label": "OCR + Ingestion",
        "description": "Extract text from images or scans, clean the output, and verify the structured result.",
        "task_examples": ["scan invoices", "extract text from screenshots", "ingest scanned PDFs"],
        "stages": ["ocr", "extract", "verify"],
    },
    {
        "id": "document_qa",
        "label": "Document Q&A",
        "description": "Turn raw documents into a concise summary and answer questions from that normalized context.",
        "task_examples": ["summarize attached docs", "answer from uploaded files", "compare two PDFs"],
        "stages": ["ocr", "summarize", "answer"],
    },
    {
        "id": "deep_research_report",
        "label": "Deep Research Report",
        "description": "Route the task, gather evidence, draft sections, merge the report, and verify the final output.",
        "task_examples": ["deep research with citations", "long-form research report", "competitive landscape report"],
        "stages": ["router", "evidence", "draft", "merge", "verify"],
    },
]


def multi_model_enabled() -> bool:
    return _env_flag("KENDR_MULTI_MODEL_ENABLED", True)


def _flatten_ready_models(statuses: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for status in statuses:
        if not isinstance(status, dict) or not bool(status.get("ready")):
            continue
        provider = str(status.get("provider") or "").strip().lower()
        if not provider:
            continue
        details = status.get("selectable_model_details")
        if not isinstance(details, list) or not details:
            details = [{
                "name": str(status.get("model") or "").strip(),
                "family": str(status.get("model_family") or infer_model_family(str(status.get("model") or ""), provider)).strip(),
                "context_window": int(status.get("context_window") or 0),
                "capabilities": dict(status.get("model_capabilities") or {}),
                "agent_capable": bool(status.get("agent_capable")),
            }]
        for detail in details:
            model = str(detail.get("name") or "").strip()
            if not model:
                continue
            key = (provider, model)
            if key in seen:
                continue
            seen.add(key)
            capabilities = detail.get("capabilities") if isinstance(detail.get("capabilities"), dict) else {}
            family = str(detail.get("family") or infer_model_family(model, provider)).strip().lower() or provider
            rows.append({
                "provider": provider,
                "model": model,
                "family": family,
                "label": f"{provider}/{model}",
                "context_window": int(detail.get("context_window") or status.get("context_window") or 0),
                "capabilities": {
                    **capabilities,
                    "native_web_search": supports_native_web_search(model, family or provider),
                },
                "agent_capable": bool(detail.get("agent_capable", status.get("agent_capable"))),
                "local": provider == "ollama",
                "source_provider": provider,
            })
    return rows


def _estimate_cost_score(candidate: dict[str, Any]) -> float:
    provider = str(candidate.get("provider") or "").strip().lower()
    name = str(candidate.get("model") or "").strip().lower()
    score = {
        "ollama": 0.3,
        "openrouter": 2.8,
        "google": 3.0,
        "glm": 3.1,
        "qwen": 3.2,
        "minimax": 3.4,
        "custom": 3.5,
        "openai": 5.0,
        "anthropic": 5.2,
        "xai": 5.5,
    }.get(provider, 4.5)
    if any(token in name for token in ("nano",)):
        score -= 2.5
    if any(token in name for token in ("mini", "flash", "haiku", "turbo")):
        score -= 1.9
    if any(token in name for token in ("lite", "small")):
        score -= 1.1
    if any(token in name for token in ("pro", "opus")):
        score += 1.8
    if "gpt-5" in name and "mini" not in name and "nano" not in name:
        score += 2.2
    if any(token in name for token in ("o3", "grok-4", "sonnet")):
        score += 1.0
    return max(score, 0.1)


def _estimate_quality_score(candidate: dict[str, Any]) -> float:
    caps = candidate.get("capabilities") if isinstance(candidate.get("capabilities"), dict) else {}
    context_window = int(candidate.get("context_window") or 0)
    name = str(candidate.get("model") or "").strip().lower()
    score = 0.0
    if caps.get("reasoning"):
        score += 2.8
    if caps.get("structured_output"):
        score += 1.0
    if caps.get("tool_calling"):
        score += 0.8
    if caps.get("vision"):
        score += 0.6
    if bool(candidate.get("agent_capable")):
        score += 0.8
    score += min(context_window, 400000) / 200000
    if "gpt-5" in name:
        score += 2.3
    elif "o3" in name:
        score += 2.0
    elif "claude-opus" in name:
        score += 2.1
    elif "claude-sonnet" in name:
        score += 1.8
    elif "gemini-2.5-pro" in name:
        score += 1.7
    elif "grok-4" in name:
        score += 1.6
    elif "glm-5" in name:
        score += 1.5
    elif "gpt-4o" in name:
        score += 1.3
    elif "gemini" in name or "glm" in name:
        score += 1.0
    elif any(token in name for token in ("qwen", "llama", "mistral", "gemma")):
        score += 0.7
    return score


def _cost_band(score: float) -> str:
    if score <= 0.6:
        return "free"
    if score <= 1.8:
        return "very-low"
    if score <= 3.0:
        return "low"
    if score <= 5.0:
        return "mid"
    return "high"


def _candidate_passes_stage(candidate: dict[str, Any], stage_name: str) -> tuple[bool, list[str]]:
    stage = _STAGE_SPECS[stage_name]
    failures: list[str] = []
    capabilities = candidate.get("capabilities") if isinstance(candidate.get("capabilities"), dict) else {}
    provider = str(candidate.get("provider") or "").strip().lower()
    compatible_providers = stage.get("compatible_providers")
    if compatible_providers and provider not in compatible_providers:
        failures.append("provider_support")
    for cap in stage.get("required_capabilities", []):
        if not capabilities.get(cap):
            failures.append(cap)
    if int(candidate.get("context_window") or 0) < int(stage.get("min_context") or 0):
        failures.append("context_window")
    return not failures, failures


def _stage_reason(candidate: dict[str, Any], stage_name: str, strategy: str) -> str:
    stage = _STAGE_SPECS[stage_name]
    capabilities = candidate.get("capabilities") if isinstance(candidate.get("capabilities"), dict) else {}
    strengths: list[str] = []
    if capabilities.get("vision") and stage_name == "ocr":
        strengths.append("vision")
    if capabilities.get("reasoning") and stage_name in {"evidence", "draft", "merge", "answer"}:
        strengths.append("reasoning")
    if capabilities.get("structured_output") and stage_name in {"router", "extract", "verify"}:
        strengths.append("structured output")
    if capabilities.get("native_web_search") and stage_name == "evidence":
        strengths.append("native web search")
    if candidate.get("local") and strategy == "cheapest" and stage_name in {"extract", "summarize"}:
        strengths.append("local low-cost execution")
    if not strengths:
        strengths.append("balanced fit")
    prefix = "Best fit" if strategy == "best" else "Lowest-cost fit"
    return f"{prefix} for {stage.get('label', stage_name).lower()} via " + ", ".join(strengths) + "."


def _stage_score(candidate: dict[str, Any], stage_name: str, strategy: str) -> float:
    ok, failures = _candidate_passes_stage(candidate, stage_name)
    if not ok:
        return float("-inf")
    stage = _STAGE_SPECS[stage_name]
    name = str(candidate.get("model") or "").strip().lower()
    family = str(candidate.get("family") or candidate.get("provider") or "").strip().lower()
    caps = candidate.get("capabilities") if isinstance(candidate.get("capabilities"), dict) else {}
    quality = _estimate_quality_score(candidate)
    cost = _estimate_cost_score(candidate)
    score = quality * (2.1 if strategy == "best" else 0.7)
    score -= cost * (0.3 if strategy == "best" else 1.9)
    score += float(stage.get("family_bonus", {}).get(family, stage.get("family_bonus", {}).get(candidate.get("provider"), 0.0)) or 0.0)
    for cap in stage.get("preferred_capabilities", []):
        if caps.get(cap):
            score += 0.7
    if stage_name == "evidence" and caps.get("native_web_search"):
        score += 1.5
    if stage_name == "ocr":
        if family == "glm":
            score += 1.6
        if "gpt-5" in name and "mini" not in name and "nano" not in name:
            score -= 0.9
    if stage_name in {"extract", "summarize"} and candidate.get("local") and strategy == "cheapest":
        score += 2.6
    if stage_name == "merge":
        score += min(int(candidate.get("context_window") or 0), 400000) / 100000
    for token, bonus in stage.get("name_bonus", []):
        if token in name:
            score += float(bonus)
    if failures:
        score -= len(failures) * 10
    return score


def _stage_result(candidate: dict[str, Any], stage_name: str, strategy: str, workflow_id: str) -> dict[str, Any]:
    stage = _STAGE_SPECS[stage_name]
    return {
        "stage": stage_name,
        "label": stage.get("label", stage_name),
        "provider": str(candidate.get("provider") or ""),
        "model": str(candidate.get("model") or ""),
        "family": str(candidate.get("family") or ""),
        "label_full": str(candidate.get("label") or ""),
        "context_window": int(candidate.get("context_window") or 0),
        "cost_score": round(_estimate_cost_score(candidate), 2),
        "cost_band": _cost_band(_estimate_cost_score(candidate)),
        "quality_score": round(_estimate_quality_score(candidate), 2),
        "reason": _stage_reason(candidate, stage_name, strategy),
        "capability_gate": {
            "required": list(stage.get("required_capabilities", [])),
            "passed": True,
        },
        "budget_gate": {
            "budget_class": str(stage.get("budget_class") or "medium"),
            "min_context": int(stage.get("min_context") or 0),
            "context_window": int(candidate.get("context_window") or 0),
            "passed": True,
        },
        "workflow_gate": workflow_id,
    }


def _fallback_stage_result(stage_name: str, workflow_id: str, failures: list[str]) -> dict[str, Any]:
    stage = _STAGE_SPECS[stage_name]
    return {
        "stage": stage_name,
        "label": stage.get("label", stage_name),
        "provider": "",
        "model": "",
        "family": "",
        "label_full": "",
        "context_window": 0,
        "cost_score": 0.0,
        "cost_band": "unknown",
        "quality_score": 0.0,
        "reason": "No available model passes this stage.",
        "capability_gate": {
            "required": list(stage.get("required_capabilities", [])),
            "passed": False,
            "missing": failures,
        },
        "budget_gate": {
            "budget_class": str(stage.get("budget_class") or "medium"),
            "min_context": int(stage.get("min_context") or 0),
            "context_window": 0,
            "passed": False,
        },
        "workflow_gate": workflow_id,
    }


def _stage_candidates(workflow_id: str, stage_name: str, candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
    ranked_rows: list[tuple[float, dict[str, Any]]] = []
    for candidate in candidates:
        score = _stage_score(candidate, stage_name, "best")
        if score == float("-inf"):
            continue
        row = _stage_result(candidate, stage_name, "best", workflow_id)
        row["rank_score"] = round(score, 3)
        ranked_rows.append((score, row))
    ranked_rows.sort(key=lambda item: item[0], reverse=True)
    return [row for _, row in ranked_rows[:25]]


def _workflow_stage_options(workflow: dict[str, Any], candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for stage_name in list(workflow.get("stages", [])):
        stage = _STAGE_SPECS.get(stage_name, {})
        rows.append({
            "stage": stage_name,
            "label": str(stage.get("label", stage_name)),
            "candidates": _stage_candidates(str(workflow.get("id") or ""), stage_name, candidates),
        })
    return rows


def _recommend_combo(workflow: dict[str, Any], candidates: list[dict[str, Any]], strategy: str, allow_multi_model: bool) -> dict[str, Any]:
    stages = list(workflow.get("stages", []))
    if not stages:
        return {"available": False, "strategy": strategy, "stages": []}

    if not allow_multi_model:
        best_candidate = None
        best_score = float("-inf")
        for candidate in candidates:
            total = 0.0
            valid = True
            for stage_name in stages:
                score = _stage_score(candidate, stage_name, strategy)
                if score == float("-inf"):
                    valid = False
                    break
                total += score
            if valid and total > best_score:
                best_candidate = candidate
                best_score = total
        if best_candidate is None:
            return {
                "available": False,
                "strategy": strategy,
                "mode_used": "single-model",
                "summary": "No single available model satisfies every stage.",
                "stages": [_fallback_stage_result(stage_name, workflow["id"], ["single_model_fit"]) for stage_name in stages],
            }
        stage_rows = [_stage_result(best_candidate, stage_name, strategy, workflow["id"]) for stage_name in stages]
    else:
        stage_rows = []
        available = True
        for stage_name in stages:
            ranked = sorted(
                candidates,
                key=lambda item: _stage_score(item, stage_name, strategy),
                reverse=True,
            )
            if not ranked or _stage_score(ranked[0], stage_name, strategy) == float("-inf"):
                available = False
                failures = list(_STAGE_SPECS[stage_name].get("required_capabilities", []))
                if "context_window" not in failures:
                    failures.append("context_window")
                stage_rows.append(_fallback_stage_result(stage_name, workflow["id"], failures))
                continue
            stage_rows.append(_stage_result(ranked[0], stage_name, strategy, workflow["id"]))
        if not available:
            return {
                "available": False,
                "strategy": strategy,
                "mode_used": "multi-model",
                "summary": "One or more stages do not have an available model match.",
                "stages": stage_rows,
            }

    unique_models = {(row.get("provider"), row.get("model")) for row in stage_rows if row.get("provider") and row.get("model")}
    avg_cost = sum(float(row.get("cost_score") or 0.0) for row in stage_rows) / max(len(stage_rows), 1)
    summary_parts = []
    for row in stage_rows[:3]:
        summary_parts.append(f"{row.get('label')}: {row.get('provider')}/{row.get('model')}")
    return {
        "available": True,
        "strategy": strategy,
        "mode_used": "multi-model" if allow_multi_model else "single-model",
        "uses_multiple_models": len(unique_models) > 1,
        "estimated_cost_band": _cost_band(avg_cost),
        "summary": "; ".join(summary_parts),
        "stages": stage_rows,
    }


def build_workflow_recommendations(
    statuses: list[dict[str, Any]],
    *,
    multi_model: bool | None = None,
) -> dict[str, Any]:
    allow_multi_model = multi_model_enabled() if multi_model is None else bool(multi_model)
    candidates = _flatten_ready_models(statuses)
    workflows: list[dict[str, Any]] = []
    for workflow in _WORKFLOW_TEMPLATES:
        workflows.append({
            "id": workflow["id"],
            "label": workflow["label"],
            "description": workflow["description"],
            "task_examples": list(workflow.get("task_examples", [])),
            "stage_options": _workflow_stage_options(workflow, candidates),
            "best": _recommend_combo(workflow, candidates, "best", allow_multi_model),
            "cheapest": _recommend_combo(workflow, candidates, "cheapest", allow_multi_model),
        })
    return {
        "enabled": allow_multi_model,
        "mode": "multi-model" if allow_multi_model else "single-model",
        "pricing_basis": "heuristic",
        "candidate_count": len(candidates),
        "available_families": sorted({str(item.get("family") or "") for item in candidates if str(item.get("family") or "").strip()}),
        "workflows": workflows,
        "notes": [
            "Recommendations are availability-aware and use heuristic cost scoring when live cross-provider pricing is unavailable.",
            "Best combinations prioritize stage fit and quality; cheapest combinations keep minimum stage requirements and then minimize estimated cost.",
        ],
    }
