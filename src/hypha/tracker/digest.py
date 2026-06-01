"""Daily whale digest — a leaderboard recap posted to the channel.

Aggregates the day's whale BUY and SELL alerts (the `alerts` table) by token, ranks the top N of
each by total USD, and posts a compact two-section leaderboard. Each token links to its DexScreener
page (chart + live transactions). Reads the alert log, so it needs DATABASE_URL; with no DB (or no
data) it logs and no-ops.

  🟢🐋 Top TON Meme Whale Buys Today

  1. $UTYA — $12.4k
  2. $FLOWGAIA — $8.1k
  ...

  🔴🐋 Top TON Meme Whale Sells Today

  1. $DUSTGANG — $4.2k
  ...

  Full live feed: @WhaleSignalsTON
"""

from __future__ import annotations

import asyncio
import html
import os
from datetime import datetime, timedelta, timezone
from urllib.parse import quote

import structlog
from sqlalchemy import func, select

from ..analysis.discovery import is_lp_or_staked, is_quote_asset, is_unknown_symbol
from ..config import Settings, get_settings
from ..db.models import Alert
from ..db.session import session

log = structlog.get_logger(__name__)


def _esc(s: str | None) -> str:
    return html.escape(s or "")


def _short(addr: str) -> str:
    return f"{addr[:6]}…{addr[-4:]}" if len(addr) > 12 else addr


def _since(window_hours: int | None) -> datetime:
    """Lower bound for 'today': the start of the current UTC day, or a rolling window if given."""
    now = datetime.now(timezone.utc)
    if window_hours:
        return now - timedelta(hours=window_hours)
    return now.replace(hour=0, minute=0, second=0, microsecond=0)


def _feed_handle(s: Settings) -> str:
    """@handle for the 'Full live feed' link — explicit config, else the channel id if it's a handle."""
    if s.feed_handle:
        return s.feed_handle.lstrip("@")
    cid = (s.alerts_channel_id or "").strip()
    return cid.lstrip("@") if cid.startswith("@") else ""


async def top_whale_trades(since: datetime, limit: int, side: str = "buy") -> list[tuple[str, str, float, int]]:
    """[(symbol, token, total_usd, trades)] — whale `side` trades since `since`, grouped by token,
    biggest first. The label is the best non-empty symbol seen for that token."""
    db = session()
    if db is None:
        return []
    label = func.max(func.nullif(Alert.symbol, ""))       # ignore blank symbols when labelling
    total = func.sum(Alert.usd)
    stmt = (
        select(Alert.token, label, total, func.count(Alert.id))
        .where(Alert.side == side, Alert.is_whale.is_(True), Alert.created_at >= since)
        .group_by(Alert.token)
        .order_by(total.desc())
        .limit(limit * 4)                                  # over-fetch; quote/LST/LP rows dropped below
    )
    try:
        async with db:
            rows = (await db.execute(stmt)).all()
    except Exception as exc:  # noqa: BLE001 — the digest is best-effort; a DB hiccup just skips it
        log.warning("digest_query_failed", error=str(exc))
        return []
    out: list[tuple[str, str, float, int]] = []
    for tok, sym, tot, n in rows:                          # guard legacy/edge rows: no $TON, $tsTON, LP, UNKWN…
        if is_quote_asset(sym) or is_lp_or_staked(sym) or is_unknown_symbol(sym):
            continue
        out.append((sym or "", tok, float(tot or 0.0), int(n)))
        if len(out) >= limit:
            break
    return out


def _rank_lines(rows: list[tuple[str, str, float, int]]) -> list[str]:
    """Numbered leaderboard lines; each token links to its DexScreener page (chart + transactions)."""
    from ..utils import fmt_usd   # local import keeps this module import-light for the CLI path

    out: list[str] = []
    for i, (sym, tok, total_usd, _n) in enumerate(rows, 1):
        name = f"${_esc(sym)}" if sym else _esc(_short(tok))
        url = f"https://dexscreener.com/ton/{quote(tok, safe='')}"
        out.append(f'{i}. <a href="{url}">{name}</a> — {fmt_usd(total_usd)}')
    return out


def render_digest(
    buys: list[tuple[str, str, float, int]],
    sells: list[tuple[str, str, float, int]],
    feed_handle: str,
) -> str:
    lines: list[str] = []
    if buys:
        lines += ["<b>🟢🐋 Top TON Meme Whale Buys Today</b>", "", *_rank_lines(buys)]
    if sells:
        if lines:
            lines.append("")
        lines += ["<b>🔴🐋 Top TON Meme Whale Sells Today</b>", "", *_rank_lines(sells)]
    if feed_handle:
        lines += ["", f'Full live feed: <a href="https://t.me/{_esc(feed_handle)}">@{_esc(feed_handle)}</a>']
    return "\n".join(lines)


async def build_and_post_digest(publisher, s: Settings, *, window_hours: int | None = None) -> bool:
    """Build today's buy/sell leaderboards and post them. No-ops (logs) when there's nothing to rank."""
    since = _since(window_hours)
    buys = await top_whale_trades(since, s.digest_top_n, "buy")
    sells = await top_whale_trades(since, s.digest_top_n, "sell")
    if not buys and not sells:
        log.info("digest_skip_empty")
        return False
    channel = s.digest_channel_id or s.alerts_channel_id
    html_body = render_digest(buys, sells, _feed_handle(s))
    ok = await publisher.publish(channel, html_body, None)
    log.info("digest_posted", buys=len(buys), sells=len(sells), ok=ok)
    return ok


async def _main() -> None:
    """Manual one-off: `python -m hypha.tracker.digest`. Set DIGEST_WINDOW_HOURS to override the
    'today' window (e.g. DIGEST_WINDOW_HOURS=24 for a rolling day)."""
    from aiogram import Bot
    from aiogram.client.default import DefaultBotProperties
    from aiogram.enums import ParseMode

    from .publisher import BotPublisher

    s = get_settings()
    publisher = BotPublisher(Bot(s.bot_token, default=DefaultBotProperties(parse_mode=ParseMode.HTML)))
    try:
        hrs = os.getenv("DIGEST_WINDOW_HOURS")
        posted = await build_and_post_digest(publisher, s, window_hours=int(hrs) if hrs else None)
        print("posted" if posted else "nothing to post")
    finally:
        await publisher.close()


if __name__ == "__main__":
    asyncio.run(_main())
