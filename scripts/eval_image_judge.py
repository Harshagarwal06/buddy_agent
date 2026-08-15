"""Vision judge for generated article illustrations.

Opt-in: makes real API calls and is never run by CI. The model was verified
against the account before being pinned; see the design spec.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass

DEFAULT_JUDGE_MODEL = "gemini-3.5-flash"

JUDGE_PROMPT = (
    "You are grading an illustration against a style contract. "
    "Answer ONLY with raw JSON, no code fences, with exactly these keys:\n"
    '{"has_text": bool, "has_person": bool, "object_group_count": int}\n'
    "has_text: true if ANY letters, words, numbers, or text-like glyphs appear "
    "anywhere in the image, including garbled or nonsense lettering.\n"
    "has_person: true if any human figure, face, or body part appears.\n"
    "object_group_count: how many distinct symbolic object groups are shown."
)

_REQUIRED = ("has_text", "has_person", "object_group_count")


@dataclass
class JudgeVerdict:
    has_text: bool | None = None
    has_person: bool | None = None
    object_group_count: int | None = None
    error: str = ""


def parse_verdict(text: str) -> JudgeVerdict:
    """Parse a judge response. Any deviation yields an error verdict, never a clean one."""
    cleaned = str(text).strip()
    if cleaned.startswith("```"):
        cleaned = "\n".join(
            line for line in cleaned.splitlines() if not line.strip().startswith("```")
        ).strip()
    try:
        data = json.loads(cleaned)
    except json.JSONDecodeError as exc:
        return JudgeVerdict(error=f"invalid JSON: {exc}")
    if not isinstance(data, dict):
        return JudgeVerdict(error="response was not a JSON object")

    missing = [key for key in _REQUIRED if key not in data]
    if missing:
        return JudgeVerdict(error=f"missing keys: {', '.join(missing)}")
    if not isinstance(data["has_text"], bool) or not isinstance(data["has_person"], bool):
        return JudgeVerdict(error="has_text and has_person must be booleans")
    if not isinstance(data["object_group_count"], int) or isinstance(
        data["object_group_count"], bool
    ):
        return JudgeVerdict(error="object_group_count must be an integer")

    return JudgeVerdict(
        has_text=data["has_text"],
        has_person=data["has_person"],
        object_group_count=data["object_group_count"],
    )


class ImageJudge:
    """Thin wrapper over the Gemini vision API. Never raises; returns error verdicts."""

    def __init__(self, model: str = DEFAULT_JUDGE_MODEL, client=None) -> None:
        self._model = model
        self._client = client

    def _ensure_client(self):
        if self._client is None:
            from google import genai

            api_key = os.getenv("GOOGLE_API_KEY", "").strip()
            if not api_key:
                raise RuntimeError(
                    "GOOGLE_API_KEY is not set; the image judge requires it."
                )
            self._client = genai.Client(api_key=api_key)
        return self._client

    def judge(self, image_bytes: bytes, mime_type: str = "image/png") -> JudgeVerdict:
        from google.genai import types

        try:
            client = self._ensure_client()
            response = client.models.generate_content(
                model=self._model,
                contents=[
                    types.Part.from_bytes(data=image_bytes, mime_type=mime_type),
                    JUDGE_PROMPT,
                ],
                config=types.GenerateContentConfig(
                    response_mime_type="application/json"
                ),
            )
        except Exception as exc:  # noqa: BLE001 - every failure mode is data here
            return JudgeVerdict(error=f"{type(exc).__name__}: {str(exc)[:160]}")
        return parse_verdict(response.text or "")
