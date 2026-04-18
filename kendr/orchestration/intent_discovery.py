from __future__ import annotations

import hashlib
import re
from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass(slots=True)
class IntentCandidate:
    intent_id: str
    intent_type: str
    label: str
    score: int
    selected: bool = False
    execution_mode: str = "adaptive"
    requires_planner: bool = False
    risk_level: str = "low"
    reasons: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def objective_signature(user_query: str, current_objective: str) -> str:
    raw = normalize_intent_text(f"{user_query}\n{current_objective}")
    digest = hashlib.sha1(raw.encode("utf-8")).hexdigest()
    return digest[:16]


def normalize_intent_text(text: str) -> str:
    return re.sub(r"\s+", " ", str(text or "").strip().lower())


def build_intent_candidates(
    *,
    user_query: str,
    current_objective: str,
    flags: dict[str, bool],
    planner_signals: dict[str, Any] | None = None,
) -> dict[str, Any]:
    signature = objective_signature(user_query, current_objective)
    signals = dict(planner_signals or {})
    score = int(signals.get("score", 0) or 0)
    threshold = int(signals.get("threshold", 4) or 4)
    risk_markers = int(signals.get("risk_markers", 0) or 0)

    candidates: list[IntentCandidate] = []

    def add_candidate(
        intent_type: str,
        label: str,
        base_score: int,
        *,
        execution_mode: str = "adaptive",
        requires_planner: bool = False,
        risk_level: str = "low",
        reasons: list[str] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        candidates.append(
            IntentCandidate(
                intent_id=f"{signature}:{intent_type}",
                intent_type=intent_type,
                label=label,
                score=base_score,
                execution_mode=execution_mode,
                requires_planner=requires_planner,
                risk_level=risk_level,
                reasons=list(reasons or []),
                metadata=dict(metadata or {}),
            )
        )

    if flags.get("security_assessment"):
        add_candidate(
            "security_assessment",
            "Security assessment workflow",
            99,
            execution_mode="plan",
            requires_planner=True,
            risk_level="high",
            reasons=["security-sensitive request detected"],
            metadata={"approval_required": True},
        )
    if flags.get("local_command"):
        add_candidate(
            "local_command",
            "Direct local command workflow",
            97,
            execution_mode="direct_tools",
            requires_planner=False,
            risk_level="medium" if risk_markers else "low",
            reasons=["direct command request detected"],
        )
    if flags.get("shell_plan"):
        add_candidate(
            "shell_plan",
            "Shell planning workflow",
            96,
            execution_mode="direct_tools",
            requires_planner=False,
            risk_level="medium",
            reasons=["shell planning request detected"],
        )
    if flags.get("github"):
        add_candidate(
            "github_ops",
            "Git/GitHub workflow",
            95,
            execution_mode="direct_tools",
            requires_planner=False,
            risk_level="medium",
            reasons=["git or github action detected"],
        )
    if flags.get("registry_discovery"):
        add_candidate(
            "capability_discovery",
            "Capability discovery workflow",
            94,
            execution_mode="direct_tools",
            requires_planner=False,
            reasons=["registry or MCP discovery request detected"],
        )
    if flags.get("communication_digest"):
        add_candidate(
            "communication_digest",
            "Communication digest workflow",
            93,
            execution_mode="direct_tools",
            requires_planner=False,
            reasons=["communication summary request detected"],
        )
    if flags.get("project_build"):
        add_candidate(
            "project_build",
            "Project build workflow",
            92,
            execution_mode="plan",
            requires_planner=True,
            risk_level="medium",
            reasons=["project build request detected"],
        )
    # Deep research is the canonical user-facing workflow for long-form researched
    # reports. When both signals are present, suppress the separate long-document
    # candidate so the router surfaces a single coherent workflow choice.
    if flags.get("long_document") and not flags.get("deep_research"):
        add_candidate(
            "long_document",
            "Long document workflow",
            91,
            execution_mode="plan",
            requires_planner=True,
            risk_level="medium",
            reasons=["long-document workflow detected"],
        )
    if flags.get("deep_research"):
        add_candidate(
            "deep_research",
            "Deep research workflow",
            90,
            execution_mode="plan",
            requires_planner=True,
            risk_level="medium",
            reasons=["deep research workflow detected"],
        )
    if flags.get("superrag"):
        add_candidate(
            "superrag",
            "SuperRAG workflow",
            89,
            execution_mode="plan",
            requires_planner=True,
            risk_level="medium",
            reasons=["SuperRAG workflow detected"],
        )
    if flags.get("local_drive"):
        add_candidate(
            "local_drive_analysis",
            "Local-drive analysis workflow",
            88,
            execution_mode="plan",
            requires_planner=True,
            risk_level="medium",
            reasons=["local-drive workflow detected"],
        )
    if bool(signals.get("explicit_plan_request")):
        add_candidate(
            "explicit_plan_request",
            "Explicit plan request",
            85,
            execution_mode="plan",
            requires_planner=True,
            risk_level="medium" if risk_markers else "low",
            reasons=["user explicitly requested a plan"],
        )

    general_requires_planner = score >= threshold
    general_reasons = []
    if general_requires_planner:
        general_reasons.append("planner heuristics crossed the execution threshold")
    else:
        general_reasons.append("planner heuristics stayed below the execution threshold")
    add_candidate(
        "general_task",
        "General task workflow",
        max(40, min(80, 50 + score)),
        execution_mode="plan" if general_requires_planner else "adaptive",
        requires_planner=general_requires_planner,
        risk_level="medium" if risk_markers else "low",
        reasons=general_reasons,
        metadata={"planner_score": score, "planner_threshold": threshold},
    )

    ordered = sorted(
        candidates,
        key=lambda item: (-item.score, item.intent_type),
    )
    if ordered:
        ordered[0].selected = True

    return {
        "objective_signature": signature,
        "candidates": [item.to_dict() for item in ordered],
        "selected": ordered[0].to_dict() if ordered else {},
    }
