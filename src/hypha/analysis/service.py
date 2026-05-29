"""Analysis orchestrator — fan out to connectors, run each feature, assemble a TokenReport
and cache it. Called by both the bot (inline) and the arq workers (heavy jobs).

The default DEX read goes through GeckoTerminal (liquidity + venues in one light call). When
all DEX sources error, `dex` is left None (liquidity *unknown*) so the score engine neither
rewards nor poison-caps it — only a genuinely pool-less token trips the honeypot flag.
See SPEC.md §3 / §5.3.
"""

from __future__ import annotations

import asyncio
import time

import structlog

from ..cache import cache_get, cache_set
from ..config import get_settings
from ..connectors.geckoterminal import GeckoTerminal
from ..connectors.tonapi import TonAPI
from ..models import PortfolioReport, TokenInfo, TokenReport
from ..snapshots import record_and_growth
from .dex import analyze_dex, extract_venues, pool_liquidity
from .holders import analyze_holders
from .launchpad import detect_launchpad
from .portfolios import analyze_portfolios
from .score import compute_score

log = structlog.get_logger(__name__)


def _val(res, default):
    """Unwrap an asyncio.gather(return_exceptions=True) result."""
    return default if isinstance(res, BaseException) else res


def _dev_sold(events: list, dev: str) -> bool | None:
    """True if the dev/admin wallet has transferred this jetton out (sold/moved)."""
    if not events:
        return None
    for ev in events:
        for act in ev.get("actions", []):
            if act.get("type") != "JettonTransfer":
                continue
            t = act.get("JettonTransfer") or {}
            sender = (t.get("sender") or {}).get("address")
            recipient = (t.get("recipient") or {}).get("address")
            if sender == dev and recipient != dev:
                return True
    return False


async def analyze_token(address: str, *, force: bool = False) -> TokenReport:
    s = get_settings()
    cache_key = f"report:{address}"
    if not force:
        cached = await cache_get(cache_key)
        if cached:
            return TokenReport.model_validate(cached)

    tonapi, gecko = TonAPI(), GeckoTerminal()
    dev_events: list = []
    try:
        info_r, holders_r, market_r, pools_r = await asyncio.gather(
            tonapi.jetton_info(address),
            tonapi.jetton_holders(address),
            gecko.token_market(address),
            gecko.token_pools(address),
            return_exceptions=True,
        )
        # Dev-sold needs the admin address (from info) + a still-open client.
        if not isinstance(info_r, BaseException) and info_r.admin_address \
                and not isinstance(holders_r, BaseException):
            try:
                dev_events = await tonapi.jetton_account_history(info_r.admin_address, address)
            except Exception:  # noqa: BLE001
                dev_events = []
    finally:
        await asyncio.gather(tonapi.aclose(), gecko.aclose(), return_exceptions=True)

    if isinstance(info_r, BaseException):
        log.warning("jetton_info_failed", address=address, error=str(info_r))
        return TokenReport(
            token=TokenInfo(address=address, symbol="?"),
            generated_at=time.time(),
            errors=[f"Couldn't load token: {info_r}"],
        )

    info: TokenInfo = info_r
    errors: list[str] = []

    holders_raw = _val(holders_r, [])
    if isinstance(holders_r, BaseException):
        errors.append("holders unavailable")

    market_ok = not isinstance(market_r, BaseException)
    pools_ok = not isinstance(pools_r, BaseException)
    market = market_r if market_ok else {}
    gecko_pools = pools_r if pools_ok else []
    dex_known = market_ok or pools_ok

    if dex_known:
        liquidity = (market.get("liquidity_usd") if market_ok else None) or pool_liquidity(gecko_pools)
        has_pool = bool(extract_venues(gecko_pools)) or liquidity > 0
    else:
        liquidity, has_pool = 0.0, False
        errors.append("dex data unavailable")

    launchpad = detect_launchpad(info, has_pool, liquidity)
    dex = analyze_dex(info, market, gecko_pools, launchpad) if dex_known else None
    holders = analyze_holders(info, holders_raw) if holders_raw else None
    if holders:
        if info.admin_address:
            holders.dev_sold = _dev_sold(dev_events, info.admin_address)
        holders.growth_delta, holders.growth_secs = await record_and_growth(
            address, holders.holders_count
        )
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


async def analyze_whales(address: str, *, force: bool = False) -> tuple[TokenReport, PortfolioReport]:
    """Feature 3: scan the top holders' portfolios. Returns (token report, portfolio report)."""
    s = get_settings()
    report = await analyze_token(address, force=force)
    if not report.holders or not report.holders.top_holders:
        return report, PortfolioReport(notes=["no holder data to scan"], whale_usd=s.whale_usd_threshold)

    cache_key = f"whales:{address}"
    if not force:
        cached = await cache_get(cache_key)
        if cached:
            return report, PortfolioReport.model_validate(cached)

    tonapi = TonAPI()
    try:
        self_raw = await tonapi.parse_address(address)
        portfolio = await analyze_portfolios(
            self_raw,
            report.token.symbol,
            report.holders.top_holders,
            tonapi,
            max_wallets=s.whales_scan_max,
            whale_usd=s.whale_usd_threshold,
            min_shared=s.whales_min_shared,
            top_shared=s.whales_top_shared,
            dust_usd=s.whales_dust_usd,
            concurrency=s.whales_concurrency,
        )
    finally:
        await tonapi.aclose()

    await cache_set(cache_key, portfolio.model_dump(), s.analysis_ttl)
    return report, portfolio
