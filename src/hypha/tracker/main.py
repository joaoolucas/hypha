"""Tracker entrypoint — `python -m hypha.tracker.main`. Runs the discovery/trade/follow loops
side by side, each on its own interval. Posts via a userbot (a Premium account, for branded
custom emoji) when configured, else via the bot. Resilient: a failing cycle is logged and the
loop keeps its cadence.
"""

from __future__ import annotations

import asyncio
import logging

import structlog

from ..config import get_settings
from ..connectors.geckoterminal import GeckoTerminal
from ..connectors.tonapi import TonAPI
from ..db.session import init_models
from .publisher import BotPublisher, UserbotPublisher
from .service import discovery_cycle, follow_cycle, trade_cycle


async def _make_publisher(s, log):
    """Userbot (Premium account → branded custom emoji) if configured, else the aiogram bot."""
    if s.userbot_session and s.userbot_api_id:
        pub = UserbotPublisher(s.userbot_api_id, s.userbot_api_hash, s.userbot_session)
        await pub.start()
        log.info("posting_via", mode="userbot")
        return pub
    from aiogram import Bot
    from aiogram.client.default import DefaultBotProperties
    from aiogram.enums import ParseMode
    if not s.bot_token:
        raise SystemExit("set a userbot session or BOT_TOKEN so the tracker can post")
    log.info("posting_via", mode="bot")
    return BotPublisher(Bot(s.bot_token, default=DefaultBotProperties(parse_mode=ParseMode.HTML)))


def _setup_logging(level: str) -> None:
    logging.basicConfig(level=level.upper(), format="%(message)s")
    structlog.configure(
        wrapper_class=structlog.make_filtering_bound_logger(getattr(logging, level.upper(), 20)),
        processors=[structlog.processors.add_log_level, structlog.processors.JSONRenderer()],
    )


async def _loop(name: str, interval: int, fn) -> None:
    log = structlog.get_logger(name)
    while True:
        try:
            await fn()
        except Exception:  # noqa: BLE001 — never let one bad cycle kill the loop
            log.exception("cycle_failed")
        await asyncio.sleep(interval)


async def main() -> None:
    s = get_settings()
    _setup_logging(s.log_level)
    log = structlog.get_logger("tracker")
    if not s.alerts_channel_id:
        log.warning("alerts_channel_unset", hint="set ALERTS_CHANNEL_ID so the tracker can post")

    publisher = await _make_publisher(s, log)
    gecko, tonapi = GeckoTerminal(), TonAPI()
    try:
        await init_models()                  # create the alerts table if DATABASE_URL is set
    except Exception as exc:  # noqa: BLE001
        log.warning("db_init_failed", error=str(exc))

    log.info("tracker_starting", hot_pools=s.hot_pools_max,
             trade_secs=s.trades_poll_secs, follow_secs=s.follow_poll_secs)
    for attempt in range(6):                 # seed the hot-pool set before trading; retry transient throttle
        if await discovery_cycle(gecko, s) > 0:
            break
        log.warning("discovery_retry", attempt=attempt + 1)
        await asyncio.sleep(20)

    loops = [_loop("discovery", s.discovery_poll_secs, lambda: discovery_cycle(gecko, s)),
             _loop("trades", s.trades_poll_secs, lambda: trade_cycle(gecko, tonapi, publisher, s))]
    if s.follow_enabled:
        loops.append(_loop("follow", s.follow_poll_secs, lambda: follow_cycle(gecko, tonapi, publisher, s)))

    try:
        await asyncio.gather(*loops)
    finally:
        await asyncio.gather(gecko.aclose(), tonapi.aclose(), publisher.close(),
                             return_exceptions=True)


if __name__ == "__main__":
    asyncio.run(main())
