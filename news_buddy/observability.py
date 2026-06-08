"""OpenTelemetry tracing setup via Arize Phoenix.

Opt-in: only activates when OTEL_TRACING is truthy. Must be called BEFORE the
pipeline's LangChain models are constructed, so the OpenInference LangChain
instrumentor can hook every LLM call.
"""

from __future__ import annotations

import os


def setup_tracing() -> None:
    """Register OTel + Phoenix tracing if OTEL_TRACING is enabled."""
    if os.getenv("OTEL_TRACING", "").lower() not in ("1", "true", "yes"):
        return

    try:
        from phoenix.otel import register
    except Exception as exc:  # noqa: BLE001 — fail-soft, never break a run
        print(f"[otel] tracing requested but Phoenix not available: {exc}")
        return

    register(
        project_name=os.getenv("PHOENIX_PROJECT", "news-buddy-langgraph"),
        auto_instrument=True,  # enables the installed OpenInference langchain instrumentor
    )
    endpoint = os.getenv("PHOENIX_COLLECTOR_ENDPOINT", "http://localhost:6006")
    print(f"🔭 OTel tracing on → Phoenix UI at {endpoint}")
