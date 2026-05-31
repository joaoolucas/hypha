"""DexScreener — a second discovery source for TON pools that GeckoTerminal misses, notably
the Uranus launchpad DEX (dexId "uranus"). We only use its search endpoint for discovery;
trades still come from TonAPI.

  GET /latest/dex/search?q=<term>     pairs matching the term (we filter to chainId == "ton")
60 req/min; we hit it a couple of times per discovery cycle, so it's well within budget.
"""

from __future__ import annotations

from ..config import get_settings
from .base import BaseConnector


class DexScreener(BaseConnector):
    name = "dexscreener"

    def __init__(self) -> None:
        super().__init__(
            get_settings().dexscreener_base,
            headers={"Accept": "application/json"},
            retry_429=False,
        )

    async def search_ton(self, query: str) -> list[dict]:
        """Pairs matching `query`, filtered to the TON chain."""
        d = await self.get(
            "/latest/dex/search",
            params={"q": query},
            cache_key=f"ds:search:{query}",
            ttl=300,
        )
        return [p for p in (d.get("pairs") or []) if p.get("chainId") == "ton"]
