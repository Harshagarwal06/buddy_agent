"""Rubric-based quality scoring for article summaries."""

from __future__ import annotations

_VAGUE_PHRASES = [
    "new development", "announced that", "according to reports",
    "it was reported", "sources say", "has been announced",
    "a new", "the company", "the organization",
]


class RubricMiddleware:
    """
    Scores a summarizer output on three dimensions and adjusts importance.
    Pure heuristics — no LLM calls.

    Dimensions:
      specificity  (1-3): penalises boilerplate vague phrases
      completeness (1-3): proxy via summary character length
      tag_quality  (0-1): whether meaningful (non-generic) tags are present

    passed = specificity >= 2 AND completeness >= 2
    """

    def __init__(self, min_length: int = 60, importance_penalty: int = 2) -> None:
        self._min_length = min_length
        self._penalty = importance_penalty

    def score(self, enriched: dict) -> dict:
        """Return enriched item with 'rubric' key added and importance adjusted."""
        summary = enriched.get("summary", "")
        tags = enriched.get("tags", [])
        importance = enriched.get("importance", 3)

        vague_hits = sum(1 for p in _VAGUE_PHRASES if p in summary.lower())
        specificity = max(1, 3 - vague_hits)

        completeness = (
            1 if len(summary) < self._min_length
            else 2 if len(summary) < self._min_length * 2
            else 3
        )

        meaningful_tags = [t for t in tags if t not in ("world", "other", "")]
        tag_quality = 1 if meaningful_tags else 0

        passed = specificity >= 2 and completeness >= 2

        if not passed:
            importance = max(1, importance - self._penalty)
        elif specificity == 2 and completeness == 2:
            importance = max(1, importance - 1)

        return {
            **enriched,
            "importance": importance,
            "rubric": {
                "specificity": specificity,
                "completeness": completeness,
                "tag_quality": tag_quality,
                "passed": passed,
            },
        }
