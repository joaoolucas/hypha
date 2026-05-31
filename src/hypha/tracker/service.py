"""The poller — three cooperative loops, all cache-coordinated:

  • discovery  — refresh the hot-pool set from Gecko trending/new (every discovery_poll_secs)
  • trades     — token-centric: poll each hot pool's trade feed, alert on big buys/sells
  • follow     — wallet-centric: poll promoted whales' TonAPI events, catch cold-token plays

handle_trade is the shared funnel: dedup → enrich → price → posting policy → promotion → post.
"""

from __future__ import annotations

import asyncio
import time

import structlog

from ..analysis.discovery import hot_pools, is_quote_asset
from ..analysis.service import analyze_token
from ..analysis.trades import parse_pool_events, parse_tonapi_events, parse_uranus_events
from ..bot.channel import render_alert
from ..config import Settings
from ..connectors.dexscreener import DexScreener
from ..connectors.geckoterminal import GeckoTerminal
from ..connectors.tonapi import TonAPI
from ..db.models import Alert
from ..db.session import session
from ..models import Trade, TradeSide
from . import state
from .enrich import enrich_trader

log = structlog.get_logger(__name__)

_MAX_POSTS_PER_CYCLE = 15        # flood guard; drops beyond this are logged, never silent


async def publish_alert(publisher, channel: str, text: str, keyboard) -> bool:
    """Send one rendered alert (html + inline keyboard) via the bot publisher."""
    return await publisher.publish(channel, text, keyboard)


def _should_post(trade: Trade, ctx, s: Settings, buy_floor_usd: float) -> bool:
    """Buys post only for whales (by portfolio) clearing the buy floor — no followed-only buys.
    Sells post for whales or followed wallets clearing the sell floor."""
    if ctx.excluded:
        return False
    if trade.side == TradeSide.BUY:
        return ctx.is_whale and trade.usd >= buy_floor_usd
    return (ctx.is_whale or ctx.is_followed) and trade.usd >= s.sell_alert_usd


async def _price_in_usd(trade: Trade, report) -> float:
    if trade.usd and trade.usd > 0:
        return trade.usd
    price = (report.dex.price_usd if report.dex else None) or trade.price_usd
    if price and trade.token_amount:
        return round(trade.token_amount * price, 2)
    return 0.0


async def handle_trade(trade: Trade, tonapi: TonAPI, publisher, s: Settings,
                       buy_floor_usd: float | None = None) -> bool:
    """Process one detected swap. Returns True if it was posted. `buy_floor_usd` is the effective
    USD buy threshold (TON-denominated, converted at the current TON price); falls back to config."""
    floor = buy_floor_usd if buy_floor_usd is not None else s.buy_alert_usd
    if not trade.token_address or is_quote_asset(trade.token_symbol):
        return False                                  # ignore stablecoins + TON/wrapped-TON as the traded token
    if not await state.is_new_op(trade, s.alert_dedup_ttl):
        return False

    report = await analyze_token(trade.token_address)
    trade.usd = await _price_in_usd(trade, report)
    ctx = await enrich_trader(trade.trader, tonapi, s)

    # Auto-promotion runs BEFORE the post gate and regardless of whale status: a wallet that
    # repeatedly makes sized buys is smart money worth following, even if its portfolio is light.
    # Crossing the threshold flips is_followed so this very buy posts as the promotion moment.
    promoted = False
    if trade.side == TradeSide.BUY and trade.usd >= floor and not ctx.excluded:
        ctx.big_buys = await state.record_big_buy(trade.trader, s.promote_window_secs)
        if (s.follow_enabled and not ctx.is_followed
                and ctx.big_buys >= s.promote_min_buys
                and await state.followed_count() < s.followed_max):
            await state.add_followed(trade.trader)
            ctx.is_followed = promoted = True
            log.info("wallet_promoted", trader=trade.trader, buys=ctx.big_buys)

    if not _should_post(trade, ctx, s, floor):
        return False

    text, keyboard = render_alert(trade, ctx, report, promoted=promoted)
    posted = await publish_alert(publisher, s.alerts_channel_id, text, keyboard)
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
    ds = DexScreener()
    try:
        pools = await hot_pools(gecko, s.hot_pools_max, ds)
    finally:
        await ds.aclose()
    if pools:
        await state.save_hot_pools(pools)
        log.info("discovery", pools=len(pools))
    else:
        log.warning("discovery_empty_kept_previous")
    return len(pools)


