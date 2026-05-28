"""DeDust DEX API — pools & assets for liquidity / LP verification (SPEC.md Feature 4).

  GET /pools
  GET /assets
DeDust referral is SDK-only (no swap URL), so buy-links route via swap.coffee / STON.fi.
"""

from __future__ import annotations

from ..config import get_settings
from .base import BaseConnector, ConnectorError


class DeDust(BaseConnector):
    name = "dedust"

    def __init__(self) -> None:
        super().__init__(get_settings().dedust_base, headers={"Accept": "application/json"})

    async def pools_for_asset(self, addr: str) -> list[dict]:
        try:
            pools = await self.get("/pools", cache_key="dedust:pools", ttl=120)
        except ConnectorError:
            return []
        if not isinstance(pools, list):
            pools = pools.get("pools", []) if isinstance(pools, dict) else []
        out = []
        for p in pools:
            assets = p.get("assets", []) or []
            addrs = [a.get("address") if isinstance(a, dict) else a for a in assets]
            if addr in addrs:
                out.append(p)
        return out
