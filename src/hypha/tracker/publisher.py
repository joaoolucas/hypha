"""Alert publishers. Two backends, same interface:

  • UserbotPublisher — posts via a Telethon user session (a dedicated Premium account that's a
    channel admin). Only a *user* can render custom emoji in a channel, so this is what turns the
    plain venue char into the branded 🟡 DeDust / 🔵 STON.fi logos.
  • BotPublisher — posts via the aiogram bot (plain emoji). Fallback when no userbot is configured.

publish(channel, html, venue_emoji) -> bool. The html uses <b>/<a>/<code>, common to both.
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

    async def publish(self, channel: str, html: str, emojis: list[tuple[str, int]]) -> bool:
        if not channel:
            log.warning("no_alerts_channel_configured")
            return False
        try:
            await self.bot.send_message(_target(channel), html, disable_web_page_preview=True)
            return True
        except Exception as exc:  # noqa: BLE001 — one bad post must not kill the poller
            log.warning("publish_failed", error=str(exc))
            return False

    async def close(self) -> None:
        try:
            await self.bot.session.close()
        except Exception:  # noqa: BLE001
            pass


class UserbotPublisher:
    def __init__(self, api_id: int, api_hash: str, session: str):
        from telethon import TelegramClient
        from telethon.sessions import StringSession
        self._client = TelegramClient(StringSession(session), api_id, api_hash)

    async def start(self) -> None:
        await self._client.connect()
        if not await self._client.is_user_authorized():
            raise RuntimeError("userbot session is not authorized (regenerate the session string)")

    async def publish(self, channel: str, html: str, emojis: list[tuple[str, int]]) -> bool:
        if not channel:
            log.warning("no_alerts_channel_configured")
            return False
        from telethon.extensions import html as tl_html
        from telethon.tl.types import MessageEntityCustomEmoji
        text, entities = tl_html.parse(html)
        for char, doc_id in emojis or []:
            idx = text.find(char)
            if idx != -1:
                offset = len(text[:idx].encode("utf-16-le")) // 2
                length = len(char.encode("utf-16-le")) // 2
                entities.append(MessageEntityCustomEmoji(offset, length, doc_id))
        try:
            await self._client.send_message(_target(channel), text,
                                            formatting_entities=entities, link_preview=False)
            return True
        except Exception as exc:  # noqa: BLE001
            log.warning("publish_failed", error=str(exc))
            return False

    async def close(self) -> None:
        try:
            await self._client.disconnect()
        except Exception:  # noqa: BLE001
            pass
