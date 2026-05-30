"""Token-centric discovery — turn GeckoTerminal's trending/new pool feeds into a bounded set
of `HotPool`s to watch. This is the seed of the whale tracker: instead of maintaining a big
watchlist of wallets, we watch where the action is and catch *any* big buyer in the trade feed.

Pure-ish: `normalize_pools` is a deterministic transform (unit-tested); `hot_pools` just wires
it to the connector. Pools whose tradable side is TON or a stablecoin (e.g. a TON/USDT pool)
are dropped — there's no memecoin to alert on.
"""

from __future__ import annotations

import re

import structlog

from ..config import get_settings
from ..connectors.geckoterminal import GeckoTerminal
from ..models import HotPool
from .dex import _norm_venue

log = structlog.get_logger(__name__)

_TON_SYMBOLS = {"TON", "WTON", "PTON", "TONCOIN"}
_STABLE_SYMBOLS = {"USDT", "USD₮", "USDC", "USDE", "JUSDT", "JUSDC", "DAI", "TSUSDE", "USDA"}
_FEE_SUFFIX = re.compile(r"\s+\d+(\.\d+)?%$")   # DeDust names append a fee tier: "TON 0.25%"


def clean_symbol(sym: str) -> str:
    """Strip the DEX fee-tier suffix DeDust appends to pool symbols ('TON 0.1%' -> 'TON')."""
    return _FEE_SUFFIX.sub("", (sym or "").strip())


def is_stable(symbol: str) -> bool:
    return (symbol or "").upper() in _STABLE_SYMBOLS


def is_quote_asset(symbol: str) -> bool:
    """True for the 'money' side of a pair (TON / stables) — never the memecoin we alert on."""
    return (symbol or "").upper() in _TON_SYMBOLS | _STABLE_SYMBOLS


def _f(v) -> float:
    try:
        return float(v) if v is not None else 0.0
    except (TypeError, ValueError):
        return 0.0


def _addr_from_id(token_id: str) -> str:
    """'ton_EQAbc…' -> 'EQAbc…' (split on the first underscore only; friendly addrs contain '_')."""
    return token_id.split("_", 1)[1] if "_" in token_id else token_id


def _token_rel(pool: dict, side: str) -> str:
    data = (((pool.get("relationships") or {}).get(side) or {}).get("data") or {})
    return _addr_from_id(data.get("id", ""))


def normalize_pools(raw_pools: list[dict], reason: str) -> list[HotPool]:
    """Map raw Gecko pool objects to HotPools, picking the memecoin side. Drops pure
    quote/quote pairs (TON/USDT) where there's nothing to track."""
    out: list[HotPool] = []
    for p in raw_pools:
        a = p.get("attributes") or {}
        pool_addr = a.get("address") or _addr_from_id(p.get("id", ""))
        if not pool_addr:
            continue
        # "SHROOM / TON 0.25%" -> ("SHROOM", "TON")  (fee tier stripped)
        parts = [clean_symbol(s) for s in str(a.get("name", "")).split("/")]
        base_sym = parts[0] if parts else ""
        quote_sym = parts[1] if len(parts) > 1 else ""
        base_addr = _token_rel(p, "base_token")
        quote_addr = _token_rel(p, "quote_token")

        base_is_quote = is_quote_asset(base_sym)
        quote_is_quote = is_quote_asset(quote_sym)
        if base_is_quote and quote_is_quote:
            continue                                  # TON/USDT etc — no memecoin
        if base_is_quote and not quote_is_quote:      # rare: memecoin is the quote side
            token_addr, token_sym, paired, token_is_base = quote_addr, quote_sym, base_sym, False
        else:
            token_addr, token_sym, paired, token_is_base = base_addr, base_sym, quote_sym, True
        if not token_addr:
            continue

        out.append(HotPool(
            pool_address=pool_addr,
            token_address=token_addr,
            token_symbol=token_sym,
            quote_symbol=paired,
            token_is_base=token_is_base,
            venue=_norm_venue((((p.get("relationships") or {}).get("dex") or {}).get("data") or {}).get("id", "")),
            reserve_usd=_f(a.get("reserve_in_usd")),
            volume24h_usd=_f((a.get("volume_usd") or {}).get("h24")),
            reason=reason,
        ))
    return out


def dedupe_pools(pools: list[HotPool], limit: int) -> list[HotPool]:
    """Drop duplicate pools (keep first seen), sort by 24h volume, cap to `limit`."""
    seen: set[str] = set()
    unique: list[HotPool] = []
    for p in pools:
        if p.pool_address in seen:
            continue
        seen.add(p.pool_address)
        unique.append(p)
    unique.sort(key=lambda p: p.volume24h_usd, reverse=True)
    return unique[:limit]


async def hot_pools(gecko: GeckoTerminal, limit: int | None = None) -> list[HotPool]:
    """Fetch trending + new pools, normalize, dedupe and cap. Trending first so new pools
    only fill the long tail (trending wins on the volume sort anyway)."""
    cap = limit if limit is not None else get_settings().hot_pools_max
    pools: list[HotPool] = []
    for fetch, reason in ((gecko.trending_pools, "trending"), (gecko.new_pools, "new")):
        try:
            pools += normalize_pools(await fetch(), reason)
        except Exception as exc:  # noqa: BLE001 — one feed failing shouldn't sink discovery
            log.warning("hot_pool_feed_failed", reason=reason, error=str(exc))
    return dedupe_pools(pools, cap)
