"""Feature 6 — Launchpad & bonding-curve detection.

MVP heuristic: match the jetton's symbol/name against known launchpad signatures, then infer
status from DEX presence. Precise curve progress needs the launchpad contract get-methods
(GasPump via @gaspump/sdk) — wired as a TODO; until then progress is reported as unknown.
See SPEC.md Feature 6.
"""

from __future__ import annotations

from ..models import LaunchpadReport, LaunchStatus, TokenInfo
from ..registry import LAUNCHPAD_SIGNATURES


def _match_launchpad(info: TokenInfo) -> tuple[str, dict] | None:
    sym = (info.symbol or "").lower()
    name = (info.name or "").lower()
    for key, sig in LAUNCHPAD_SIGNATURES.items():
        if any(sym.startswith(p) for p in sig.get("symbol_prefixes", ())):
            return key, sig
        if any(k in name or k in sym for k in sig.get("name_keywords", ())):
            return key, sig
    return None


def detect_launchpad(info: TokenInfo, has_pool: bool, liquidity_usd: float) -> LaunchpadReport:
    match = _match_launchpad(info)
    notes: list[str] = []

    if match:
        key, sig = match
        graduated = has_pool and liquidity_usd > 0
        status = LaunchStatus.GRADUATED if graduated else LaunchStatus.ON_CURVE
        if status == LaunchStatus.ON_CURVE:
            notes.append("still on bonding curve (no graduated DEX pool detected)")
        notes.append("curve progress unavailable (needs launchpad contract read — TODO)")
        return LaunchpadReport(
            launchpad=sig["label"],
            is_known=sig.get("reputable", False),
            status=status,
            graduation_dex=sig.get("graduation_dex"),
            curve_progress_pct=None,
            notes=notes,
        )

    # No known launchpad signature.
    if has_pool:
        return LaunchpadReport(status=LaunchStatus.LISTED, notes=["no known launchpad — DEX-listed"])
    return LaunchpadReport(status=LaunchStatus.UNKNOWN, notes=["launchpad/status undetermined"])
