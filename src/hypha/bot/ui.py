"""Mushroom-themed copy + report rendering. All user-facing strings live here (SPEC.md §7).

Cards are built as clean, scannable blocks of labelled metric lines (Telegram HTML) — header
+ copyable CA + viewer links + market block + holder block + Hypha Score (colour dots) +
flags. Verbose methodology notes live in the detail views, not the main card.
"""

from __future__ import annotations

import html
from urllib.parse import quote

from ..models import TokenReport
from ..utils import fmt_int, fmt_price, fmt_usd, to_friendly

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


def _wallet_link(addr: str) -> str:
    """Truncated user-friendly (UQ…) address linking to that wallet's holdings on Tonviewer."""
    friendly = to_friendly(addr)
    return f'<a href="https://tonviewer.com/{quote(friendly, safe="")}?section=tokens">{_short(friendly)}</a>'


def _verification_mark(t) -> str:
    if t.verification == "whitelist":
        return " ✅"
    if t.verification == "blacklist":
        return " ⛔"
    return ""


def _smart_money(pf) -> list[str]:
    """Top-wallet signal, inline on the card: the most notable top holders, each linking to
    its Tonviewer holdings, with a stables/tokens split and the per-token USD it holds."""
    if not pf or not pf.wallets:
        return []
    L = ["", "🐋 <b>Top Wallet Signal</b>"]
    for i, w in enumerate(pf.wallets[:3], 1):
        L.append(
            f"{i}. {_wallet_link(w.owner)} — {fmt_usd(w.portfolio_usd)}"
            f"  (🪙 {fmt_usd(w.tokens_usd)} · 💵 {fmt_usd(w.stables_usd)})"
        )
        bags = " · ".join(
            f"${_esc(b['symbol'])} {fmt_usd(b['usd'])}"
            for b in w.top_bags if b.get("symbol") and b.get("usd")
        )
        if bags:
            L.append(f"   {bags}")
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

    # ── holders + growth ──
    if h:
        L += ["", f"👥 <b>{fmt_int(h.holders_count)} holders</b>{_growth(h)}",
              f"🔝 Top10 {h.top10_pct}% · Top20 {h.top20_pct}%"]

    # ── smart money (the headline signal, inline) ──
    L += _smart_money(pf)

    # ── identity ──
    L += ["", f"<code>{_esc(t.address)}</code>", viewer_links(t.address)]
    L.append("\n<i>not financial advice</i>")
    return "\n".join(L)
