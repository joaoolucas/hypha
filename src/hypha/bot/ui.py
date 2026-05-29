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
    "<b>Just paste a token address (CA)</b> and I'll show everything — the <b>Hypha Score</b>, "
    "holder spread, dev allocation, liquidity &amp; launchpad status — with a menu to dig into "
    "holders, 🐋 whales and liquidity. No commands needed.\n\n"
    "<i>Shortcuts (optional):</i> /analyze · /holders · /whales · /dex\n\n"
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


def _dev_status(t, h) -> str:
    if t.mintable:
        return "⚠️ mintable"
    if not t.admin_address:
        return "renounced 👑"
    if h and h.dev_sold:
        return "sold ⚠️"
    pct = f" {h.dev_pct}%" if h and h.dev_pct else ""
    return f"holding{pct}"


def _growth(h) -> str:
    parts = []
    if h.growth_1h is not None:
        parts.append(f"{h.growth_1h:+d} 1h")
    if h.growth_24h is not None:
        parts.append(f"{h.growth_24h:+d} 24h")
    return f"  ·  📈 {' · '.join(parts)}" if parts else ""


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


def render_report(report: TokenReport) -> str:
    if not report.holders and not report.dex:
        msg = report.errors[0] if report.errors else "couldn't analyze this token"
        return f"🍄 {_esc(msg)}"

    t, h, d, lp = report.token, report.holders, report.dex, report.launchpad
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

    # ── holders + dev ──
    if h:
        L += ["", f"👥 <b>{fmt_int(h.holders_count)} holders</b>{_growth(h)}",
              f"🔝 Top10 {h.top10_pct}% · 🧑‍💻 Dev {_dev_status(t, h)}"]

    # ── status + identity ──
    L.append("")
    if lp and lp.launchpad:
        grad = f" ({lp.graduation_dex})" if lp.graduation_dex else ""
        L.append(f"🚀 {_esc(lp.launchpad)} • {lp.status.value}{grad}")
    elif lp and lp.status.value != "unknown":
        L.append(f"🚀 {lp.status.value}")
    L.append(f"<code>{_esc(t.address)}</code>")
    L.append(viewer_links(t.address))

    L.append("\n👇 <i>tap a button below · not financial advice</i>")
    return "\n".join(L)


def render_holders(report: TokenReport) -> str:
    h = report.holders
    if not h:
        return "🍄 No holder data available."
    L = [
        f"🔬 <b>Holders — ${_esc(report.token.symbol)}</b>",
        f"<code>{_esc(report.token.address)}</code>",
        "",
        f"👥 {fmt_int(h.holders_count)} holders · counted {fmt_int(h.counted_holders)}",
        f"🔝 Top1 {h.top1_pct}% · Top10 {h.top10_pct}% · Top20 {h.top20_pct}%",
        f"📐 Gini {h.gini} · 🌊 pools/burn {h.excluded_pct}%",
        f"🧑‍💻 Dev {_dev_status(report.token, h)}{_growth(h)}",
        "",
    ]
    for i, hol in enumerate(h.top_holders[:10], 1):
        tag = f" · <i>{_esc(hol.label)}</i>" if hol.label else ""
        bal = hol.balance / (10 ** report.token.decimals)
        L.append(f"{i}. <code>{_short(hol.owner)}</code> · {fmt_int(bal)}{tag}")
    if h.notes:
        L += ["", *(f"• <i>{_esc(n)}</i>" for n in h.notes[:3])]
    return "\n".join(L)


def render_whales(report: TokenReport, pf) -> str:
    sym = _esc(report.token.symbol or "?")
    if not pf or (not pf.shared_tokens and not pf.wallets):
        note = _esc(pf.notes[0]) if pf and pf.notes else "no portfolio data"
        return f"🐋 <b>Top Wallets — ${sym}</b>\n{note}."

    L = [
        f"🐋 <b>Top Wallets — ${sym}</b>",
        f"<i>scanned {pf.scanned} top holders' portfolios</i>",
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


def render_dex(report: TokenReport) -> str:
    d = report.dex
    if not d:
        return "🍄 No liquidity data available."
    L = [
        f"💧 <b>Liquidity — ${_esc(report.token.symbol)}</b>",
        f"<code>{_esc(report.token.address)}</code>",
        "",
        f"💵 Price {fmt_price(d.price_usd)}  {_hero_change(d.price_change_24h)}".rstrip(),
        f"5m {_pct(d.change_5m)} · 1h {_pct(d.change_1h)} · 24h {_pct(d.price_change_24h)}",
        f"📈 MC {fmt_usd(d.market_cap_usd)} · 💧 Liq {fmt_usd(d.liquidity_usd)} · 📊 Vol24h {fmt_usd(d.volume24h_usd)}",
        f"🏦 {', '.join(d.venues) or 'no venue'}" + (f" · Vol {d.vol_trend}" if d.vol_trend else ""),
    ]
    if d.liq_to_mcap_pct is not None:
        L.append(f"⚖️ Liq/MC {d.liq_to_mcap_pct}%")
    if d.notes:
        L += ["", *(f"• <i>{_esc(n)}</i>" for n in d.notes[:3])]
    return "\n".join(L)
