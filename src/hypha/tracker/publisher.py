"""Alert publisher — posts via the aiogram bot, which can attach inline button grids.

Branded custom emoji are not used (bots can't render them in channels), so alerts use plain
emoji + real tappable buttons. publish(channel, html, keyboard) -> bool.
"""

from __future__ import annotations

import structlog

log = structlog.get_logger(__name__)


def _target(channel_id: str) -> str | int:
    """Numeric ids (-100…) as int; @handles as str."""
    s = (channel_id or "").strip()
    try:
        return int(s)
    except ValueError:
        return s


class BotPublisher:
    def __init__(self, bot):
        self.bot = bot

    async def publish(self, channel: str, html: str, keyboard) -> bool:
        if not channel:
            log.warning("no_alerts_channel_configured")
            return False
        try:
            await self.bot.send_message(_target(channel), html,
                                        reply_markup=keyboard, disable_web_page_preview=True)
            return True
        except Exception as exc:  # noqa: BLE001 — one bad post must not kill the poller
            log.warning("publish_failed", error=str(exc))
            return False

    async def close(self) -> None:
        try:
            await self.bot.session.close()
        except Exception:  # noqa: BLE001
            pass
