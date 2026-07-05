"""LLM factory — single place to swap providers.

Supported providers (set via config.llm.provider):
  - "google"  → Gemini via langchain-google-genai (free tier; lean usage)
  - "huggingface" → Hugging Face Inference Providers / endpoint
  - "ollama"  → local models via langchain-ollama
"""

from __future__ import annotations

from dataclasses import dataclass
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


# ── Hugging Face ──────────────────────────────────────────────────────────────
@dataclass
class _ChatResponse:
    content: str
    usage_metadata: dict


class _HuggingFaceChatModel:
    """Small LangChain-like adapter for huggingface_hub chat completions."""

    def __init__(self, llm: dict, model: str, json_mode: bool = False) -> None:
        from huggingface_hub import InferenceClient

        token = (
            os.getenv("HF_TOKEN", "").strip()
            or os.getenv("HUGGINGFACEHUB_API_TOKEN", "").strip()
        )
        if not token:
            raise RuntimeError(
                "HF_TOKEN is not set. Create a Hugging Face access token and add "
                "HF_TOKEN=... to .env."
            )

        provider = llm.get("hf_provider", "auto")
        self._client = InferenceClient(
            model=model,
            provider=provider,
            token=token,
            timeout=llm.get("timeout", 60),
        )
        self._model = model
        self._json_mode = json_mode
        self._temperature = llm.get("temperature", 0.2)
        self._max_tokens = llm.get("max_tokens", 512)
        self._rate_limiter = None
        rpm = llm.get("requests_per_minute")
        if rpm:
            from langchain_core.rate_limiters import InMemoryRateLimiter

            self._rate_limiter = InMemoryRateLimiter(
                requests_per_second=rpm / 60.0,
                check_every_n_seconds=0.5,
                max_bucket_size=1,
            )

    def invoke(self, messages) -> _ChatResponse:
        if self._rate_limiter:
            self._rate_limiter.acquire(blocking=True)

        kwargs = {
            "messages": [_to_hf_message(message) for message in messages],
            "model": self._model,
            "temperature": self._temperature,
            "max_tokens": self._max_tokens,
        }
        if self._json_mode:
            kwargs["response_format"] = {"type": "json_object"}

        response = self._client.chat_completion(**kwargs)
        choice = response.choices[0]
        content = getattr(choice.message, "content", "") or ""
        usage = _usage_metadata(getattr(response, "usage", None))
        return _ChatResponse(content=content, usage_metadata=usage)


def _to_hf_message(message) -> dict:
    role = getattr(message, "type", "")
    if role == "human":
        role = "user"
    elif role == "ai":
        role = "assistant"
    elif role != "system":
        role = "user"
    return {"role": role, "content": str(getattr(message, "content", ""))}


def _usage_metadata(usage) -> dict:
    if not usage:
        return {}
    if isinstance(usage, dict):
        input_tokens = usage.get("prompt_tokens") or usage.get("input_tokens") or 0
        output_tokens = usage.get("completion_tokens") or usage.get("output_tokens") or 0
    else:
        input_tokens = getattr(usage, "prompt_tokens", 0) or getattr(usage, "input_tokens", 0)
        output_tokens = getattr(usage, "completion_tokens", 0) or getattr(usage, "output_tokens", 0)
    return {"input_tokens": input_tokens, "output_tokens": output_tokens}


def _build_huggingface(llm: dict, model: str, json_mode: bool = False):
    return _HuggingFaceChatModel(llm, model, json_mode=json_mode)


# ── Dispatch ──────────────────────────────────────────────────────────────────
def _build(config: dict, model_key: str, json_mode: bool = False):
    llm = config["llm"]
    provider = llm.get("provider", "ollama").lower()
    model = llm[model_key]
    if provider == "google":
        return _build_google(llm, model, json_mode=json_mode)
    if provider in {"huggingface", "hf"}:
        return _build_huggingface(llm, model, json_mode=json_mode)
    if provider == "ollama":
        return _build_ollama(llm, model)
    raise RuntimeError(
        f"Unknown llm.provider '{provider}' (use 'google', 'huggingface', or 'ollama')."
    )


def get_main_model(config: dict):
    return _build(config, "main_model")


def get_sub_model(config: dict):
    # json_mode=True: forces raw JSON output, eliminates code-fence parse failures
    return _build(config, "sub_model", json_mode=True)
