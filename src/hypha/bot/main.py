"""Bot entrypoint — long-polling. `python -m hypha.bot.main`."""

from __future__ import annotations

import asyncio
import logging

import structlog
from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode

from ..config import get_settings
from .handlers import router


def _setup_logging(level: str) -> None:
    logging.basicConfig(level=level.upper(), format="%(message)s")
    structlog.configure(
        wrapper_class=structlog.make_filtering_bound_logger(getattr(logging, level.upper(), 20)),
        processors=[structlog.processors.add_log_level, structlog.processors.JSONRenderer()],
    )


async def main() -> None:
    s = get_settings()
    _setup_logging(s.log_level)
    if not s.bot_token:
        raise SystemExit("BOT_TOKEN is not set (see .env.example)")

    bot = Bot(s.bot_token, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    dp = Dispatcher()
    dp.include_router(router)

    structlog.get_logger().info("hypha_starting", mode="polling")
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
