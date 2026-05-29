"""Mushroom-themed copy + report rendering. All user-facing strings live here (SPEC.md §7).

Cards are built as clean, scannable blocks of labelled metric lines (Telegram HTML) — header
+ copyable CA + viewer links + market block + holder block + Hypha Score (colour dots) +
flags. Verbose methodology notes live in the detail views, not the main card.
"""

from __future__ import annotations

import html
from urllib.parse import quote

from ..models import TokenReport
from ..utils import fmt_int, fmt_price, fmt_usd

INTRO = (
    "🍄 <b>Hypha</b> — I sense the health of TON tokens through their mycelium.\n\n"
    "<b>Just paste a token address (CA)</b> and I'll show it all in one card — price, "
    "momentum, holder growth, and whether the top holders are 🐋 <b>whales</b>. No commands needed.\n\n"
    "<i>Hypha is a heuristic risk aid, not financial advice.</i>"
)

HELP = INTRO
SPROUTING = "🍄 <i>sprouting analysis… reading the mycelium</i>"
SCANNING = "🐋 <i>scanning the top wallets' portfolios…</i>"
BAD_ADDRESS = "🍄 That doesn't look like a TON address. Paste an <code>EQ…</code> / <code>UQ…</code> jetton address."
RATE_LIMITED = "🍄 Easy, sporeling — too many requests. Try again in a minute."

def _esc(s: str | None) -> str:
    return html.escape(s or "")


def _pct(pct: float | None) -> str:
    if pct is None:
        return "—"
    return f"{pct:+.0f}%" if abs(pct) >= 10 else f"{pct:+.1f}%"


def _hero_change(pct: float | None) -> str:
    if pct is None:
        return ""
    return f"📈 <b>{_pct(pct)}</b>" if pct >= 0 else f"📉 <b>{_pct(pct)}</b>"


def _ago(secs: float) -> str:
    if secs < 3600:
        return f"{round(secs / 60)}m"
    if secs < 86400:
        return f"{round(secs / 3600)}h"
    return f"{round(secs / 86400)}d"


def _growth(h) -> str:
    """Holder growth since the last snapshot, e.g. '· +12 in 7m'. Empty if no movement yet."""
    if h.growth_delta is None or h.growth_secs is None or h.growth_delta == 0:
        return ""
    return f" · {h.growth_delta:+d} in {_ago(h.growth_secs)}"


def _short(addr: str) -> str:
    return f"{_esc(addr[:6])}…{_esc(addr[-4:])}"


def viewer_links(addr: str) -> str:
    a = quote(addr, safe="")
    return (
        f'🔎 <a href="https://tonviewer.com/{a}">Tonviewer</a> · '
        f'🦎 <a href="https://www.geckoterminal.com/ton/tokens/{a}">GeckoTerminal</a> · '
        f'🦅 <a href="https://dexscreener.com/ton/{a}">DexScreener</a>'
    )


def _verification_mark(t) -> str:
    if t.verification == "whitelist":
        return " ✅"
    if t.verification == "blacklist":
        return " ⛔"
    return ""


def _smart_money(pf) -> list[str]:
    """The headline signal: how many top holders are whales + what they pile into."""
    if not pf or not pf.scanned:
        return []
    n, whales = pf.scanned, pf.whale_wallets
    if whales == 0:
        head = f"🐋 <b>Smart Money</b> — none of the top {n} are whales"
    else:
        head = f"🐋 <b>Smart Money</b> — {whales}/{n} top holders are whales"
    L = ["", head]
    # what they collectively pile into (proven big money's other bags)
    bags = [t for t in pf.shared_tokens if t.whales > 0][:3]
    if bags:
        joined = " · ".join(f"${_esc(t.symbol)} ({t.whales}🐋)" for t in bags)
        L.append(f"also holding: {joined}")
    return L


def render_report(report: TokenReport, pf=None) -> str:
    """The one card. Everything lives here: price, momentum, holders+growth, and the
    smart-money read on the top holders. No sub-tabs."""
    if not report.holders and not report.dex:
        msg = report.errors[0] if report.errors else "couldn't analyze this token"
        return f"🍄 {_esc(msg)}"

    t, h, d = report.token, report.holders, report.dex
    L: list[str] = []

    # ── header: name + hero price/change (what the eye should hit first) ──
    name = f" · {_esc(t.name)}" if t.name else ""
    L.append(f"🍄 <b>${_esc(t.symbol or '?')}</b>{_verification_mark(t)}{name}")
    if d:
        L.append(f"💵 <b>{fmt_price(d.price_usd)}</b>   {_hero_change(d.price_change_24h)}".rstrip())
        L.append(f"💰 MC <b>{fmt_usd(d.market_cap_usd)}</b> · 💧 Liq {fmt_usd(d.liquidity_usd)} · 📊 Vol {fmt_usd(d.volume24h_usd)}")
    else:
        L.append("<i>market data unavailable</i>")

    # ── momentum (memecoin gold) ──
    if d and any(v is not None for v in (d.change_5m, d.change_1h, d.price_change_24h)):
        L += ["", "🚀 <b>Momentum</b>",
              f"5m {_pct(d.change_5m)} · 1h {_pct(d.change_1h)} · 24h {_pct(d.price_change_24h)}"]
        if d.vol_trend:
            L.append(f"Volume: {d.vol_trend}")

    # ── holders + growth ──
    if h:
        L += ["", f"👥 <b>{fmt_int(h.holders_count)} holders</b>{_growth(h)}",
              f"🔝 Top10 {h.top10_pct}% · Top20 {h.top20_pct}%"]

    # ── smart money (the headline signal, inline) ──
    L += _smart_money(pf)

    # ── identity ──
    L += ["", f"<code>{_esc(t.address)}</code>", viewer_links(t.address)]
    L.append("\n👇 <i>tap to dig into the whales · not financial advice</i>")
    return "\n".join(L)


def render_whales(report: TokenReport, pf) -> str:
    """Drill-down: the full top-holder portfolio scan behind the card's Smart Money line."""
    sym = _esc(report.token.symbol or "?")
    if not pf or (not pf.shared_tokens and not pf.wallets):
        note = _esc(pf.notes[0]) if pf and pf.notes else "no portfolio data"
        return f"🐋 <b>Top Wallets — ${sym}</b>\n{note}."

    L = [
        f"🐋 <b>Top Wallets — ${sym}</b>",
        f"<i>{pf.whale_wallets}/{pf.scanned} are whales · median bag {fmt_usd(pf.median_portfolio_usd)}</i>",
    ]
    if pf.shared_tokens:
        L += ["", "<b>Shared bags</b> — held by multiple top wallets:"]
        for t in pf.shared_tokens:
            tick = " ✅" if t.verified else ""
            whales = f" · {t.whales}🐋" if t.whales else ""
            L.append(f"• ${_esc(t.symbol)}{tick} — {t.held_by} wallets · {fmt_usd(t.total_usd)}{whales}")
    if pf.wallets:
        L += ["", "<b>Notable wallets</b>:"]
        for i, w in enumerate(pf.wallets[:6], 1):
            bags = ", ".join(
                f"${_esc(b['symbol'])}{'🐋' if b['whale'] else ''}"
                for b in w.top_bags if b.get("symbol")
            )
            L.append(f"{i}. <code>{_short(w.owner)}</code> · {fmt_usd(w.portfolio_usd)} · {w.token_count} tokens")
            if bags:
                L.append(f"    holds {bags}")
    L.append(f"\n<i>🐋 = a single bag worth ≥ {fmt_usd(pf.whale_usd)}. Not financial advice.</i>")
    return "\n".join(L)
