"""Feature 4 — DEX / liquidity verification.

Default path reads liquidity + venues from GeckoTerminal (one light call gives reserves and
per-pool DEX id), rather than downloading entire DEX pool lists. STON.fi / DeDust connectors
are reserved for the Phase-2 LP-lock check.

LP lock/burn status is conservative: an unverified pool is treated as `unlocked` (low score)
rather than assumed safe; known graduation flows that burn LP (GasPump → DeDust) are upgraded
to `burned`. See SPEC.md Feature 4 / §5.
"""

from __future__ import annotations

from ..models import DexReport, LaunchpadReport, LaunchStatus, LockStatus, TokenInfo


def _norm_venue(dex_id: str) -> str:
    low = (dex_id or "").lower()
    if "ston" in low:
        return "stonfi"
    if "dedust" in low:
        return "dedust"
    return low or "dex"


def extract_venues(gecko_pools: list[dict]) -> list[str]:
    venues: list[str] = []
    for p in gecko_pools:
        dex_id = (((p.get("relationships") or {}).get("dex") or {}).get("data") or {}).get("id", "")
        v = _norm_venue(dex_id)
        if v not in venues:
            venues.append(v)
    return venues


def pool_liquidity(gecko_pools: list[dict]) -> float:
    total = 0.0
    for p in gecko_pools:
        try:
            total += float((p.get("attributes") or {}).get("reserve_in_usd") or 0)
        except (TypeError, ValueError):
            continue
    return total


def _f(v) -> float | None:
    try:
        return float(v) if v is not None else None
    except (TypeError, ValueError):
        return None


def _deepest(gecko_pools: list[dict]) -> dict | None:
    """Attributes of the pool with the most liquidity (most representative price/volume)."""
    best, best_res = None, -1.0
    for p in gecko_pools:
        a = p.get("attributes") or {}
        res = _f(a.get("reserve_in_usd")) or 0.0
        if res > best_res:
            best_res, best = res, a
    return best


def momentum(gecko_pools: list[dict]) -> dict:
    """Price change (5m/1h/24h) + a volume trend read from the deepest pool."""
    a = _deepest(gecko_pools)
    if not a:
        return {}
    pc = a.get("price_change_percentage") or {}
    vu = a.get("volume_usd") or {}
    v1, v24 = _f(vu.get("h1")), _f(vu.get("h24"))
    trend = None
    if v1 is not None and v24 and v24 > 0:
        avg_hourly = v24 / 24
        if avg_hourly > 0:
            trend = "Rising 📈" if v1 > 1.3 * avg_hourly else "Cooling 📉" if v1 < 0.7 * avg_hourly else "Steady ➡️"
    return {
        "change_5m": _f(pc.get("m5")),
        "change_1h": _f(pc.get("h1")),
        "change_24h": _f(pc.get("h24")),
        "vol_trend": trend,
    }


def analyze_dex(
    info: TokenInfo,
    market: dict,
    gecko_pools: list[dict],
    launchpad: LaunchpadReport | None = None,
) -> DexReport:
    venues = extract_venues(gecko_pools)
    mom = momentum(gecko_pools)
    # Prefer the token-level aggregate; fall back to summing pool reserves.
    liquidity = market.get("liquidity_usd") or pool_liquidity(gecko_pools)
    mcap = market.get("market_cap_usd")
    has_pool = bool(venues) or liquidity > 0

    notes: list[str] = []
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
        price_change_24h=mom.get("change_24h"),
        change_5m=mom.get("change_5m"),
        change_1h=mom.get("change_1h"),
        vol_trend=mom.get("vol_trend"),
        volume24h_usd=market.get("volume24h_usd"),
        lp_status=lp_status,
        liq_to_mcap_pct=ratio,
        pools=[
            {
                "name": (p.get("attributes") or {}).get("name", ""),
                "reserve_usd": (p.get("attributes") or {}).get("reserve_in_usd"),
            }
            for p in gecko_pools[:5]
        ],
        notes=notes,
    )
