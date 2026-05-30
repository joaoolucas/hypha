"""GeckoTerminal — price, FDV, market cap, liquidity and volume for a TON token, plus the
trending/new pool feeds and per-pool trade stream that power the whale-tracker channel.

  GET /networks/ton/tokens/{addr}             token market data + top pools
  GET /networks/ton/tokens/{addr}/pools       pools for the token
  GET /networks/ton/trending_pools            hottest pools (discovery seed)
  GET /networks/ton/new_pools                 freshest pools (discovery seed)
  GET /networks/ton/pools/{pool}/trades       recent swaps for a pool (the alert feed)
~30 req/min unauthenticated, so responses are cached.
"""

from __future__ import annotations

from ..config import get_settings
from .base import BaseConnector


def _f(v) -> float | None:
    try:
        return float(v) if v is not None else None
    except (TypeError, ValueError):
        return None


class GeckoTerminal(BaseConnector):
    name = "geckoterminal"

    def __init__(self) -> None:
        s = get_settings()
        super().__init__(
            s.geckoterminal_base,
            headers={"Accept": "application/json"},
            min_interval=s.gecko_min_interval,
            retry_429=False,     # polled on a loop; skip a rate-limited pool, re-read next cycle
        )

    async def token_market(self, addr: str) -> dict:
        """Return {price_usd, fdv_usd, market_cap_usd, liquidity_usd, volume24h_usd}."""
        d = await self.get(
            f"/networks/ton/tokens/{addr}",
            cache_key=f"gt:token:{addr}",
            ttl=120,
        )
        attr = (d.get("data", {}) or {}).get("attributes", {}) or {}
        return {
            "price_usd": _f(attr.get("price_usd")),
            "fdv_usd": _f(attr.get("fdv_usd")),
            "market_cap_usd": _f(attr.get("market_cap_usd")) or _f(attr.get("fdv_usd")),
            "liquidity_usd": _f(attr.get("total_reserve_in_usd")),
            "volume24h_usd": _f((attr.get("volume_usd") or {}).get("h24")),
        }

    async def token_pools(self, addr: str) -> list[dict]:
        d = await self.get(
            f"/networks/ton/tokens/{addr}/pools",
            cache_key=f"gt:pools:{addr}",
            ttl=120,
        )
        return d.get("data", []) or []

    async def trending_pools(self) -> list[dict]:
        """Hottest TON pools (by recent volume/movement). Discovery seed for the tracker."""
        d = await self.get(
            "/networks/ton/trending_pools",
            params={"duration": "1h"},
            cache_key="gt:trending:ton",
            ttl=300,
        )
        return d.get("data", []) or []

    async def new_pools(self) -> list[dict]:
        """Freshest TON pools — where early whale entries show up first."""
        d = await self.get(
            "/networks/ton/new_pools",
            cache_key="gt:new:ton",
            ttl=300,
        )
        return d.get("data", []) or []

    async def pool_trades(self, pool_address: str, min_usd: float = 0.0) -> list[dict]:
        """Recent swaps for a pool (last 24h, newest first). `min_usd` pushes the size filter
        server-side so we only pull trades large enough to possibly alert on. Not cached —
        the poller wants fresh trades each cycle."""
        params: dict = {}
        if min_usd > 0:
            params["trade_volume_in_usd_greater_than"] = min_usd
        d = await self.get(f"/networks/ton/pools/{pool_address}/trades", params=params)
        return d.get("data", []) or []
