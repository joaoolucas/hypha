"""Mushroom-themed copy + report rendering. All user-facing strings live here (SPEC.md §7).
Uses Telegram HTML parse mode."""

from __future__ import annotations

import html

from ..models import LockStatus, TokenReport
from ..utils import bar, fmt_int, fmt_usd

INTRO = (
    "🍄 <b>Hypha</b> — I sense the health of TON tokens through their mycelium.\n\n"
    "Send me a jetton address (or <code>/analyze &lt;address&gt;</code>) and I'll return a "
    "<b>Hypha Score</b>: holder spread, dev allocation, liquidity, launchpad status and more.\n\n"
    "Try:\n"
    "• <code>/analyze &lt;address&gt;</code> — full report\n"
    "• <code>/score &lt;address&gt;</code> — just the score card\n"
    "• <code>/holders &lt;address&gt;</code> — holder breakdown\n"
    "• <code>/whales &lt;address&gt;</code> — what the top holders also own 🐋\n"
    "• <code>/dex &lt;address&gt;</code> — liquidity &amp; LP check\n\n"
    "<i>Hypha is a heuristic risk aid, not financial advice.</i>"
)

HELP = INTRO
SPROUTING = "🍄 <i>sprouting analysis… reading the mycelium</i>"
SCANNING = "🐋 <i>scanning the top wallets' portfolios…</i>"
BAD_ADDRESS = "🍄 That doesn't look like a TON address. Paste an <code>EQ…</code> / <code>UQ…</code> jetton address."
RATE_LIMITED = "🍄 Easy, sporeling — too many requests. Try again in a minute."

_LOCK_EMOJI = {
    LockStatus.BURNED: "🔥 burned",
    LockStatus.LOCKED: "🔒 locked",
    LockStatus.PARTIAL: "🧩 partial",
    LockStatus.UNLOCKED: "🔓 unlocked",
    LockStatus.NONE: "∅ none",
}


def _esc(s: str | None) -> str:
    return html.escape(s or "")


def _pillar_lines(report: TokenReport) -> str:
    if not report.score:
        return ""
    rows = []
    for p in report.score.pillars:
        val = "n/a" if p.score is None else f"{int(round(p.score)):>3}"
        rows.append(f"{p.emoji} {p.label:<15} {val} {bar(p.score)}")
    return "\n".join(rows)


def render_score_header(report: TokenReport) -> str:
    sc = report.score
    sym = _esc(report.token.symbol or "?")
    if not sc:
        return f"🍄 <b>${sym}</b> — couldn't compute a score."
    return (
        f"🍄 <b>HYPHA REPORT — ${sym}</b>\n"
        f"{sc.badge} <b>{_esc(sc.tier)} · {sc.score}/100</b> · confidence: {sc.confidence}"
    )


def render_report(report: TokenReport) -> str:
    if report.errors and not report.score:
        return f"🍄 {_esc(report.errors[0])}"

    t, h, d, lp = report.token, report.holders, report.dex, report.launchpad
    parts = [render_score_header(report)]
    if t.name:
        parts.append(f"<i>{_esc(t.name)}</i>")
    parts.append("")
    parts.append(f"<pre>{_pillar_lines(report)}</pre>")

    # Snapshot
    snap = []
    if h:
        snap.append(
            f"Top10 {h.top10_pct}% · Top20 {h.top20_pct}% · "
            f"{fmt_int(h.holders_count)} holders · dev {h.dev_pct}%"
        )
    if d:
        lock = _LOCK_EMOJI.get(d.lp_status, "")
        snap.append(f"LP {lock} · Liq {fmt_usd(d.liquidity_usd)} · MCap {fmt_usd(d.market_cap_usd)}")
    if lp and lp.launchpad:
        grad = f" ({lp.graduation_dex})" if lp.graduation_dex else ""
        snap.append(f"Launchpad: {_esc(lp.launchpad)} → {lp.status.value}{grad}")
    elif lp:
        snap.append(f"Status: {lp.status.value}")
    if snap:
        parts.append("\n".join(snap))

    if report.score and report.score.poison_flags:
        parts.append("")
        parts += [f"☠️ <b>{_esc(f)}</b>" for f in report.score.poison_flags]

    extra_notes = []
    if h:
        extra_notes += h.notes
    if d:
        extra_notes += d.notes
    if extra_notes:
        parts.append("")
        parts += [f"• <i>{_esc(n)}</i>" for n in extra_notes[:4]]

    parts.append("\n<i>Not financial advice.</i>")
    return "\n".join(parts)


