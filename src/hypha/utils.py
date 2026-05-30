"""Small shared helpers — TON address validation and number formatting."""

from __future__ import annotations

import base64
import re

# user-friendly: 48 base64url chars (EQ/UQ/kQ/0Q…); raw: workchain:hex64
_FRIENDLY = re.compile(r"^[EUk0][QcfF][A-Za-z0-9_-]{46}$")
_RAW = re.compile(r"^-?\d+:[0-9a-fA-F]{64}$")


def _crc16(data: bytes) -> bytes:
    """CRC16/XMODEM, as used by TON user-friendly addresses."""
    crc = 0
    for b in data:
        crc ^= b << 8
        for _ in range(8):
            crc = ((crc << 1) ^ 0x1021) if crc & 0x8000 else (crc << 1)
            crc &= 0xFFFF
    return crc.to_bytes(2, "big")


def to_friendly(addr: str, *, bounceable: bool = False) -> str:
    """Convert a raw `workchain:hex` address to the user-friendly base64url form (UQ… for
    non-bounceable, EQ… for bounceable). Returns the input unchanged if already friendly."""
    if not addr or ":" not in addr:
        return addr
    try:
        wc_str, hex_part = addr.split(":")
        hash_bytes = bytes.fromhex(hex_part)
    except ValueError:
        return addr
    tag = 0x11 if bounceable else 0x51
    payload = bytes([tag, int(wc_str) & 0xFF]) + hash_bytes
    return base64.urlsafe_b64encode(payload + _crc16(payload)).decode()


def to_raw(addr: str) -> str:
    """Convert a user-friendly (EQ…/UQ…) address to its raw `workchain:hex` form. Returns the
    input unchanged if already raw or undecodable. No network call — the inverse of to_friendly,
    so the same wallet keys identically whether it arrives from Gecko (EQ…) or TonAPI (0:hex)."""
    if not addr or ":" in addr:
        return addr
    try:
        payload = base64.urlsafe_b64decode(addr)
    except (ValueError, TypeError):
        return addr
    if len(payload) != 36:
        return addr
    wc = payload[1] - 256 if payload[1] > 127 else payload[1]
    return f"{wc}:{payload[2:34].hex()}"


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
