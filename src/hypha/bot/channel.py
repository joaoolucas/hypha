"""Whale-alert rendering (the channel side). The unit is a single trade, not an on-demand
report. render_alert returns (html, venue_emoji): the html uses tags common to both aiogram and
Telethon (<b>/<a>/<code>) so either publisher can send it; venue_emoji is the (char, doc_id) of
the branded custom emoji the userbot publisher upgrades the plain venue char into. Actions are
inline links, not buttons (a userbot can't attach inline keyboards).
"""

from __future__ import annotations

import html
from urllib.parse import quote

from ..models import TokenReport, Trade, TraderContext, TradeSide
from ..referral.router import build_buy
from ..utils import fmt_usd, fmt_price, to_friendly

# Branded explorer emoji from the NoNameDev set (char shown as fallback; userbot upgrades it).
_LINK_EMOJI = {
    "tonviewer": ("🔷", 5364245841525645356),
    "dexscreener": ("🦅", 5391144822268537893),
}


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


# venue -> (base emoji char, display name, branded custom-emoji id from the NoNameDev set).
# The char goes in the text; the userbot publisher upgrades it to the branded emoji via its id.
_VENUE = {
    "dedust": ("🟡", "DeDust", 5391224493911876583),
    "stonfi": ("🔵", "STON.fi", 5388852301869916327),
}


def _venue(v: str) -> tuple[str, tuple[str, int] | None]:
    """Return (display_text, (emoji_char, custom_emoji_id) | None) for a venue."""
    low = (v or "").lower()
    if low in _VENUE:
        char, name, eid = _VENUE[low]
        return f"{char} {name}", (char, eid)
    return (low.title() if low else "", None)


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
) -> tuple[str, list[tuple[str, int]]]:
    """Return (html, emojis). emojis is a list of (char, custom_emoji_id) the userbot publisher
    upgrades to branded emoji (venue + explorer links); the bot path shows the plain chars."""
    t, d = report.token, report.dex
    head = _headline(trade, ctx)
    venue_text, venue_emoji = _venue(trade.venue or (d.venues[0] if d and d.venues else ""))
    if venue_text:
        head = f"{head} - {venue_text}"
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

    # identity + footer: Buy + Tonviewer + DexScreener (branded), always friendly address
    addr = to_friendly(t.address, bounceable=True)
    a = quote(addr, safe="")
    tv_char, tv_id = _LINK_EMOJI["tonviewer"]
    dx_char, dx_id = _LINK_EMOJI["dexscreener"]
    foot = []
    buy = build_buy(report)
    if buy:
        foot.append(f'🛒 <a href="{_esc(buy["url"])}">Buy</a>')
    foot.append(f'{tv_char} <a href="https://tonviewer.com/{a}">Tonviewer</a>')
    foot.append(f'{dx_char} <a href="https://dexscreener.com/ton/{a}">DexScreener</a>')
    L += ["", f"<code>{_esc(addr)}</code>", " · ".join(foot)]

    emojis = [e for e in (venue_emoji, (tv_char, tv_id), (dx_char, dx_id)) if e]
    return "\n".join(L), emojis
