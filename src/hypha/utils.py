"""Small shared helpers — TON address validation and number formatting."""

from __future__ import annotations

import re

# user-friendly: 48 base64url chars (EQ/UQ/kQ/0Q…); raw: workchain:hex64
_FRIENDLY = re.compile(r"^[EUk0][QcfF][A-Za-z0-9_-]{46}$")
_RAW = re.compile(r"^-?\d+:[0-9a-fA-F]{64}$")


def clean_address(text: str) -> str | None:
    """Extract/validate a TON address from arbitrary user text. Returns None if not found."""
    text = (text or "").strip()
    for tok in re.split(r"\s+", text):
        tok = tok.strip().rstrip(".,;")
        if _FRIENDLY.match(tok) or _RAW.match(tok):
            return tok
    return None


def is_ton_address(text: str) -> bool:
    return clean_address(text) is not None


def fmt_usd(v: float | None) -> str:
    if v is None:
        return "—"
    if v >= 1_000_000:
        return f"${v / 1_000_000:.2f}M"
    if v >= 1_000:
        return f"${v / 1_000:.1f}k"
    return f"${v:,.0f}"


_SUBSCRIPT = "₀₁₂₃₄₅₆₇₈₉"


def _subscript(n: int) -> str:
    return "".join(_SUBSCRIPT[int(d)] for d in str(n))


def fmt_price(p: float | None) -> str:
    """Compact USD price, with DexScreener-style subscript-zero notation for tiny values
    (e.g. 0.000142 -> $0.0₂142)."""
    if p is None:
        return "—"
    try:
        p = float(p)
    except (TypeError, ValueError):
        return "—"
    if p <= 0:
        return "$0"
    if p >= 1:
        return f"${p:,.2f}"
    if p >= 0.001:
        return "$" + f"{p:.6f}".rstrip("0").rstrip(".")
    decimals = f"{p:.18f}".split(".")[1]
    zeros = len(decimals) - len(decimals.lstrip("0"))
    sig = decimals[zeros:zeros + 4].rstrip("0") or "0"
    return f"$0.0{_subscript(zeros - 1)}{sig}"


def fmt_int(v: int | float | None) -> str:
    if v is None:
        return "—"
    v = int(v)
    if v >= 1_000_000:
        return f"{v / 1_000_000:.1f}M"
    if v >= 1_000:
        return f"{v / 1_000:.1f}k"
    return str(v)


def bar(pct: float | None, width: int = 10) -> str:
    """ASCII mycelium bar for a 0..100 value."""
    if pct is None:
        return "░" * width
    filled = max(0, min(width, round(pct / 100 * width)))
    return "▓" * filled + "░" * (width - filled)
