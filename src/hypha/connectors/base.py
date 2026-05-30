"""Shared async HTTP client with retry/backoff and a tiny response cache.

Every connector subclasses this. Rate-limit (429) and transient 5xx/transport errors are
retried with exponential backoff; results can be cached by key+TTL.
"""

from __future__ import annotations

import asyncio
import time
from typing import Any

import httpx
import structlog
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from ..cache import cache_get, cache_set

log = structlog.get_logger(__name__)

# Per-source request pacing, shared across all instances of a connector (rate limits are
# enforced by the source per IP, and analysis spins up its own connector instances).
_pace_locks: dict[str, asyncio.Lock] = {}
_pace_last: dict[str, float] = {}


class ConnectorError(Exception):
    """Raised when a source cannot satisfy a request after retries."""


class RetryableHTTP(Exception):
    """Internal: signals a retryable HTTP condition (429 / 5xx)."""


class BaseConnector:
    name: str = "base"

    def __init__(
        self,
        base_url: str,
        headers: dict[str, str] | None = None,
        timeout: float = 15.0,
        min_interval: float = 0.0,
        retry_429: bool = True,
    ):
        self.base_url = base_url.rstrip("/")
        self.min_interval = min_interval     # min seconds between network calls (0 = unthrottled)
        # Retrying a rate-limited source just keeps its penalty hot. Sources we poll on a loop
        # (and can simply re-read next cycle) fail fast on 429 instead.
        self.retry_429 = retry_429
        self._client = httpx.AsyncClient(
            base_url=self.base_url,
            headers=headers or {},
            timeout=timeout,
            follow_redirects=True,
        )

    async def _pace(self) -> None:
        """Throttle real network calls to <= 1 / min_interval, shared across instances of this
        source, so bursts (e.g. fanning out over many pools) stay under the source's rate limit."""
        if self.min_interval <= 0:
            return
        lock = _pace_locks.setdefault(self.name, asyncio.Lock())
        async with lock:
            wait = self.min_interval - (time.monotonic() - _pace_last.get(self.name, 0.0))
            if wait > 0:
                await asyncio.sleep(wait)
            _pace_last[self.name] = time.monotonic()

    async def aclose(self) -> None:
        await self._client.aclose()

    @retry(
        retry=retry_if_exception_type((RetryableHTTP, httpx.TransportError)),
        wait=wait_exponential(multiplier=0.6, max=8),
        stop=stop_after_attempt(4),
        reraise=True,
    )
    async def _request(self, method: str, path: str, **kw: Any) -> Any:
        await self._pace()
        resp = await self._client.request(method, path, **kw)
        if resp.status_code == 429 and not self.retry_429:
            log.warning("http_rate_limited", source=self.name, path=path)
            raise ConnectorError(f"{self.name} 429 rate-limited: {path}")
        if resp.status_code == 429 or resp.status_code >= 500:
            log.warning("http_retryable", source=self.name, path=path, status=resp.status_code)
            raise RetryableHTTP(f"{self.name} {resp.status_code}")
        if resp.status_code >= 400:
            raise ConnectorError(f"{self.name} {resp.status_code} {path}: {resp.text[:200]}")
        if not resp.content:
            return {}
        return resp.json()

    async def get(
        self,
        path: str,
        *,
        params: dict | None = None,
        cache_key: str | None = None,
        ttl: int = 0,
    ) -> Any:
        if cache_key and ttl:
            cached = await cache_get(cache_key)
            if cached is not None:
                return cached
        data = await self._request("GET", path, params=params)
        if cache_key and ttl:
            await cache_set(cache_key, data, ttl)
        return data
