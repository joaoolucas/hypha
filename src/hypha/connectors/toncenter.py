"""TON Center v3 — indexer fallback for jetton masters / wallets.

  GET /jetton/masters?address=
  GET /jetton/wallets?jetton_address=&limit=
Auth via X-API-Key header. Used when TonAPI is unavailable or rate-limited.
"""

from __future__ import annotations

from ..config import get_settings
from .base import BaseConnector


class TonCenter(BaseConnector):
    name = "toncenter"

    def __init__(self) -> None:
        s = get_settings()
        headers = {"X-API-Key": s.toncenter_key} if s.toncenter_key else {}
        super().__init__(s.toncenter_base, headers=headers)

    async def jetton_master(self, addr: str) -> dict:
        d = await self.get(
            "/jetton/masters",
            params={"address": addr},
            cache_key=f"tc:master:{addr}",
            ttl=600,
        )
        masters = d.get("jetton_masters", []) or []
        return masters[0] if masters else {}

    async def jetton_wallets(self, addr: str, limit: int = 1000) -> list[dict]:
        d = await self.get(
            "/jetton/wallets",
            params={"jetton_address": addr, "limit": min(limit, 1000)},
            cache_key=f"tc:wallets:{addr}:{limit}",
            ttl=300,
        )
        return d.get("jetton_wallets", []) or []
