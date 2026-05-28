"""Feature 3 — Top wallet holdings.

For the top holders of a token, fetch each wallet's jetton portfolio and aggregate which
*other* tokens they commonly hold — surfacing narratives & project connections. This fans out
N portfolio calls, so it's gated behind /whales (not the default /analyze) and cached.
See SPEC.md Feature 3.
"""

from __future__ import annotations

import asyncio
from collections import defaultdict

from ..connectors.tonapi import TonAPI
from ..models import Holder, PortfolioReport


async def analyze_portfolios(
    self_addr: str, top_holders: list[Holder], tonapi: TonAPI, max_wallets: int = 15
) -> PortfolioReport:
    owners = [h.owner for h in top_holders[:max_wallets] if h.owner and not h.is_excluded]
    if not owners:
        return PortfolioReport(notes=["no eligible top holders to scan"])

    results = await asyncio.gather(
        *(tonapi.account_jettons(o) for o in owners), return_exceptions=True
    )

    counter: dict[str, dict] = defaultdict(lambda: {"holders": 0, "symbol": "", "address": ""})
    for res in results:
        if isinstance(res, Exception):
            continue
        for bal in res:
            jetton = bal.get("jetton", {}) or {}
            addr = jetton.get("address")
            if not addr or addr == self_addr:
                continue
            entry = counter[addr]
            entry["holders"] += 1
            entry["symbol"] = jetton.get("symbol", "")
            entry["address"] = addr

    common = sorted(counter.values(), key=lambda e: e["holders"], reverse=True)
    common = [c for c in common if c["holders"] >= 2][:10]
    return PortfolioReport(
        common_tokens=common,
        notes=[f"scanned {len(owners)} top wallets"],
    )
