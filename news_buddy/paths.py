"""Paths for source checkouts and installed News Buddy packages."""

from __future__ import annotations

import os
from pathlib import Path


_PACKAGE_ROOT = Path(__file__).resolve().parent
_SOURCE_ROOT = _PACKAGE_ROOT.parent
_BUNDLED_ROOT = _PACKAGE_ROOT / "resources"


def runtime_root() -> Path:
    """Return the writable root for state, RAG, and knowledge-base data."""
    configured = os.getenv("NEWS_BUDDY_HOME", "").strip()
    if configured:
        return Path(configured).expanduser().resolve()
    if (_SOURCE_ROOT / "config.yaml").is_file():
        return _SOURCE_ROOT
    return Path.cwd().resolve()


def resource_path(relative_path: str | Path) -> Path:
    """Resolve a packaged resource while preserving checkout overrides."""
    relative = Path(relative_path)
    if relative.is_absolute():
        return relative

    source_candidate = _SOURCE_ROOT / relative
    if source_candidate.exists():
        return source_candidate

    runtime_candidate = runtime_root() / relative
    if runtime_candidate.exists():
        return runtime_candidate

    return _BUNDLED_ROOT / relative


def default_config_path() -> Path:
    """Use a checkout-local config when present, otherwise the bundled default."""
    local_config = runtime_root() / "config.yaml"
    if local_config.is_file():
        return local_config
    return resource_path("config.yaml")
