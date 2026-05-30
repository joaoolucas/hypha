"""The poller — three cooperative loops, all cache-coordinated:

  • discovery  — refresh the hot-pool set from Gecko trending/new (every discovery_poll_secs)
  • trades     — token-centric: poll each hot pool's trade feed, alert on big buys/sells
  • follow     — wallet-centric: poll promoted whales' TonAPI events, catch cold-token plays

handle_trade is the shared funnel: dedup → enrich → price → posting policy → promotion → post.
"""

from __future__ import annotations

import asyncio

import structlog

from ..analysis.discovery import hot_pools
from ..analysis.service import analyze_token
from ..analysis.trades import parse_pool_events, parse_tonapi_events
from ..bot.channel import publish_alert, render_alert
from ..config import Settings
from ..connectors.geckoterminal import GeckoTerminal
from ..connectors.tonapi import TonAPI
from ..db.models import Alert
from ..db.session import session
from ..models import Trade, TradeSide
from . import state
from .enrich import enrich_trader

log = structlog.get_logger(__name__)

_MAX_POSTS_PER_CYCLE = 15        # flood guard; drops beyond this are logged, never silent


def _should_post(trade: Trade, ctx, s: Settings) -> bool:
    if trade.side == TradeSide.BUY:
        return trade.usd >= s.buy_alert_usd or ctx.is_followed
    return trade.usd >= s.sell_alert_usd


async def _price_in_usd(trade: Trade, report) -> float:
    if trade.usd and trade.usd > 0:
        return trade.usd
    price = (report.dex.price_usd if report.dex else None) or trade.price_usd
    if price and trade.token_amount:
        return round(trade.token_amount * price, 2)
    return 0.0


async def handle_trade(trade: Trade, tonapi: TonAPI, bot, s: Settings) -> bool:
    """Process one detected swap. Returns True if it was posted."""
    if not trade.token_address or not await state.is_new_op(trade, s.alert_dedup_ttl):
        return False

    report = await analyze_token(trade.token_address)
    trade.usd = await _price_in_usd(trade, report)
    ctx = await enrich_trader(trade.trader, tonapi, s)

    if not _should_post(trade, ctx, s):
        return False

    # auto-promotion: a real, sized buy by a real wallet counts toward the followed list
    promoted = False
    if trade.side == TradeSide.BUY and trade.usd >= s.buy_alert_usd and not ctx.excluded:
        ctx.big_buys = await state.record_big_buy(trade.trader, s.promote_window_secs)
        if (s.follow_enabled and not ctx.is_followed
                and ctx.big_buys >= s.promote_min_buys
                and await state.followed_count() < s.followed_max):
            await state.add_followed(trade.trader)
            ctx.is_followed = promoted = True
            log.info("wallet_promoted", trader=trade.trader, buys=ctx.big_buys)

    text, kb = render_alert(trade, ctx, report, promoted=promoted)
    posted = await publish_alert(bot, s.alerts_channel_id, text, kb)
    if posted:
        await _log_alert(trade, ctx, report)
    return posted


async def _log_alert(trade: Trade, ctx, report) -> None:
    """Best-effort durable log for calibration. No-ops without DATABASE_URL; never raises."""
    db = session()
    if db is None:
        return
    try:
        async with db:
            db.add(Alert(
                side=trade.side.value, token=trade.token_address, symbol=trade.token_symbol,
                trader=trade.trader, usd=trade.usd,
                price_usd=trade.price_usd or (report.dex.price_usd if report.dex else None),
                hypha_score=report.score.score if report.score else None,
                is_whale=ctx.is_whale, is_followed=ctx.is_followed,
            ))
            await db.commit()
    except Exception as exc:  # noqa: BLE001 — analytics must never break the poller
        log.warning("alert_log_failed", error=str(exc))


# ── cycles ─────────────────────────────────────────────────────────────────────
async def discovery_cycle(gecko: GeckoTerminal, s: Settings) -> int:
    """Refresh the hot-pool set from Gecko (trending/new). Only a couple of tiny calls every
    half hour, so the free tier copes. If it comes back empty (throttle), keep the prior set."""
    pools = await hot_pools(gecko, s.hot_pools_max)
    if pools:
        await state.save_hot_pools(pools)
        log.info("discovery", pools=len(pools))
    else:
        log.warning("discovery_empty_kept_previous")
    return len(pools)


async def trade_cycle(gecko: GeckoTerminal, tonapi: TonAPI, bot, s: Settings) -> None:
    """Token-centric: read each hot pool's swaps from TonAPI (reliable) and alert on big ones."""
    pools = await state.load_hot_pools()
    if not pools:
        await discovery_cycle(gecko, s)
        pools = await state.load_hot_pools()
    ton_usd = await _ton_price(tonapi)
    sem = asyncio.Semaphore(s.trade_concurrency)

    async def _fresh(pool):
        async with sem:
            try:
                events = await tonapi.account_events(pool.pool_address, limit=30)
            except Exception as exc:  # noqa: BLE001
                log.warning("pool_events_failed", pool=pool.pool_address, error=str(exc))
                return []
        parsed = parse_pool_events(events, pool, ton_usd)
        return await state.new_pool_trades(pool.pool_address, parsed)

    batches = await asyncio.gather(*(_fresh(p) for p in pools), return_exceptions=True)
    fresh = [t for b in batches if not isinstance(b, BaseException) for t in b]
    await _post_batch(fresh, tonapi, bot, s)


async def _ton_price(tonapi: TonAPI) -> float:
    try:
        return await tonapi.ton_usd()
    except Exception as exc:  # noqa: BLE001 — sizing falls back to token price if this fails
        log.warning("ton_price_failed", error=str(exc))
        return 0.0


async def follow_cycle(gecko: GeckoTerminal, tonapi: TonAPI, bot, s: Settings) -> None:
    wallets = (await state.followed_list())[: s.followed_max]
    if not wallets:
        return
    sem = asyncio.Semaphore(s.trade_concurrency)

    async def _fresh(wallet):
        async with sem:
            try:
                events = await tonapi.account_events(wallet, limit=20)
            except Exception as exc:  # noqa: BLE001
                log.warning("account_events_failed", wallet=wallet, error=str(exc))
                return []
        parsed = parse_tonapi_events(events, wallet)
        return await state.new_wallet_trades(wallet, parsed)

    batches = await asyncio.gather(*(_fresh(w) for w in wallets), return_exceptions=True)
    fresh = [t for b in batches if not isinstance(b, BaseException) for t in b]
    await _post_batch(fresh, tonapi, bot, s)


async def _post_batch(trades: list[Trade], tonapi: TonAPI, bot, s: Settings) -> None:
    trades.sort(key=lambda t: t.ts)          # oldest first, chronological in the channel
    if len(trades) > _MAX_POSTS_PER_CYCLE:
        log.warning("post_cap_hit", found=len(trades), cap=_MAX_POSTS_PER_CYCLE,
                    dropped=len(trades) - _MAX_POSTS_PER_CYCLE)
        trades = trades[-_MAX_POSTS_PER_CYCLE:]   # keep the most recent
    for tr in trades:
        try:
            if await handle_trade(tr, tonapi, bot, s):
                await asyncio.sleep(1.1)          # stay under Telegram's channel post rate
        except Exception:  # noqa: BLE001
            log.exception("handle_trade_failed", token=tr.token_address)
