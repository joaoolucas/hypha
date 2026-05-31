"""Trader enrichment — turn a bare wallet address into the context that tags an alert:
its USD portfolio (🐋 whale?), whether we already follow it (👣), its recent big-buy count,
and its biggest other bags. One TonAPI portfolio call per qualifying trade (connector-cached),
so it stays cheap.
"""

from __future__ import annotations

import structlog

from ..config import Settings
from ..connectors.tonapi import TonAPI
from ..models import TraderContext
from ..registry import BURN_ADDRESSES
from ..utils import to_raw
from . import state

log = structlog.get_logger(__name__)

_STABLE_SYMBOLS = {"USDT", "USD₮", "USDC", "USDE", "JUSDT", "JUSDC", "DAI", "TSUSDE", "USDA"}
_BURN_RAW = {to_raw(a) for a in BURN_ADDRESSES} | set(BURN_ADDRESSES)


def _bag_usd(bal: dict, decimals: int) -> float:
    try:
        amt = int(bal.get("balance", 0) or 0) / (10 ** decimals)
    except (TypeError, ValueError):
        return 0.0
    price = ((bal.get("price") or {}).get("prices") or {}).get("USD")
    try:
        return amt * float(price) if price is not None else 0.0
    except (TypeError, ValueError):
        return 0.0


async def enrich_trader(trader_raw: str, tonapi: TonAPI, settings: Settings) -> TraderContext:
    ctx = TraderContext(address=trader_raw)
    ctx.is_followed = await state.is_followed(trader_raw)
    ctx.big_buys = await state.buy_count(trader_raw, settings.promote_window_secs)

    if not trader_raw or trader_raw in _BURN_RAW:
        ctx.excluded = True
        ctx.label = "burn" if trader_raw in _BURN_RAW else None
        return ctx

    try:
        balances = await tonapi.account_jettons(trader_raw)
    except Exception as exc:  # noqa: BLE001 — portfolio is best-effort context, never fatal
        log.warning("enrich_portfolio_failed", trader=trader_raw, error=str(exc))
        return ctx

    portfolio = 0.0
    bags: list[dict] = []
    for bal in balances:
        j = bal.get("jetton") or {}
        sym = j.get("symbol", "")
        try:
            decimals = int(j.get("decimals", 9) or 9)
        except (TypeError, ValueError):
            decimals = 9
        usd = _bag_usd(bal, decimals)
        portfolio += usd
        if usd >= 1 and sym.upper() not in _STABLE_SYMBOLS:
            bags.append({"symbol": sym, "usd": round(usd, 2)})

    # native TON counts toward whale value too (some whales hold mostly TON, not jettons)
    try:
        ton_usd = await tonapi.ton_usd()
        if ton_usd:
            ctx.ton_balance = round(await tonapi.account_ton(trader_raw), 2)
            ctx.ton_value_usd = round(ctx.ton_balance * ton_usd, 2)
            portfolio += ctx.ton_value_usd
    except Exception as exc:  # noqa: BLE001 — TON balance is a bonus signal, never fatal
        log.warning("enrich_ton_balance_failed", trader=trader_raw, error=str(exc))

    bags.sort(key=lambda b: b["usd"], reverse=True)
    ctx.portfolio_usd = round(portfolio, 2)
    ctx.is_whale = portfolio >= settings.whale_portfolio_usd
    ctx.top_bags = bags[:3]
    return ctx
