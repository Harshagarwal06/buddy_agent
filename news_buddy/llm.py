"""LLM factory — single place to swap providers.

Supported providers (set via config.llm.provider):
  - "google"  → Gemini via langchain-google-genai (free tier; lean usage)
  - "ollama"  → local models via langchain-ollama
"""

from __future__ import annotations

import os

import httpx


# ── Ollama ────────────────────────────────────────────────────────────────────
def _verify_ollama(base_url: str, model: str) -> None:
    try:
        resp = httpx.get(f"{base_url}/api/tags", timeout=5.0)
        resp.raise_for_status()
        names = [m["name"] for m in resp.json().get("models", [])]
        if not any(n.startswith(model.split(":")[0]) for n in names):
            raise RuntimeError(
                f"Model '{model}' not found in Ollama at {base_url}. "
                f"Run: ollama pull {model}"
            )
    except httpx.ConnectError:
        raise RuntimeError(f"Cannot reach Ollama at {base_url}. Run: ollama serve")


def _build_ollama(llm: dict, model: str):
    from langchain_ollama import ChatOllama

    base_url = llm["base_url"]
    _verify_ollama(base_url, model)
    return ChatOllama(
        model=model,
        base_url=base_url,
        temperature=llm.get("temperature", 0.2),
    )


# ── Google Gemini (free tier) ─────────────────────────────────────────────────
def _google_rate_limiter(llm: dict):
    """Throttle to stay under the free-tier requests/min cap (default 9/min)."""
    from langchain_core.rate_limiters import InMemoryRateLimiter

    rpm = llm.get("requests_per_minute", 9)
    return InMemoryRateLimiter(
        requests_per_second=rpm / 60.0,
        check_every_n_seconds=0.5,
        max_bucket_size=1,
    )


def _build_google(llm: dict, model: str, json_mode: bool = False):
    from langchain_google_genai import ChatGoogleGenerativeAI

    api_key = os.getenv("GOOGLE_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError(
            "GOOGLE_API_KEY is not set. Get a free key at "
            "https://aistudio.google.com/apikey and add it to .env."
        )
    # json_mode forces Gemini to return raw JSON — no code fences, no parse failures
    extra = {"model_kwargs": {"response_mime_type": "application/json"}} if json_mode else {}
    return ChatGoogleGenerativeAI(
        model=model,
        temperature=llm.get("temperature", 0.2),
        google_api_key=api_key,
        rate_limiter=_google_rate_limiter(llm),
        max_retries=3,
        **extra,
    )


# ── Dispatch ──────────────────────────────────────────────────────────────────
def _build(config: dict, model_key: str, json_mode: bool = False):
    llm = config["llm"]
    provider = llm.get("provider", "ollama").lower()
    model = llm[model_key]
    if provider == "google":
        return _build_google(llm, model, json_mode=json_mode)
    if provider == "ollama":
        return _build_ollama(llm, model)
    raise RuntimeError(f"Unknown llm.provider '{provider}' (use 'google' or 'ollama').")


def get_main_model(config: dict):
    return _build(config, "main_model")


def get_sub_model(config: dict):
    # json_mode=True: forces raw JSON output, eliminates code-fence parse failures
    return _build(config, "sub_model", json_mode=True)
