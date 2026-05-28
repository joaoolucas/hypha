"""TonAPI (tonapi.io) — primary source for jetton info, holders, portfolios and tx events.

Endpoints verified May 2026:
  GET /v2/jettons/{addr}                      jetton master info
  GET /v2/jettons/{addr}/holders?limit&offset holders (max limit 1000)
  GET /v2/accounts/{addr}/jettons             an account's jetton balances
  GET /v2/accounts/{addr}/events?limit        high-level decoded actions
"""

from __future__ import annotations

import structlog

from ..config import get_settings
from ..models import Holder, TokenInfo
from .base import BaseConnector

log = structlog.get_logger(__name__)
ZERO_ADDRS = {"0:0000000000000000000000000000000000000000000000000000000000000000"}


class TonAPI(BaseConnector):
    name = "tonapi"

    def __init__(self) -> None:
        s = get_settings()
        headers = {"Authorization": f"Bearer {s.tonapi_key}"} if s.tonapi_key else {}
        super().__init__(s.tonapi_base, headers=headers)

    async def jetton_info(self, addr: str) -> TokenInfo:
        d = await self.get(f"/v2/jettons/{addr}", cache_key=f"ta:info:{addr}", ttl=600)
        meta = d.get("metadata", {}) or {}
        admin = (d.get("admin") or {}).get("address")
        if admin in ZERO_ADDRS:
            admin = None
        try:
            decimals = int(meta.get("decimals", 9))
        except (TypeError, ValueError):
            decimals = 9
        return TokenInfo(
            address=addr,
            name=meta.get("name", ""),
            symbol=meta.get("symbol", ""),
            decimals=decimals,
            image=meta.get("image"),
            total_supply=int(d.get("total_supply", 0) or 0),
            mintable=bool(d.get("mintable", False)),
            admin_address=admin,
            holders_count=int(d.get("holders_count", 0) or 0),
            verification=d.get("verification", "none"),
        )

    async def jetton_holders(self, addr: str, limit: int = 1000) -> list[Holder]:
        limit = min(limit, 1000)
        d = await self.get(
            f"/v2/jettons/{addr}/holders",
            params={"limit": limit, "offset": 0},
            cache_key=f"ta:holders:{addr}:{limit}",
            ttl=300,
        )
        out: list[Holder] = []
        for h in d.get("addresses", []) or []:
            owner = h.get("owner") or {}
            out.append(
                Holder(
                    owner=owner.get("address", ""),
                    wallet=h.get("address", ""),
                    balance=int(h.get("balance", 0) or 0),
                    label=owner.get("name"),
                    is_scam=bool(owner.get("is_scam", False)),
                )
            )
        return out

    async def account_jettons(self, addr: str) -> list[dict]:
        d = await self.get(
            f"/v2/accounts/{addr}/jettons",
            cache_key=f"ta:acct_jettons:{addr}",
            ttl=300,
        )
        return d.get("balances", []) or []

    async def account_events(self, addr: str, limit: int = 100) -> list[dict]:
        d = await self.get(
            f"/v2/accounts/{addr}/events",
            params={"limit": min(limit, 100)},
        )
        return d.get("events", []) or []
