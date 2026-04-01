"""Skill-based routing registry.

Auto-discovers all registered agents (including MCP tools) at gateway startup,
builds an intent-keyword index, and provides ``top_match()`` for fast
single-agent routing — bypassing the LLM planner when the intent is clearly
mapped to exactly one active, configured agent.

Usage
-----
At startup::

    from kendr.skill_registry import build_skill_registry
    sr = build_skill_registry(registry)

In the orchestrator::

    target = sr.top_match(user_query)
    if target:
        state["next_agent"] = target   # skip planner
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from kendr.registry import Registry


# Agents that are part of the orchestration infrastructure and must never
# be offered as direct routing targets.
_SYSTEM_AGENTS: frozenset[str] = frozenset({
    "planner_agent",
    "orchestrator_agent",
    "worker_agent",
    "channel_gateway_agent",
    "session_router_agent",
    "finalize_agent",
    "error_handler_agent",
    "post_setup_agent",
    "blueprint_reviewer_agent",
})

_STOPWORDS: frozenset[str] = frozenset(
    "a an the of in on at to for with by from and or is are was were be been "
    "this that these those it its i me my we our you your he she his her they "
    "their what how why when where who which can could would should will have "
    "has had do does did not no any all some just also well make get".split()
)

# Category display names and emoji badges
_CATEGORY_META: dict[str, dict] = {
    "development":  {"label": "Development",    "emoji": "💻"},
    "github":       {"label": "GitHub / Git",   "emoji": "🐙"},
    "research":     {"label": "Research",       "emoji": "🔬"},
    "documents":    {"label": "Documents",      "emoji": "📄"},
    "testing":      {"label": "Testing",        "emoji": "🧪"},
    "deployment":   {"label": "Cloud Deploy",   "emoji": "🚀"},
    "infra":        {"label": "Infrastructure", "emoji": "🏗️"},
    "comms":        {"label": "Communications", "emoji": "💬"},
    "data":         {"label": "Data / RAG",     "emoji": "📊"},
    "security":     {"label": "Security",       "emoji": "🔒"},
    "general":      {"label": "General",        "emoji": "✨"},
    "mcp":          {"label": "MCP Tools",      "emoji": "🔌"},
}


@dataclass
class SkillCard:
    agent_name: str
    display_name: str
    description: str
    category: str
    skills: list[str] = field(default_factory=list)
    intent_patterns: list[str] = field(default_factory=list)
    active_when: list[str] = field(default_factory=list)
    is_active: bool = True
    config_hint: str = ""

    def to_dict(self) -> dict:
        cat = self.category or "general"
        cat_meta = _CATEGORY_META.get(cat, _CATEGORY_META["general"])
        return {
            "agent_name": self.agent_name,
            "display_name": self.display_name,
            "description": self.description,
            "category": cat,
            "category_label": cat_meta["label"],
            "category_emoji": cat_meta["emoji"],
            "skills": self.skills,
            "is_active": self.is_active,
            "config_hint": self.config_hint,
        }


class SkillRegistry:
    """Intent-routing registry built from all registered agents.

    Call ``top_match(query)`` to get a high-confidence single-agent route or
    ``None`` when the query is ambiguous (fall through to the planner).
    """

    # A candidate must score at least this much to be considered high-confidence.
    DIRECT_ROUTE_THRESHOLD: float = 5.0
    # Top candidate must outscore runner-up by this ratio to be "unambiguous".
    DIRECT_ROUTE_DOMINANCE: float = 2.2

    def __init__(self, registry: "Registry") -> None:
        self._cards: list[SkillCard] = []
        # keyword → list of (agent_name, weight)
        self._index: dict[str, list[tuple[str, float]]] = {}
        self._build(registry)

    # ------------------------------------------------------------------ build

    def _check_condition(self, cond: str) -> bool:
        cond = cond.strip()
        if not cond or cond == "always":
            return True
        if cond.startswith("env:"):
            key = cond[4:].strip()
            return bool(os.environ.get(key, "").strip())
        if cond.startswith("provider:"):
            prefix = cond[9:].strip().upper()
            return any(
                os.environ.get(k, "").strip()
                for k in os.environ
                if k.upper().startswith(prefix)
            )
        return True

    def _is_active(self, conditions: list[str]) -> bool:
        if not conditions:
            return True
        return all(self._check_condition(c) for c in conditions)

    def _make_card(self, agent, meta: dict) -> SkillCard:
        name = agent.name
        base = name[:-6] if name.endswith("_agent") else name
        default_display = base.replace("_", " ").title()
        active_when = list(meta.get("active_when") or [])
        return SkillCard(
            agent_name=name,
            display_name=meta.get("display_name") or default_display,
            description=meta.get("description") or agent.description or "",
            category=meta.get("category", "general"),
            skills=list(agent.skills or []),
            intent_patterns=list(meta.get("intent_patterns") or []),
            active_when=active_when,
            is_active=self._is_active(active_when),
            config_hint=meta.get("config_hint", ""),
        )

    def _index_card(self, card: SkillCard) -> None:
        """Add card tokens to the inverted index with weights."""
        seen: dict[str, float] = {}

        # Skills → high weight (2.5)
        for skill in card.skills:
            for w in re.findall(r"[a-z]+", skill.lower()):
                if w not in _STOPWORDS and len(w) > 2:
                    seen[w] = max(seen.get(w, 0.0), 2.5)

        # Intent patterns → medium weight (1.8)
        for pat in card.intent_patterns:
            for w in re.findall(r"[a-z]+", pat.lower()):
                if w not in _STOPWORDS and len(w) > 2:
                    seen[w] = max(seen.get(w, 0.0), 1.8)

        # Description → low weight (0.5)
        for w in re.findall(r"[a-z]+", (card.description or "").lower()):
            if w not in _STOPWORDS and len(w) > 2:
                seen[w] = max(seen.get(w, 0.0), 0.5)

        for w, weight in seen.items():
            self._index.setdefault(w, []).append((card.agent_name, weight))

    def _build(self, registry: "Registry") -> None:
        for agent in registry.agents.values():
            if agent.name in _SYSTEM_AGENTS:
                continue
            meta = agent.metadata or {}
            card = self._make_card(agent, meta)
            self._cards.append(card)
            if card.is_active:
                self._index_card(card)

    # ------------------------------------------------------------------ query

    def match_query(self, text: str) -> list[tuple[str, float]]:
        """Return ``[(agent_name, score), …]`` sorted by score descending.

        Only active agents are included.  Scores are additive across matched
        tokens so a query hitting multiple strong signals scores higher.
        """
        if not text:
            return []
        tokens = [
            w for w in re.findall(r"[a-z]+", text.lower())
            if w not in _STOPWORDS and len(w) > 2
        ]
        scores: dict[str, float] = {}
        for tok in tokens:
            for agent_name, weight in self._index.get(tok, []):
                scores[agent_name] = scores.get(agent_name, 0.0) + weight
        return sorted(scores.items(), key=lambda x: x[1], reverse=True)

    def top_match(self, text: str) -> str | None:
        """Return the best agent name when a single dominant match exists.

        Returns ``None`` when the query is ambiguous or below threshold —
        the orchestrator should fall through to the planner in that case.
        """
        ranked = self.match_query(text)
        if not ranked:
            return None
        top_name, top_score = ranked[0]
        if top_score < self.DIRECT_ROUTE_THRESHOLD:
            return None
        if len(ranked) > 1:
            _, second_score = ranked[1]
            if second_score > 0 and (top_score / second_score) < self.DIRECT_ROUTE_DOMINANCE:
                return None
        return top_name

    def hint_agents(self, text: str, n: int = 3) -> list[str]:
        """Return the top-n agent names as routing hints for the planner."""
        return [name for name, _ in self.match_query(text)[:n]]

    # ------------------------------------------------------------------ cards

    def get_all_cards(self) -> list[SkillCard]:
        return list(self._cards)

    def get_active_cards(self) -> list[SkillCard]:
        return [c for c in self._cards if c.is_active]

    def get_inactive_cards(self) -> list[SkillCard]:
        return [c for c in self._cards if not c.is_active]

    def summary(self) -> dict:
        active = sum(1 for c in self._cards if c.is_active)
        by_cat: dict[str, int] = {}
        for c in self._cards:
            if c.is_active:
                by_cat[c.category] = by_cat.get(c.category, 0) + 1
        return {
            "total": len(self._cards),
            "active": active,
            "inactive": len(self._cards) - active,
            "by_category": by_cat,
        }


def build_skill_registry(registry: "Registry") -> SkillRegistry:
    """Convenience factory — call once at startup."""
    return SkillRegistry(registry)
