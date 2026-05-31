"""Whale-alert rendering. render_alert returns (html, keyboard): the message body (plain emoji)
and an inline button grid (DTrade/RedoTrade trade bots + Tonviewer/DexScreener explorers).
Posted via the bot so the buttons work.
"""

from __future__ import annotations

import html
from urllib.parse import quote

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from ..models import TokenReport, Trade, TraderContext, TradeSide
from ..utils import fmt_price, fmt_usd, to_friendly

# Trade-bot deep links (referral); the friendly token address is appended to the start payload.
_DTRADE = "https://t.me/dtrade?start=25BSDKtN0o_"
_REDOTRADE = "https://t.me/redotrade?start=mAJe4lm0_"
_VENUE_NAME = {"stonfi": "STON.fi", "dedust": "DeDust", "uranus": "Uranus"}


def _esc(s: str | None) -> str:
    return html.escape(s or "")


def _pct(p: float | None) -> str:
    if p is None:
        return ""
    return f"{p:+.0f}%" if abs(p) >= 10 else f"{p:+.1f}%"


def _short(addr: str) -> str:
    return f"{_esc(addr[:6])}…{_esc(addr[-4:])}"


def _trader_link(raw: str) -> str:
    friendly = to_friendly(raw)
    return f'<a href="https://tonviewer.com/{quote(friendly, safe="")}?section=tokens">{_short(friendly)}</a>'


def _fmt_ton(ton: float) -> str:
    return f"{ton:,.0f}" if ton >= 10 else f"{ton:.1f}"


def _venue_name(v: str) -> str:
    low = (v or "").lower()
    return _VENUE_NAME.get(low, low.title() if low else "")


def _size(trade: Trade) -> str:
    """'826 TON ($1.6k) · $UTYA' — TON with USD in parens, falling back to USD then bare symbol."""
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
        return f"🐋 <b>WHALE BUY · {size}</b>" if ctx.is_whale else f"🟢 <b>BUY · {size}</b>"
    return f"🐋📉 <b>WHALE SELL · {size}</b>" if ctx.is_whale else f"🔴 <b>SELL · {size}</b>"


def _keyboard(addr: str) -> InlineKeyboardMarkup:
    a = quote(addr, safe="")
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⚡ DTrade", url=_DTRADE + addr),
         InlineKeyboardButton(text="🐶 RedoTrade", url=_REDOTRADE + addr)],
        [InlineKeyboardButton(text="🔎 Tonviewer", url=f"https://tonviewer.com/{a}"),
         InlineKeyboardButton(text="🦅 DexScreener", url=f"https://dexscreener.com/ton/{a}")],
    ])


def render_alert(
    trade: Trade,
    ctx: TraderContext,
    report: TokenReport,
) -> tuple[str, InlineKeyboardMarkup]:
    t, d = report.token, report.dex
    addr = to_friendly(t.address, bounceable=True)
    venue = _venue_name(trade.venue or (d.venues[0] if d and d.venues else ""))
    head = _headline(trade, ctx)
    if venue:
        head = f"{head} via {venue}"
    L: list[str] = [head]

    if d:
        chg = _pct(d.price_change_24h)
        price = f"💰 Price {fmt_price(d.price_usd)}"
        if chg:
            arrow = "📉" if (d.price_change_24h or 0) < 0 else "📈"
            price += f" · {arrow} 24h {chg}"
        L += ["", price,
              f"🏦 MC {fmt_usd(d.market_cap_usd)} · 💧 Liq {fmt_usd(d.liquidity_usd)} · 📊 Vol {fmt_usd(d.volume24h_usd)}"]

    L.append("")
    if ctx.excluded:
        L.append(f"👤 {_trader_link(ctx.address)} <i>(router/contract)</i>")
    else:
        line = f"👤 {_trader_link(ctx.address)}"
        if ctx.portfolio_usd > 0:
            line += f" · 💼 {fmt_usd(ctx.portfolio_usd)} Wallet"
        L.append(line)
        holdings = []
        if ctx.ton_balance > 0:
            holdings.append(f"• {_fmt_ton(ctx.ton_balance)} TON ({fmt_usd(ctx.ton_value_usd)})")
        holdings += [f"• ${_esc(b['symbol'])} {fmt_usd(b['usd'])}"
                     for b in ctx.top_bags if b.get("symbol")][:3]
        if holdings:
            hurl = f'https://tonviewer.com/{quote(to_friendly(ctx.address), safe="")}?section=tokens'
            L += ["", f'👜 <a href="{hurl}">Holdings:</a>']   # tap-through to the whale's full holdings
            L += holdings

    L += ["", f"🧬 CA: <code>{_esc(addr)}</code>"]
    return "\n".join(L), _keyboard(addr)
