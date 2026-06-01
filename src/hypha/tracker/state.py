"""Tracker state — cursors, dedup, the followed-wallet list and promotion counters.

All cache-backed (Redis in prod, in-memory locally — see cache.py), so the single poller
process keeps its place across cycles and restarts without needing Postgres. Keys are namespaced
under `trk:`. Wallets are always keyed by raw `0:hex` form so a wallet matches regardless of
whether it arrived from Gecko (EQ…) or TonAPI (0:hex).
"""

from __future__ import annotations

import time

from ..cache import cache_get, cache_set
from ..models import HotPool, Trade
from ..utils import to_raw

_HOTPOOLS = "trk:hotpools"
_FOLLOWED = "trk:followed"
_CURSOR_TTL = 7 * 86400
_FOLLOWED_TTL = 90 * 86400


# ── hot-pool set (written by discovery, read by the trade loop) ────────────────
async def save_hot_pools(pools: list[HotPool]) -> None:
    await cache_set(_HOTPOOLS, [p.model_dump() for p in pools], _CURSOR_TTL)


async def load_hot_pools() -> list[HotPool]:
    raw = await cache_get(_HOTPOOLS) or []
    return [HotPool.model_validate(p) for p in raw]


# ── dedup: don't post the same op twice (across both sources) ──────────────────
async def is_new_op(trade: Trade, ttl: int) -> bool:
    """True the first time we see an op. Dedups by tx hash (exact, same source) and by a
    trader+token+side+time-bucket key (collapses the same swap arriving from both sources)."""
    keys = []
    if trade.tx_hash:
        keys.append(f"trk:tx:{trade.tx_hash}")
    bucket = int(trade.ts // 180) if trade.ts else 0
    keys.append(f"trk:op:{trade.trader}:{to_raw(trade.token_address)}:{trade.side.value}:{bucket}")
    for k in keys:
        if await cache_get(k):
            return False
    for k in keys:
        await cache_set(k, 1, ttl)
    return True


# ── per-pool / per-wallet watermarks (avoid replaying history on first sight) ──
async def _watermark(key: str, trades: list[Trade]) -> list[Trade]:
    cursor = await cache_get(key)
    max_ts = max((t.ts for t in trades), default=0.0)
    if cursor is None:                          # first sighting — set the line, replay nothing
        if max_ts:
            await cache_set(key, max_ts, _CURSOR_TTL)
        return []
    fresh = [t for t in trades if t.ts > cursor]
    if max_ts > cursor:
        await cache_set(key, max_ts, _CURSOR_TTL)
    return fresh


async def new_pool_trades(pool_address: str, trades: list[Trade]) -> list[Trade]:
    return await _watermark(f"trk:cursor:{pool_address}", trades)


async def new_wallet_trades(wallet_raw: str, trades: list[Trade]) -> list[Trade]:
    return await _watermark(f"trk:wcursor:{wallet_raw}", trades)


# ── followed wallets (the premium list we track everywhere) ────────────────────
async def followed_map() -> dict[str, dict]:
    return await cache_get(_FOLLOWED) or {}


async def is_followed(wallet_raw: str) -> bool:
    return wallet_raw in (await followed_map())


async def followed_count() -> int:
    return len(await followed_map())


async def followed_list() -> list[str]:
    return list((await followed_map()).keys())


async def add_followed(wallet_raw: str, *, reason: str = "promoted") -> None:
    m = await followed_map()
    if wallet_raw not in m:
        m[wallet_raw] = {"since": time.time(), "reason": reason}
        await cache_set(_FOLLOWED, m, _FOLLOWED_TTL)


async def remove_followed(wallet_raw: str) -> bool:
    m = await followed_map()
    if m.pop(wallet_raw, None) is not None:
        await cache_set(_FOLLOWED, m, _FOLLOWED_TTL)
        return True
    return False


# ── promotion counters: qualifying big buys per wallet within a rolling window ─
async def record_big_buy(wallet_raw: str, window: int) -> int:
    key = f"trk:buys:{wallet_raw}"
    now = time.time()
    arr = [x for x in (await cache_get(key) or []) if now - x <= window]
    arr.append(now)
    await cache_set(key, arr[-50:], window)
    return len(arr)


async def buy_count(wallet_raw: str, window: int) -> int:
    now = time.time()
    arr = [x for x in (await cache_get(f"trk:buys:{wallet_raw}") or []) if now - x <= window]
    return len(arr)


# ── trending: distinct whale buyers of a token within a rolling window ──────────
async def record_token_whale_buy(token_raw: str, trader_raw: str, usd: float, window: int) -> tuple[int, float]:
    """Record a whale buy of `token` and return (distinct whales, total USD) within the window.
    One entry per trader (latest buy wins), so the count is distinct wallets, not raw buys."""
    key = f"trk:trend:{token_raw}"
    now = time.time()
    arr = [x for x in (await cache_get(key) or [])
           if now - x.get("ts", 0) <= window and x.get("trader") != trader_raw]
    arr.append({"trader": trader_raw, "ts": now, "usd": round(usd, 2)})
    await cache_set(key, arr[-100:], window)
    return len(arr), round(sum(x.get("usd", 0.0) for x in arr), 2)


async def mark_trending(token_raw: str, cooldown: int) -> bool:
    """Claim the trending slot for a token: True once per `cooldown`, then False until it expires.
    Stops the same token being re-flagged on every subsequent whale buy."""
    key = f"trk:trended:{token_raw}"
    if await cache_get(key):
        return False
    await cache_set(key, time.time(), cooldown)
    return True
