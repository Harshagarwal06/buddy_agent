"""Rubric-based quality scoring for article summaries."""

from __future__ import annotations

import re

_VAGUE_PHRASES = [
    "new development",
    "according to reports",
    "it was reported",
    "sources say",
    "has been announced",
    "significant implications",
    "could change the landscape",
    "marks a major step",
]

_THIN_OPENERS = (
    "it ",
    "this ",
    "they ",
    "he ",
    "she ",
    "his ",
    "her ",
    "the company ",
    "the organization ",
    "the decision ",
    "the deal ",
)

_TITLE_STOPWORDS = {
    "about",
    "after",
    "against",
    "from",
    "into",
    "over",
    "that",
    "their",
    "this",
    "through",
    "under",
    "with",
    "will",
    "your",
}


def _words(text: str) -> list[str]:
    normalized = text.lower().replace("’", "'")
    words = re.findall(r"[a-z0-9]+(?:['-][a-z0-9]+)?", normalized)
    return [word[:-2] if word.endswith("'s") else word for word in words]


def _sentence_count(text: str) -> int:
    return len(
        [
            sentence
            for sentence in re.split(r"(?<=[.!?])\s+", text.strip())
            if len(_words(sentence)) >= 3
        ]
    )


def _covers_title_subject(title: str, summary: str) -> bool:
    title_words = {
        word
        for word in _words(title)
        if len(word) >= 4 and word not in _TITLE_STOPWORDS
    }
    return not title_words or bool(title_words.intersection(_words(summary)))


class RubricMiddleware:
    """
    Scores a summarizer output on four dimensions and adjusts importance.
    Pure heuristics — no LLM calls.

    Dimensions:
      specificity  (1-3): penalises boilerplate vague phrases
      completeness (1-3): checks word count and sentence development
      context      (1-3): checks subject identification and self-containment
      tag_quality  (0-1): whether meaningful (non-generic) tags are present

    passed = specificity >= 2 AND completeness >= 2 AND context >= 2
    """

    def __init__(
        self,
        min_length: int = 60,
        min_words: int | None = None,
        importance_penalty: int = 2,
    ) -> None:
        self._min_length = min_length
        self._min_words = min_words or max(20, round(min_length / 5))
        self._penalty = importance_penalty

    def score(self, enriched: dict) -> dict:
        """Return enriched item with 'rubric' key added and importance adjusted."""
        summary = enriched.get("summary", "")
        tags = enriched.get("tags", [])
        importance = enriched.get("importance", 3)
        title = str(enriched.get("title", ""))

        vague_hits = sum(1 for p in _VAGUE_PHRASES if p in summary.lower())
        specificity = max(1, 3 - vague_hits)

        word_count = len(_words(summary))
        sentence_count = _sentence_count(summary)
        if len(summary) < self._min_length or word_count < self._min_words:
            completeness = 1
        elif sentence_count < 2:
            completeness = 1
        elif word_count < self._min_words + 25 or sentence_count < 3:
            completeness = 2
        else:
            completeness = 3

        starts_thin = summary.strip().lower().startswith(_THIN_OPENERS)
        covers_subject = _covers_title_subject(title, summary)
        if starts_thin or not covers_subject:
            context = 1
        elif sentence_count >= 3 and word_count >= self._min_words:
            context = 3
        else:
            context = 2

        meaningful_tags = [t for t in tags if t not in ("world", "other", "")]
        tag_quality = 1 if meaningful_tags else 0

        passed = specificity >= 2 and completeness >= 2 and context >= 2

        if not passed:
            importance = max(1, importance - self._penalty)
        elif specificity == 2 and completeness == 2 and context == 2:
            importance = max(1, importance - 1)

        return {
            **enriched,
            "importance": importance,
            "rubric": {
                "specificity": specificity,
                "completeness": completeness,
                "context": context,
                "tag_quality": tag_quality,
                "word_count": word_count,
                "sentence_count": sentence_count,
                "passed": passed,
            },
        }
