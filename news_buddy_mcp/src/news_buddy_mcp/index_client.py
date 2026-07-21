"""Fetches and caches the public digest archive index from gh-pages."""

from __future__ import annotations

import time
from dataclasses import dataclass

import httpx

_DEFAULT_TTL_SECONDS = 3600


@dataclass
class _CacheEntry:
    data: object
    fetched_at: float


class ArchiveIndexClient:
    """Reads index.json and per-day JSON files from the published archive.

    Caches responses in memory for ttl_seconds. On fetch failure, serves the
    last good cached copy (marking it stale) rather than raising, unless
    there's no cache yet, in which case the original error propagates.
    """

    def __init__(
        self,
        base_url: str,
        ttl_seconds: int = _DEFAULT_TTL_SECONDS,
        client: httpx.Client | None = None,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._ttl = ttl_seconds
        self._client = client or httpx.Client(timeout=15)
        self._cache: dict[str, _CacheEntry] = {}

    def _get_json(self, path: str) -> tuple[object, bool]:
        now = time.monotonic()
        cached = self._cache.get(path)
        if cached and now - cached.fetched_at < self._ttl:
            return cached.data, False

        try:
            resp = self._client.get(f"{self._base_url}/{path}")
            resp.raise_for_status()
            data = resp.json()
            self._cache[path] = _CacheEntry(data=data, fetched_at=now)
            return data, False
        except (httpx.HTTPError, ValueError):
            if cached:
                return cached.data, True
            raise

    def manifest(self) -> tuple[list[str], bool]:
        data, stale = self._get_json("index.json")
        return data.get("dates", []), stale

    def day(self, date_str: str) -> tuple[list[dict] | None, bool]:
        try:
            return self._get_json(f"{date_str}.json")
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code == 404:
                return None, False
            raise