async def trade_cycle(gecko: GeckoTerminal, tonapi: TonAPI, publisher, s: Settings) -> None:
    """Token-centric: read each hot pool's swaps from TonAPI (reliable) and alert on big ones."""
    pools = await state.load_hot_pools()
    if not pools:
        await discovery_cycle(gecko, s)
        pools = await state.load_hot_pools()
    ton_usd = await _ton_price(tonapi)
    buy_floor = _buy_floor(s, ton_usd)
    sem = asyncio.Semaphore(s.trade_concurrency)

    async def _fresh(pool):
        async with sem:
            try:
                if pool.venue == "uranus":
                    # Uranus/Topblast: parse the Meme contract's on-chain BuyEvent/SellEvent
                    txs = await tonapi.blockchain_transactions(pool.token_address, limit=20)
                    parsed = parse_uranus_events(txs, pool, ton_usd)
                else:
                    events = await tonapi.account_events(pool.pool_address, limit=30)
                    parsed = parse_pool_events(events, pool, ton_usd)
            except Exception as exc:  # noqa: BLE001
                log.warning("pool_fetch_failed", pool=pool.pool_address, venue=pool.venue, error=str(exc))
                return []
        return await state.new_pool_trades(pool.pool_address, parsed)

    batches = await asyncio.gather(*(_fresh(p) for p in pools), return_exceptions=True)
    fresh = [t for b in batches if not isinstance(b, BaseException) for t in b]
    log.info("trade_cycle", pools=len(pools), fresh=len(fresh),
             max_usd=round(max((t.usd for t in fresh), default=0.0)), buy_floor=round(buy_floor))
    await _post_batch(fresh, tonapi, publisher, s, buy_floor)


def _buy_floor(s: Settings, ton_usd: float) -> float:
    """Effective USD buy threshold: the TON-denominated floor priced at the current TON rate."""
    return s.buy_alert_ton * ton_usd if ton_usd > 0 else s.buy_alert_usd


async def _ton_price(tonapi: TonAPI) -> float:
    try:
        return await tonapi.ton_usd()
    except Exception as exc:  # noqa: BLE001 — sizing falls back to token price if this fails
        log.warning("ton_price_failed", error=str(exc))
        return 0.0


async def follow_cycle(gecko: GeckoTerminal, tonapi: TonAPI, publisher, s: Settings) -> None:
    wallets = (await state.followed_list())[: s.followed_max]
    if not wallets:
        return
    # Followed buys are no longer posted (whale-only buys); the follow loop now surfaces a followed
    # wallet's whale buys in cold tokens and its big sells. Same floors as the token-centric loop.
    buy_floor = _buy_floor(s, await _ton_price(tonapi))
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
    await _post_batch(fresh, tonapi, publisher, s, buy_floor)


async def _post_batch(trades: list[Trade], tonapi: TonAPI, publisher, s: Settings,
                      buy_floor_usd: float) -> None:
    now = time.time()
    floor = min(buy_floor_usd, s.sell_alert_usd)
    # Only timely, plausibly-sized trades: drop the restart backlog (stale ts) and clear obvious
    # sub-threshold noise before the flood cap. usd==0 means unpriced (no TON leg) — keep it so
    # handle_trade can price it from market data.
    cands = [t for t in trades
             if (now - t.ts) <= s.trade_max_age_secs and (t.usd == 0 or t.usd >= floor)]
    if len(cands) > _MAX_POSTS_PER_CYCLE:
        log.warning("post_cap_hit", found=len(cands), cap=_MAX_POSTS_PER_CYCLE,
                    dropped=len(cands) - _MAX_POSTS_PER_CYCLE)
        cands = sorted(cands, key=lambda t: t.usd, reverse=True)[:_MAX_POSTS_PER_CYCLE]  # keep biggest
    cands.sort(key=lambda t: t.ts)               # oldest first, chronological in the channel
    for tr in cands:
        try:
            if await handle_trade(tr, tonapi, publisher, s, buy_floor_usd):
                await asyncio.sleep(1.1)          # stay under Telegram's channel post rate
        except Exception:  # noqa: BLE001
            log.exception("handle_trade_failed", token=tr.token_address)
