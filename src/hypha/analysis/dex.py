"""Feature 4 — DEX / liquidity verification.

Combines GeckoTerminal market data (liquidity, mcap, price, volume) with STON.fi / DeDust
pool presence. LP lock/burn status is conservative by default: an unverified pool is treated
as `unlocked` (low score) rather than assumed safe; known graduation flows that burn LP
(e.g. GasPump → DeDust) are upgraded to `burned`. See SPEC.md Feature 4 / §5.
"""

from __future__ import annotations

from ..models import DexReport, LaunchpadReport, LaunchStatus, LockStatus, TokenInfo


def analyze_dex(
    info: TokenInfo,
    market: dict,
    stonfi_pools: list[dict],
    dedust_pools: list[dict],
    launchpad: LaunchpadReport | None = None,
) -> DexReport:
    venues: list[str] = []
    if stonfi_pools:
        venues.append("stonfi")
    if dedust_pools:
        venues.append("dedust")

    liquidity = market.get("liquidity_usd") or 0.0
    mcap = market.get("market_cap_usd")
    has_pool = bool(venues) or liquidity > 0

    notes: list[str] = []
    # Conservative LP status.
    if not has_pool:
        lp_status = LockStatus.NONE
    elif launchpad and launchpad.status == LaunchStatus.GRADUATED and launchpad.graduation_dex == "dedust":
        lp_status = LockStatus.BURNED       # GasPump burns LP on graduation to DeDust
        notes.append("LP burned via launchpad graduation")
    else:
        lp_status = LockStatus.UNLOCKED
        notes.append("LP lock/burn not verified — treated as unlocked")

    ratio = round(liquidity / mcap * 100, 2) if mcap else None

    return DexReport(
        has_pool=has_pool,
        venues=venues,
        liquidity_usd=round(liquidity, 2),
        market_cap_usd=mcap,
        price_usd=market.get("price_usd"),
        volume24h_usd=market.get("volume24h_usd"),
        lp_status=lp_status,
        liq_to_mcap_pct=ratio,
        pools=(stonfi_pools[:3] + dedust_pools[:3]),
        notes=notes,
    )
