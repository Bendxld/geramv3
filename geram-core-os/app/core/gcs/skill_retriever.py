"""
Local Skill Retriever — GERAM Core System.

Fully-local retrieval. The flow is:

    Monaco / prompt  ->  Autocomplete  ->  Skill Retriever  ->  local answer

If a sufficiently-matching Skill exists, the answer comes from local knowledge
and **no external provider is called at all**. This is what lets GERAM stay
useful with zero API keys and fully offline.

Matching is deterministic and cheap (no embeddings, no network): exact trigger
matches win, then trigger substrings, then name, then description. Every
response names the Skill it used so the UI can show provenance ("answered
locally by <skill>").
"""

from __future__ import annotations

from dataclasses import dataclass

from app.core.gcs.skills import Skill, SkillStore, skill_store

# The retriever never trusts an unbounded query — clamp before scanning.
MAX_QUERY_LENGTH = 2_000

# Score weights, highest signal first. Exact trigger equality is decisive.
_SCORE_EXACT_TRIGGER = 100
_SCORE_TRIGGER_SUBSTRING = 40
_SCORE_NAME = 25
_SCORE_DESCRIPTION = 10


@dataclass(frozen=True)
class SkillMatch:
    """A scored retrieval hit."""

    skill: Skill
    score: int
    reason: str

    def as_dict(self) -> dict:
        return {"skill": self.skill.summary(), "score": self.score, "reason": self.reason}


@dataclass(frozen=True)
class RetrievalResult:
    """Outcome of a retrieval. ``handled_locally`` is the key signal for callers:
    when True, do NOT fall back to an external provider."""

    query: str
    handled_locally: bool
    matches: list[SkillMatch]

    @property
    def best(self) -> SkillMatch | None:
        return self.matches[0] if self.matches else None

    def as_dict(self) -> dict:
        best = self.best
        return {
            "query": self.query,
            "handled_locally": self.handled_locally,
            "skill_used": best.skill.id if best else None,
            "matches": [match.as_dict() for match in self.matches],
        }


class SkillRetriever:
    """Deterministic, offline scorer over the enabled Skill catalog."""

    def __init__(self, store: SkillStore | None = None) -> None:
        self._store = store or skill_store

    def _score(self, skill: Skill, query: str) -> tuple[int, str]:
        """Return ``(score, reason)`` for one skill against a normalized query."""
        best_score = 0
        best_reason = ""

        for trigger in skill.triggers:
            if not trigger:
                continue
            if trigger == query:
                return _SCORE_EXACT_TRIGGER, f"exact trigger '{trigger}'"
            if trigger in query or query in trigger:
                if _SCORE_TRIGGER_SUBSTRING > best_score:
                    best_score, best_reason = _SCORE_TRIGGER_SUBSTRING, f"trigger '{trigger}'"

        name = skill.name.strip().lower()
        if name and (name in query or query in name) and _SCORE_NAME > best_score:
            best_score, best_reason = _SCORE_NAME, "name match"

        description = skill.description.strip().lower()
        if description and query and query in description and _SCORE_DESCRIPTION > best_score:
            best_score, best_reason = _SCORE_DESCRIPTION, "description match"

        return best_score, best_reason

    def retrieve(
        self,
        query: str,
        *,
        profile: str = "any",
        limit: int = 5,
        min_score: int = _SCORE_DESCRIPTION,
    ) -> RetrievalResult:
        """Score every enabled, profile-compatible skill against ``query``.

        ``handled_locally`` is True only when the top hit is a confident match
        (>= a trigger substring), which is the threshold at which the caller
        should skip the external provider entirely.
        """
        normalized = (query or "").strip().lower()[:MAX_QUERY_LENGTH]
        if not normalized:
            return RetrievalResult(query=query or "", handled_locally=False, matches=[])

        target_profile = (profile or "any").strip().lower()
        bounded_limit = max(1, min(int(limit), 20))

        scored: list[SkillMatch] = []
        for skill in self._store.list_all():
            if skill.status != "enabled":
                continue
            if target_profile != "any" and not skill.supports_profile(target_profile):
                continue
            score, reason = self._score(skill, normalized)
            if score >= min_score:
                scored.append(SkillMatch(skill=skill, score=score, reason=reason))

        # Highest score first; ties broken by system-before-custom then id for
        # deterministic, reproducible output.
        scored.sort(key=lambda m: (-m.score, 0 if m.skill.origin == "system" else 1, m.skill.id))
        top = scored[:bounded_limit]

        handled_locally = bool(top) and top[0].score >= _SCORE_TRIGGER_SUBSTRING
        return RetrievalResult(query=query, handled_locally=handled_locally, matches=top)


# Singleton shared across the app lifespan.
skill_retriever = SkillRetriever()