def render_holders(report: TokenReport) -> str:
    h = report.holders
    if not h:
        return "🍄 No holder data available."
    lines = [f"🍄 <b>Holders — ${_esc(report.token.symbol)}</b>", ""]
    lines.append(f"Holders: {fmt_int(h.holders_count)} · counted: {fmt_int(h.counted_holders)}")
    lines.append(f"Top1 {h.top1_pct}% · Top10 {h.top10_pct}% · Top20 {h.top20_pct}%")
    lines.append(f"Gini {h.gini} · dev {h.dev_pct}% · pools/burn excluded {h.excluded_pct}%")
    lines.append("")
    for i, hol in enumerate(h.top_holders[:10], 1):
        tag = f" <i>{_esc(hol.label)}</i>" if hol.label else ""
        bal = hol.balance / (10 ** report.token.decimals)
        lines.append(f"{i}. <code>{_esc(hol.owner[:6])}…{_esc(hol.owner[-4:])}</code> {fmt_int(bal)}{tag}")
    return "\n".join(lines)


def render_whales(report: TokenReport, pf) -> str:
    sym = _esc(report.token.symbol or "?")
    if not pf or (not pf.shared_tokens and not pf.wallets):
        note = _esc(pf.notes[0]) if pf and pf.notes else "no portfolio data"
        return f"🐋 <b>Top Wallets — ${sym}</b>\n{note}."

    lines = [
        f"🐋 <b>Top Wallets — ${sym}</b>",
        f"<i>scanned {pf.scanned} top holders' portfolios</i>",
    ]

    if pf.shared_tokens:
        lines += ["", "<b>Shared bags</b> — held by multiple top wallets:"]
        for t in pf.shared_tokens:
            tick = "☑️" if t.verified else ""
            whales = f" · {t.whales}🐋" if t.whales else ""
            lines.append(f"• ${_esc(t.symbol)}{tick} — {t.held_by} wallets · {fmt_usd(t.total_usd)}{whales}")

    if pf.wallets:
        lines += ["", "<b>Notable wallets</b>:"]
        for i, w in enumerate(pf.wallets[:6], 1):
            bags = ", ".join(
                f"${_esc(b['symbol'])}{'🐋' if b['whale'] else ''}"
                for b in w.top_bags if b.get("symbol")
            )
            short = f"{_esc(w.owner[:6])}…{_esc(w.owner[-4:])}"
            lines.append(f"{i}. <code>{short}</code> · {fmt_usd(w.portfolio_usd)} · {w.token_count} tokens")
            if bags:
                lines.append(f"    holds {bags}")

    lines.append(f"\n<i>🐋 = a single bag worth ≥ {fmt_usd(pf.whale_usd)}. Not financial advice.</i>")
    return "\n".join(lines)


def render_dex(report: TokenReport) -> str:
    d = report.dex
    if not d:
        return "🍄 No liquidity data available."
    lock = _LOCK_EMOJI.get(d.lp_status, "")
    lines = [
        f"🍄 <b>Liquidity — ${_esc(report.token.symbol)}</b>",
        "",
        f"Pool: {'yes' if d.has_pool else 'no'} · venues: {', '.join(d.venues) or '—'}",
        f"Liquidity: {fmt_usd(d.liquidity_usd)} · MCap: {fmt_usd(d.market_cap_usd)}",
        f"Price: {fmt_usd(d.price_usd)} · 24h vol: {fmt_usd(d.volume24h_usd)}",
        f"LP status: {lock}",
    ]
    if d.liq_to_mcap_pct is not None:
        lines.append(f"Liq/MCap: {d.liq_to_mcap_pct}%")
    lines += [f"• <i>{_esc(n)}</i>" for n in d.notes[:3]]
    return "\n".join(lines)
