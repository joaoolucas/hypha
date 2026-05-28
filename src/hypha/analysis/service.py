"""Analysis orchestrator — fan out to connectors, run each feature, assemble a TokenReport
and cache it. Called by both the bot (inline) and the arq workers (heavy jobs).
See SPEC.md §3.
"""

from __future__ import annotations

import asyncio
import time

import structlog

from ..cache import cache_get, cache_set
from ..config import get_settings
from ..connectors.dedust import DeDust
from ..connectors.geckoterminal import GeckoTerminal
from ..connectors.stonfi import StonFi
from ..connectors.tonapi import TonAPI
from ..models import TokenInfo, TokenReport
from .dex import analyze_dex
from .holders import analyze_holders
from .launchpad import detect_launchpad
from .score import compute_score

log = structlog.get_logger(__name__)


def _val(res, default):
    """Unwrap an asyncio.gather(return_exceptions=True) result."""
    return default if isinstance(res, BaseException) else res


async def analyze_token(address: str, *, force: bool = False) -> TokenReport:
    s = get_settings()
    cache_key = f"report:{address}"
    if not force:
        cached = await cache_get(cache_key)
        if cached:
            return TokenReport.model_validate(cached)

    tonapi, gecko, stonfi, dedust = TonAPI(), GeckoTerminal(), StonFi(), DeDust()
    try:
        info_r, holders_r, market_r, stonfi_r, dedust_r = await asyncio.gather(
            tonapi.jetton_info(address),
            tonapi.jetton_holders(address),
            gecko.token_market(address),
            stonfi.pools_for_asset(address),
            dedust.pools_for_asset(address),
            return_exceptions=True,
        )
    finally:
        await asyncio.gather(
            tonapi.aclose(), gecko.aclose(), stonfi.aclose(), dedust.aclose(),
            return_exceptions=True,
        )

    errors: list[str] = []
    if isinstance(info_r, BaseException):
        log.warning("jetton_info_failed", address=address, error=str(info_r))
        return TokenReport(
            token=TokenInfo(address=address, symbol="?"),
            generated_at=time.time(),
            errors=[f"Couldn't load token: {info_r}"],
        )

    info: TokenInfo = info_r
    holders_raw = _val(holders_r, [])
    market = _val(market_r, {})
    stonfi_pools = _val(stonfi_r, [])
    dedust_pools = _val(dedust_r, [])
    for label, res in (("holders", holders_r), ("market", market_r),
                       ("stonfi", stonfi_r), ("dedust", dedust_r)):
        if isinstance(res, BaseException):
            errors.append(f"{label} unavailable")

    has_pool = bool(stonfi_pools or dedust_pools) or (market.get("liquidity_usd") or 0) > 0
    liquidity = market.get("liquidity_usd") or 0.0

    launchpad = detect_launchpad(info, has_pool, liquidity)
    dex = analyze_dex(info, market, stonfi_pools, dedust_pools, launchpad)
    holders = analyze_holders(info, holders_raw) if holders_raw else None
    bundle = None  # Phase 3 — pillar treated as unavailable by the score engine

    score = compute_score(info, holders, dex, launchpad, bundle)

    report = TokenReport(
        token=info,
        holders=holders,
        dex=dex,
        launchpad=launchpad,
        bundle=bundle,
        score=score,
        generated_at=time.time(),
        errors=errors,
    )
    await cache_set(cache_key, report.model_dump(), s.analysis_ttl)
    return report
