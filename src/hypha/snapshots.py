"""Lightweight holder-count time-series for Holder Growth.

TonAPI only exposes the *current* holder count, so growth ("+12 since 7m ago") needs us to
keep our own snapshots. We append (ts, holders) per token on each fresh analysis and diff
against the most recent prior snapshot. Backed by the shared cache (Redis in prod; in-memory
locally), so it accumulates over time — it returns None until at least one prior snapshot
exists and the count actually moved.
"""

from __future__ import annotations

import time

from .cache import cache_get, cache_set

_SNAP_TTL = 7 * 86400   # keep a week of snapshots
_MAX_SNAPS = 300
_MIN_GAP = 60           # ignore snapshots younger than this (avoid noisy back-to-back diffs)


async def record_and_growth(token: str, holders_now: int) -> tuple[int | None, float | None]:
    """Record the current count and return (delta, seconds_since) vs the most recent prior
    snapshot older than _MIN_GAP. Returns (None, None) until such a snapshot exists."""
    if not holders_now:
        return None, None
    key = f"snap:{token}"
    snaps = await cache_get(key) or []
    now = time.time()

    prior = [s for s in snaps if now - s[0] >= _MIN_GAP]
    delta = secs = None
    if prior:
        last = max(prior, key=lambda s: s[0])   # most recent prior snapshot
        delta = holders_now - int(last[1])
        secs = now - last[0]

    snaps.append([now, holders_now])
    await cache_set(key, snaps[-_MAX_SNAPS:], _SNAP_TTL)
    return delta, secs
