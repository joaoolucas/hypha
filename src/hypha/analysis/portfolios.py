"""Feature 3 — Top wallet holdings ("are they whales of some coin?").

For the top holders of a token, fetch each wallet's USD-priced jetton portfolio and:
  • aggregate the tokens held *in common* across them (shared bags = narrative/connection),
  • flag whale positions — a single bag worth >= the configured USD threshold,
  • surface each notable wallet's biggest other bags.

The analyzed token itself is excluded (matched by raw address + symbol). This fans out one
portfolio call per scanned wallet, so it's gated behind /whales and cached. See SPEC.md Feature 3.
"""

from __future__ import annotations

import asyncio

from ..connectors.tonapi import TonAPI
from ..models import Holder, PortfolioReport, TokenHolding, WhaleWallet


def _usd(bal: dict, decimals: int) -> float:
    try:
        amt = int(bal.get("balance", 0) or 0) / (10 ** decimals)
    except (TypeError, ValueError):
        return 0.0
    price = ((bal.get("price") or {}).get("prices") or {}).get("USD")
    try:
        return amt * float(price) if price is not None else 0.0
    except (TypeError, ValueError):
        return 0.0


async def analyze_portfolios(
    self_addr_raw: str,
    self_symbol: str,
    top_holders: list[Holder],
    tonapi: TonAPI,
    *,
    max_wallets: int,
    whale_usd: float,
    min_shared: int,
    top_shared: int,
    dust_usd: float = 1_000.0,
    concurrency: int = 6,
) -> PortfolioReport:
    scan = [h for h in top_holders[:max_wallets] if h.owner and not h.is_excluded]
    if not scan:
        return PortfolioReport(notes=["no eligible top holders to scan"], whale_usd=whale_usd)

    sem = asyncio.Semaphore(max(1, concurrency))

    async def _fetch(h: Holder) -> list[dict]:
        async with sem:           # cap concurrent portfolio calls to avoid 429s
            return await tonapi.account_jettons(h.owner)

    results = await asyncio.gather(*(_fetch(h) for h in scan), return_exceptions=True)

    self_sym = (self_symbol or "").upper()
    agg: dict[str, dict] = {}
    wallets: list[WhaleWallet] = []

    for holder, res in zip(scan, results):
        if isinstance(res, BaseException):
            continue
        bags: list[dict] = []
        portfolio_usd = 0.0
        for bal in res:
            j = bal.get("jetton") or {}
            addr, sym = j.get("address"), j.get("symbol", "")
            if not addr or addr == self_addr_raw or (self_sym and sym.upper() == self_sym):
                continue  # skip the analyzed token itself
            try:
                decimals = int(j.get("decimals", 9) or 9)
            except (TypeError, ValueError):
                decimals = 9
            usd = _usd(bal, decimals)
            is_whale = usd >= whale_usd
            portfolio_usd += usd
            bags.append({"symbol": sym, "usd": round(usd, 2), "whale": is_whale})

            e = agg.setdefault(addr, {
                "address": addr, "symbol": sym, "name": j.get("name", ""),
                "held_by": 0, "whales": 0, "total_usd": 0.0,
                "verified": j.get("verification") == "whitelist",
            })
            e["held_by"] += 1
            e["whales"] += 1 if is_whale else 0
            e["total_usd"] += usd

        bags.sort(key=lambda b: b["usd"], reverse=True)
        wallets.append(WhaleWallet(
            owner=holder.owner, label=holder.label,
            portfolio_usd=round(portfolio_usd, 2), token_count=len(bags), top_bags=bags[:3],
        ))

    shared = [
        TokenHolding(
            address=e["address"], symbol=e["symbol"], name=e["name"],
            held_by=e["held_by"], whales=e["whales"],
            total_usd=round(e["total_usd"], 2), verified=e["verified"],
        )
        for e in agg.values() if e["held_by"] >= min_shared
    ]
    # drop spam/airdrop dust (held by many but worthless and no whale position)
    shared = [t for t in shared if t.whales > 0 or t.total_usd >= dust_usd]
    # surface the strongest signal first: whale count, then combined value
    shared.sort(key=lambda t: (t.whales, t.total_usd), reverse=True)
    wallets.sort(key=lambda w: w.portfolio_usd, reverse=True)

    return PortfolioReport(
        scanned=len(scan),
        shared_tokens=shared[:top_shared],
        wallets=wallets[:8],
        whale_usd=whale_usd,
        notes=[f"scanned {len(scan)} top wallets"],
    )
