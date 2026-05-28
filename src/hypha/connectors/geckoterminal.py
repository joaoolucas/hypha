"""GeckoTerminal — price, FDV, market cap, liquidity and volume for a TON token.

  GET /networks/ton/tokens/{addr}             token market data + top pools
  GET /networks/ton/tokens/{addr}/pools       pools for the token
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
        super().__init__(get_settings().geckoterminal_base, headers={"Accept": "application/json"})

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
