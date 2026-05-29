"""Lightweight holder-count time-series for Holder Growth.

TonAPI only exposes the *current* holder count, so growth ("+140 in 24h") needs us to keep our
own snapshots. We append (ts, holders) per token on each fresh analysis and diff against the
nearest older snapshot. Backed by the shared cache (Redis in prod; in-memory locally), so it
accumulates over time and per popular token — it returns None until enough history exists.
"""

from __future__ import annotations

import time

from .cache import cache_get, cache_set

_SNAP_TTL = 7 * 86400   # keep a week of snapshots
_MAX_SNAPS = 300


def _delta(snaps: list, now: float, holders_now: int, target: float, lo: float, hi: float) -> int | None:
    """Holder delta vs the snapshot whose age is closest to `target`, within [lo, hi] seconds."""
    candidates = [s for s in snaps if lo <= now - s[0] <= hi]
    if not candidates:
        return None
    best = min(candidates, key=lambda s: abs((now - s[0]) - target))
    return holders_now - int(best[1])


async def record_and_growth(token: str, holders_now: int) -> tuple[int | None, int | None]:
    """Record the current count and return (growth_1h, growth_24h) vs prior snapshots."""
    if not holders_now:
        return None, None
    key = f"snap:{token}"
    snaps = await cache_get(key) or []
    now = time.time()

    g1 = _delta(snaps, now, holders_now, target=3600, lo=1800, hi=7200)        # ~1h (30m–2h)
    g24 = _delta(snaps, now, holders_now, target=86400, lo=43200, hi=129600)   # ~24h (12h–36h)

    snaps.append([now, holders_now])
    await cache_set(key, snaps[-_MAX_SNAPS:], _SNAP_TTL)
    return g1, g24
