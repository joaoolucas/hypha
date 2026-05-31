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
from ..utils import to_friendly
from .dex import _norm_venue

log = structlog.get_logger(__name__)

# TON + wrapped/staked TON (LSTs) — treated as "money", never the memecoin we alert on.
_TON_SYMBOLS = {"TON", "WTON", "PTON", "TONCOIN", "TSTON", "STTON", "HTON", "WSTON", "USTON"}
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


def _pick_token(base_sym: str, base_addr: str, quote_sym: str, quote_addr: str):
    """Pick the memecoin side of a pair → (token_addr, token_sym, paired_sym, token_is_base).
    Returns None for pure quote/quote pairs (TON/USDT) or when the token address is missing."""
    base_q, quote_q = is_quote_asset(base_sym), is_quote_asset(quote_sym)
    if base_q and quote_q:
        return None
    if base_q and not quote_q:                      # rare: memecoin is the quote side
        token_addr, token_sym, paired, is_base = quote_addr, quote_sym, base_sym, False
    else:
        token_addr, token_sym, paired, is_base = base_addr, base_sym, quote_sym, True
    return (token_addr, token_sym, paired, is_base) if token_addr else None


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
        picked = _pick_token(base_sym, _token_rel(p, "base_token"),
                             quote_sym, _token_rel(p, "quote_token"))
        if not picked:
            continue
        token_addr, token_sym, paired, token_is_base = picked

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


def normalize_dexscreener(pairs: list[dict], reason: str = "dexscreener") -> list[HotPool]:
    """Map DexScreener search pairs (TON) to HotPools — same memecoin-side logic, different shape.
    Surfaces launchpad DEXes Gecko misses (e.g. dexId 'uranus')."""
    out: list[HotPool] = []
    for p in pairs:
        pool_addr = p.get("pairAddress")
        if not pool_addr:
            continue
        base = p.get("baseToken") or {}
        quote = p.get("quoteToken") or {}
        picked = _pick_token(
            clean_symbol(base.get("symbol", "")), base.get("address", ""),
            clean_symbol(quote.get("symbol", "")), quote.get("address", ""),
        )
        if not picked:
            continue
        token_addr, token_sym, paired, token_is_base = picked
        out.append(HotPool(
            pool_address=pool_addr,
            token_address=to_friendly(token_addr, bounceable=True),  # DexScreener gives raw 0:hex

            token_symbol=token_sym,
            quote_symbol=paired,
            token_is_base=token_is_base,
            venue=_norm_venue(p.get("dexId", "")),
            reserve_usd=_f((p.get("liquidity") or {}).get("usd")),
            volume24h_usd=_f((p.get("volume") or {}).get("h24")),
            reason=reason,
        ))
    return out


def _dedupe(pools: list[HotPool]) -> list[HotPool]:
    """Drop duplicate pool addresses, keeping first-seen (preserves feed order)."""
    seen: set[str] = set()
    out: list[HotPool] = []
    for p in pools:
        if p.pool_address not in seen:
            seen.add(p.pool_address)
            out.append(p)
    return out


def dedupe_pools(pools: list[HotPool], limit: int) -> list[HotPool]:
    """Dedupe, sort by 24h volume, cap to `limit`."""
    return sorted(_dedupe(pools), key=lambda p: p.volume24h_usd, reverse=True)[:limit]


async def _gather(feeds: list[tuple]) -> list[HotPool]:
    out: list[HotPool] = []
    for coro, reason in feeds:
        try:
            out += normalize_pools(await coro, reason)
        except Exception as exc:  # noqa: BLE001 — one feed/page failing shouldn't sink discovery
            log.warning("hot_pool_feed_failed", reason=reason, error=str(exc))
    return out


async def hot_pools(gecko: GeckoTerminal, limit: int | None = None, dexscreener=None) -> list[HotPool]:
    """Build the watch set so fresh/launchpad tokens aren't crowded out by volume:
      • DexScreener launchpad pairs (e.g. Uranus) + freshest Gecko launches — reserved, kept
        regardless of volume
      • most actively traded (Gecko top-volume + trending) — fills the rest, sorted by volume
    StonksLabs (trades on DeDust from launch) shows up in the Gecko new feed; Uranus comes via
    DexScreener, which Gecko doesn't index."""
    s = get_settings()
    cap = limit if limit is not None else s.hot_pools_max
    reserve = min(s.new_pools_reserve, cap)

    ds_pools: list[HotPool] = []
    if dexscreener is not None:
        for q in s.dexscreener_query_list:
            try:
                ds_pools += normalize_dexscreener(await dexscreener.search_ton(q))
            except Exception as exc:  # noqa: BLE001 — a failed search shouldn't sink discovery
                log.warning("dexscreener_search_failed", query=q, error=str(exc))
    ds_pools = _dedupe(ds_pools)

    fresh = _dedupe(await _gather([
        (gecko.new_pools(1), "new"), (gecko.new_pools(2), "new"), (gecko.new_pools(3), "new"),
    ]))
    # reserve = all launchpad pairs + freshest launches up to the reserve budget
    priority = _dedupe(ds_pools + fresh)[: max(reserve, len(ds_pools))]
    seen = {p.pool_address for p in priority}

    volume = await _gather([
        (gecko.top_pools(1), "top"), (gecko.top_pools(2), "top"),
        (gecko.trending_pools(1), "trending"), (gecko.trending_pools(2), "trending"),
    ])
    by_volume = [p for p in dedupe_pools(volume, cap) if p.pool_address not in seen]
    return (priority + by_volume)[:cap]
