"""Whale-alert rendering + publishing (the channel side). Mushroom voice, like ui.py, but the
unit is a single trade, not an on-demand report. One scannable card: headline (who/what/size),
the token's market + Hypha read, the trader context (🐋/👣), CA + links, and a Buy button.
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


def _lp(report: TokenReport) -> str:
    d = report.dex
    if not d:
        return ""
    return {
        "burned": "💧 LP 🔥burned", "locked": "💧 LP 🔒locked",
        "partial": "💧 LP partial", "unlocked": "💧 LP ⚠️unlocked",
    }.get(getattr(d.lp_status, "value", str(d.lp_status)), "")


def _headline(trade: Trade, ctx: TraderContext) -> str:
    sym = f"${_esc(trade.token_symbol or '?')}"
    size = fmt_usd(trade.usd) if trade.usd and trade.usd > 0 else None
    amt = f"{size} of {sym}" if size else sym
    if trade.side == TradeSide.BUY:
        if ctx.is_whale:
            return f"🐋 <b>Whale bought {amt}</b>"
        if ctx.is_followed:
            return f"👣 <b>Followed wallet bought {amt}</b>"
        return f"🟢 <b>Big buy · {amt}</b>"
    if ctx.is_whale:
        return f"🐋📉 <b>Whale dumped {amt}</b>"
    return f"🔴 <b>Big sell · {amt}</b>"


def render_alert(
    trade: Trade,
    ctx: TraderContext,
    report: TokenReport,
    *,
    promoted: bool = False,
) -> tuple[str, InlineKeyboardMarkup | None]:
    t, d, sc = report.token, report.dex, report.score
    L: list[str] = [_headline(trade, ctx)]
    venue = trade.venue or (d.venues[0] if d and d.venues else "")
    if venue:
        L.append(f"<i>via {_esc(venue)}</i>")

    # market snapshot
    if d:
        price = f"💵 {fmt_price(d.price_usd)}"
        chg = _pct(d.price_change_24h)
        L.append(f"{price}  {chg}".rstrip())
        L.append(f"💰 MC {fmt_usd(d.market_cap_usd)} · 💧 {fmt_usd(d.liquidity_usd)} · 📊 {fmt_usd(d.volume24h_usd)}")

    # the Hypha read — the differentiator vs a dumb tracker
    if sc:
        L += ["", f"{sc.badge} <b>Hypha {sc.score}/100</b> · {_esc(sc.tier)}"]
        flags = []
        if report.holders:
            if report.holders.dev_pct:
                flags.append(f"🔑 dev {report.holders.dev_pct:.0f}%")
            if report.holders.top10_pct:
                flags.append(f"🔝 Top10 {report.holders.top10_pct:.0f}%")
        lp = _lp(report)
        if lp:
            flags.append(lp)
        if flags:
            L.append(" · ".join(flags))

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
