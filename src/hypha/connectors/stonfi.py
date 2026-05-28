"""STON.fi DEX API — pools & assets for liquidity / LP verification (SPEC.md Feature 4).

  GET /v1/assets/{address}
  GET /v1/pools                         (filter client-side by asset)
Referral swaps are built in referral/router.py via the app.ston.fi deep link.
"""

from __future__ import annotations

from ..config import get_settings
from .base import BaseConnector, ConnectorError


class StonFi(BaseConnector):
    name = "stonfi"

    def __init__(self) -> None:
        super().__init__(get_settings().stonfi_base, headers={"Accept": "application/json"})

    async def pools_for_asset(self, addr: str) -> list[dict]:
        """Pools that contain the given jetton. STON.fi returns all pools; we filter."""
        try:
            d = await self.get("/v1/pools", cache_key="stonfi:pools", ttl=120)
        except ConnectorError:
            return []
        pools = d.get("pool_list", d.get("pools", [])) or []
        return [
            p for p in pools
            if addr in (p.get("token0_address"), p.get("token1_address"))
            or addr in str(p.get("address", ""))
        ]

    async def asset(self, addr: str) -> dict:
        try:
            d = await self.get(f"/v1/assets/{addr}", cache_key=f"stonfi:asset:{addr}", ttl=300)
        except ConnectorError:
            return {}
        return d.get("asset", d) or {}
