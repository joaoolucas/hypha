"""Whale-alert rendering + publishing (the channel side). The unit is a single trade, not an
on-demand report. One scannable card: headline (who/what/size in TON), the token's market
snapshot, the trader context (🐋/👣), CA + links, and a Buy button.
"""

from __future__ import annotations

import html
from urllib.parse import quote

import structlog
from aiogram import Bot
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from ..models import TokenReport, Trade, TraderContext, TradeSide
from ..referral.router import build_buy
from ..utils import fmt_usd, fmt_price, to_friendly
from . import ui

log = structlog.get_logger(__name__)


def _esc(s: str | None) -> str:
    return html.escape(s or "")


def _pct(p: float | None) -> str:
    if p is None:
        return ""
    arrow = "📈" if p >= 0 else "📉"
    return f"{arrow} {p:+.0f}% (24h)" if abs(p) >= 10 else f"{arrow} {p:+.1f}% (24h)"


def _short(addr: str) -> str:
    return f"{_esc(addr[:6])}…{_esc(addr[-4:])}"


def _trader_link(raw: str) -> str:
    friendly = to_friendly(raw)
    return f'<a href="https://tonviewer.com/{quote(friendly, safe="")}?section=tokens">{_short(friendly)}</a>'


def _fmt_ton(ton: float) -> str:
    return f"{ton:,.0f}" if ton >= 10 else f"{ton:.1f}"


# Plain Unicode circles: Telegram won't render bot custom emoji in *channels* without a
# Fragment-purchased username, so the branded NoNameDev logos (🟡=5391224493911876583,
# 🔵=5388852301869916327) only fall back to these here. Kept as IDs in case we ever enable them.
_VENUE_DISPLAY = {"dedust": "🟡 DeDust", "stonfi": "🔵 STON.fi"}


def _venue(v: str) -> str:
    low = (v or "").lower()
    return _VENUE_DISPLAY.get(low, low.title() if low else "")


def _size(trade: Trade) -> str:
    """Size in TON with USD in parens, e.g. '100 TON ($285) · $DUROVIUS'. Falls back to USD,
    then bare symbol, when the TON leg / price is unknown."""
    sym = f"${_esc(trade.token_symbol or '?')}"
    if trade.ton_value and trade.ton_value > 0:
        usd = f" ({fmt_usd(trade.usd)})" if trade.usd and trade.usd > 0 else ""
        return f"{_fmt_ton(trade.ton_value)} TON{usd} · {sym}"
    if trade.usd and trade.usd > 0:
        return f"{fmt_usd(trade.usd)} · {sym}"
    return sym


def _headline(trade: Trade, ctx: TraderContext) -> str:
    size = _size(trade)
    if trade.side == TradeSide.BUY:
        if ctx.is_whale:
            return f"🐋 <b>WHALE BUY · {size}</b>"
        if ctx.is_followed:
            return f"👣 <b>FOLLOWED BUY · {size}</b>"
        return f"🟢 <b>BUY · {size}</b>"
    if ctx.is_whale:
        return f"🐋📉 <b>WHALE SELL · {size}</b>"
    return f"🔴 <b>SELL · {size}</b>"


def render_alert(
    trade: Trade,
    ctx: TraderContext,
    report: TokenReport,
    *,
    promoted: bool = False,
) -> tuple[str, InlineKeyboardMarkup | None]:
    t, d = report.token, report.dex
    head = _headline(trade, ctx)
    venue = _venue(trade.venue or (d.venues[0] if d and d.venues else ""))
    if venue:
        head = f"{head} - {venue}"
    L: list[str] = [head]

    # market snapshot
    if d:
        price = f"💵 {fmt_price(d.price_usd)}"
        chg = _pct(d.price_change_24h)
        L.append(f"{price}  {chg}".rstrip())
        L.append(f"💰 MC {fmt_usd(d.market_cap_usd)} · 💧 {fmt_usd(d.liquidity_usd)} · 📊 {fmt_usd(d.volume24h_usd)}")

    # trader context
    L.append("")
    if ctx.excluded:
        L.append(f"👤 {_trader_link(ctx.address)} <i>(router/contract)</i>")
    else:
        bits = [f"👤 {_trader_link(ctx.address)}"]
        if ctx.portfolio_usd > 0:
            bits.append(f"💼 {fmt_usd(ctx.portfolio_usd)}")
        if ctx.is_followed:
            bits.append("👣 followed")
        L.append(" · ".join(bits))
        bags = " · ".join(f"${_esc(b['symbol'])} {fmt_usd(b['usd'])}" for b in ctx.top_bags if b.get("symbol"))
        if bags:
            L.append(f"   {bags}")
    if promoted:
        L.append(f"⭐ <i>added to the followed list — {ctx.big_buys} big buys lately</i>")

    # identity + links
    L += ["", f"<code>{_esc(t.address)}</code>", ui.viewer_links(t.address)]

    kb_rows: list[list[InlineKeyboardButton]] = []
    buy = build_buy(report)
    if buy:
        kb_rows.append([InlineKeyboardButton(text=buy["label"], url=buy["url"])])
    kb_rows.append([InlineKeyboardButton(
        text="📊 Chart",
        url=f"https://www.geckoterminal.com/ton/pools/{quote(trade.pool_address, safe='')}"
        if trade.pool_address else f"https://www.geckoterminal.com/ton/tokens/{quote(t.address, safe='')}",
    )])
    return "\n".join(L), InlineKeyboardMarkup(inline_keyboard=kb_rows)


def _channel_target(channel_id: str) -> str | int:
    """Numeric ids (-100…) must be passed as int; @handles as str."""
    s = channel_id.strip()
    try:
        return int(s)
    except ValueError:
        return s


async def publish_alert(bot: Bot, channel_id: str, text: str, kb: InlineKeyboardMarkup | None) -> bool:
    if not channel_id:
        log.warning("no_alerts_channel_configured")
        return False
    try:
        await bot.send_message(
            _channel_target(channel_id), text,
            reply_markup=kb, disable_web_page_preview=True,
        )
        return True
    except Exception as exc:  # noqa: BLE001 — a single bad post must not kill the poller
        log.warning("publish_failed", error=str(exc))
        return False
