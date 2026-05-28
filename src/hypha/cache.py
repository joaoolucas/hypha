"""Redis-backed cache + per-user rate limiter, with an in-memory fallback so the bot
still runs locally without Redis. See SPEC.md §9.

Concurrency-safe: the Redis client is only published to the module global *after* a
successful ping (guarded by a lock), and every Redis op is wrapped so a failure degrades
to the in-memory path instead of propagating into an analysis.
"""

from __future__ import annotations

import asyncio
import json
import time
from typing import Any

import structlog
from redis import asyncio as aioredis

from .config import get_settings

log = structlog.get_logger(__name__)

_redis: aioredis.Redis | None = None
_redis_disabled = False
_init_lock = asyncio.Lock()
_mem: dict[str, tuple[float, str]] = {}   # key -> (expires_at, json)
_mem_hits: dict[str, list[float]] = {}    # rate-limit buckets


async def _client() -> aioredis.Redis | None:
    global _redis, _redis_disabled
    if _redis_disabled:
        return None
    if _redis is not None:
        return _redis
    async with _init_lock:
        if _redis is not None or _redis_disabled:
            return _redis
        try:
            client = aioredis.from_url(get_settings().redis_url, decode_responses=True)
            await client.ping()
        except Exception as exc:  # noqa: BLE001 — degrade to in-memory, don't retry forever
            log.warning("redis_unavailable", error=str(exc))
            _redis_disabled = True
            return None
        _redis = client          # publish only after a successful ping
        return _redis


async def cache_get(key: str) -> Any | None:
    r = await _client()
    if r is not None:
        try:
            raw = await r.get(key)
            return json.loads(raw) if raw else None
        except Exception as exc:  # noqa: BLE001 — fall back to memory
            log.warning("cache_get_failed", error=str(exc))
    hit = _mem.get(key)
    if hit and hit[0] > time.time():
        return json.loads(hit[1])
    return None


async def cache_set(key: str, value: Any, ttl: int) -> None:
    payload = json.dumps(value, default=str)
    r = await _client()
    if r is not None:
        try:
            await r.set(key, payload, ex=ttl)
            return
        except Exception as exc:  # noqa: BLE001 — fall back to memory
            log.warning("cache_set_failed", error=str(exc))
    _mem[key] = (time.time() + ttl, payload)


async def rate_limit_ok(user_id: int, per_min: int | None = None) -> bool:
    """Sliding-window-ish limiter: <= per_min actions in the last 60s."""
    limit = per_min or get_settings().user_rate_per_min
    now = time.time()
    key = f"rl:{user_id}"
    r = await _client()
    if r is not None:
        try:
            count = await r.incr(key)
            if count == 1:
                await r.expire(key, 60)
            return count <= limit
        except Exception as exc:  # noqa: BLE001 — fall back to memory
            log.warning("rate_limit_failed", error=str(exc))
    bucket = [t for t in _mem_hits.get(key, []) if t > now - 60]
    bucket.append(now)
    _mem_hits[key] = bucket
    return len(bucket) <= limit
