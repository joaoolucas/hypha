"""Mushroom-themed copy + report rendering. All user-facing strings live here (SPEC.md §7).

Cards are built as clean, scannable blocks of labelled metric lines (Telegram HTML) — header
+ copyable CA + viewer links + market block + holder block + Hypha Score (colour dots) +
flags. Verbose methodology notes live in the detail views, not the main card.
"""

from __future__ import annotations

import html
from urllib.parse import quote

from ..models import LockStatus, TokenReport
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

# LP status as shown on the card. UNLOCKED currently only means "not verified" (Phase 2 will
# do real lock detection), so we label it honestly rather than asserting "unlocked".
_LP_DISPLAY = {
    LockStatus.BURNED: "🔥 LP burned",
    LockStatus.LOCKED: "🔒 LP locked",
    LockStatus.PARTIAL: "🧩 LP partial",
    LockStatus.UNLOCKED: "🔓 LP unverified",
    LockStatus.NONE: "🚫 no LP",
}


def _esc(s: str | None) -> str:
    return html.escape(s or "")


def _dot(score: float | None) -> str:
    if score is None:
        return "⚪"
    if score >= 70:
        return "🟢"
    if score >= 40:
        return "🟡"
    return "🔴"


def _change(pct: float | None) -> str:
    if pct is None:
        return ""
    arrow = "🔼" if pct >= 0 else "🔽"
    return f" {arrow} {pct:+.1f}%"


def _short(addr: str) -> str:
    return f"{_esc(addr[:6])}…{_esc(addr[-4:])}"


def _authority(t) -> str:
    if t.mintable:
        return "⚠️ mintable"
    if t.admin_address:
        return "🔑 admin active"
    return "👑 renounced ✅"


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
    if report.errors and not report.score:
        return f"🍄 {_esc(report.errors[0])}"

    t, h, d, lp, sc = report.token, report.holders, report.dex, report.launchpad, report.score
    L: list[str] = []

    # ── header ──
    name = f" · {_esc(t.name)}" if t.name else ""
    L.append(f"🍄 <b>${_esc(t.symbol or '?')}</b>{_verification_mark(t)}{name}")
    if sc:
        L.append(f"{sc.badge} <b>{_esc(sc.tier)}</b> · {sc.score}/100 · confidence {sc.confidence}")

    # ── CA + viewer links ──
    L += ["", f"<code>{_esc(t.address)}</code>", viewer_links(t.address)]

    # ── market block ──
    L.append("")
    if d:
        L.append(
            f"💵 <b>{fmt_price(d.price_usd)}</b>{_change(d.price_change_24h)} · "
            f"📈 MC <b>{fmt_usd(d.market_cap_usd)}</b> · 💧 Liq <b>{fmt_usd(d.liquidity_usd)}</b>"
        )
        L.append(f"📊 Vol24h {fmt_usd(d.volume24h_usd)} · {_LP_DISPLAY.get(d.lp_status, '')} · {_authority(t)}")
    else:
        L.append("💵 <i>market data unavailable</i> · " + _authority(t))

    # ── holder block ──
    if h:
        L.append(f"👥 {fmt_int(h.holders_count)} holders · 🔝 Top10 {h.top10_pct}% · 🛠 Dev {h.dev_pct}%")

    # ── launchpad / status ──
    if lp and lp.launchpad:
        grad = f" ({lp.graduation_dex})" if lp.graduation_dex else ""
        L.append(f"🚀 {_esc(lp.launchpad)} • {lp.status.value}{grad}")
    elif lp:
        L.append(f"🚀 {lp.status.value}")

    # ── Hypha Score breakdown (colour dots, no code block) ──
    if sc:
        L += ["", "<b>Hypha Score</b>"]
        for p in sc.pillars:
            val = "n/a" if p.score is None else str(int(round(p.score)))
            L.append(f"{_dot(p.score)} {p.label} — {val}")

    # ── flags ──
    if sc and sc.poison_flags:
        L.append("")
        L += [f"☠️ <b>{_esc(f)}</b>" for f in sc.poison_flags]

    L += ["", "👇 <i>tap a button below · not financial advice</i>"]
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
        f"📐 Gini {h.gini} · 🛠 Dev {h.dev_pct}% · 🌊 pools/burn {h.excluded_pct}%",
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
        f"💵 Price {fmt_price(d.price_usd)}{_change(d.price_change_24h)}",
        f"📈 MC {fmt_usd(d.market_cap_usd)} · 💧 Liq {fmt_usd(d.liquidity_usd)} · 📊 Vol24h {fmt_usd(d.volume24h_usd)}",
        f"{_LP_DISPLAY.get(d.lp_status, '')} · 🏦 {', '.join(d.venues) or 'no venue'}",
    ]
    if d.liq_to_mcap_pct is not None:
        L.append(f"⚖️ Liq/MC {d.liq_to_mcap_pct}%")
    if d.notes:
        L += ["", *(f"• <i>{_esc(n)}</i>" for n in d.notes[:3])]
    return "\n".join(L)
