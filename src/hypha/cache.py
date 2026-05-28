"""Redis-backed cache + per-user rate limiter, with an in-memory fallback so the bot
still runs locally without Redis. See SPEC.md §9."""

from __future__ import annotations

import json
import time
from typing import Any

import structlog
from redis import asyncio as aioredis

from .config import get_settings

log = structlog.get_logger(__name__)

_redis: aioredis.Redis | None = None
_mem: dict[str, tuple[float, str]] = {}   # key -> (expires_at, json)
_mem_hits: dict[str, list[float]] = {}    # rate-limit buckets


async def _client() -> aioredis.Redis | None:
    global _redis
    if _redis is not None:
        return _redis
    try:
        _redis = aioredis.from_url(get_settings().redis_url, decode_responses=True)
        await _redis.ping()
        return _redis
    except Exception as exc:  # noqa: BLE001 — degrade to in-memory
        log.warning("redis_unavailable", error=str(exc))
        _redis = None
        return None


async def cache_get(key: str) -> Any | None:
    r = await _client()
    if r is not None:
        raw = await r.get(key)
        return json.loads(raw) if raw else None
    hit = _mem.get(key)
    if hit and hit[0] > time.time():
        return json.loads(hit[1])
    return None


async def cache_set(key: str, value: Any, ttl: int) -> None:
    payload = json.dumps(value, default=str)
    r = await _client()
    if r is not None:
        await r.set(key, payload, ex=ttl)
    else:
        _mem[key] = (time.time() + ttl, payload)


async def rate_limit_ok(user_id: int, per_min: int | None = None) -> bool:
    """Sliding-window-ish limiter: <= per_min actions in the last 60s."""
    limit = per_min or get_settings().user_rate_per_min
    now = time.time()
    key = f"rl:{user_id}"
    r = await _client()
    if r is not None:
        count = await r.incr(key)
        if count == 1:
            await r.expire(key, 60)
        return count <= limit
    bucket = [t for t in _mem_hits.get(key, []) if t > now - 60]
    bucket.append(now)
    _mem_hits[key] = bucket
    return len(bucket) <= limit
