"""The Hypha Score 🍄 — five weighted pillars, clamped by poison flags. See SPEC.md §5.

Pillars whose inputs are missing are dropped and the remaining weights renormalized; missing
data lowers `confidence` rather than silently scoring 0 (except where a 0 is meaningful, e.g.
no liquidity). Every breakpoint comes from config.ScoreConfig so we can calibrate live.
"""

from __future__ import annotations

import math

from ..config import get_settings
from ..models import (
    BundleReport,
    DexReport,
    HolderReport,
    HyphaScore,
    LaunchpadReport,
    LaunchStatus,
    PillarScore,
    TokenInfo,
)


def _clamp(x: float, lo: float = 0.0, hi: float = 100.0) -> float:
    return max(lo, min(hi, x))


def _decreasing(value: float, good: float, bad: float) -> float:
    """100 when value<=good, 0 when value>=bad, linear between (lower is better)."""
    if value <= good:
        return 100.0
    if value >= bad:
        return 0.0
    return 100.0 * (bad - value) / (bad - good)


def _log_score(value: float, full: float) -> float:
    if value <= 0:
        return 0.0
    return _clamp(100.0 * math.log10(value + 1) / math.log10(full))


# ── pillars ───────────────────────────────────────────────────────────────────
def _distribution(h: HolderReport, c) -> float:
    top10 = _decreasing(h.top10_pct, c.top10_good_pct, c.top10_bad_pct)
    holders = _log_score(h.holders_count, c.holders_full)
    gini = _decreasing(h.gini, c.gini_good, c.gini_bad)
    return 0.50 * top10 + 0.30 * holders + 0.20 * gini


def _bundling(b: BundleReport, c) -> float:
    base = _decreasing(b.bundled_pct, c.bundle_good_pct, c.bundle_bad_pct)
    base -= c.bundle_dev_penalty if b.dev_in_cluster else 0
    base -= c.bundle_bigcluster_penalty if b.largest_cluster_pct > c.bundle_bigcluster_pct else 0
    return _clamp(base)


def _liquidity(d: DexReport, c) -> float:
    lock = c.lock_scores.get(d.lp_status.value, 0.0)
    depth = _log_score(d.liquidity_usd, c.liq_depth_full_usd)
    if d.liq_to_mcap_pct is not None:
        ratio = _decreasing(-d.liq_to_mcap_pct, -c.liq_ratio_good_pct, -c.liq_ratio_bad_pct)
        return 0.45 * lock + 0.40 * depth + 0.15 * ratio
    # ratio unknown -> reweight lock/depth
    return 0.53 * lock + 0.47 * depth


def _dev_authority(info: TokenInfo, h: HolderReport, c) -> float:
    dev = _decreasing(h.dev_pct, c.dev_good_pct, c.dev_bad_pct)
    auth = 100.0
    if info.mintable:
        auth -= c.mintable_penalty
    if info.admin_address:
        auth -= c.admin_not_renounced_penalty
    return 0.60 * dev + 0.40 * _clamp(auth)


def _launch(lp: LaunchpadReport, d: DexReport | None, c) -> float:
    if lp.status == LaunchStatus.ON_CURVE:
        base = c.launch_on_curve_base + 0.20 * (lp.curve_progress_pct or 0)
    elif lp.status == LaunchStatus.GRADUATED:
        base = c.launch_graduated_base
    elif lp.status == LaunchStatus.LISTED:
        base = c.launch_listed_base
    else:
        base = c.launch_unknown_base
    if lp.age_days and lp.age_days > c.launch_age_days:
        base += c.launch_age_bonus
    if lp.is_known:
        base += c.launch_known_bonus
    if d is not None and not d.has_pool and lp.status != LaunchStatus.ON_CURVE:
        base -= c.launch_no_pool_penalty
    return _clamp(base)


# ── confidence ─────────────────────────────────────────────────────────────────
def _confidence(n_present: int, bundle: BundleReport | None) -> str:
    level = "high" if n_present >= 4 else "medium" if n_present >= 2 else "limited"
    if bundle is None or bundle.confidence in ("unavailable", "limited"):
        level = "medium" if level == "high" else level
    return level


# ── orchestration ───────────────────────────────────────────────────────────────
def compute_score(
    info: TokenInfo,
    holders: HolderReport | None,
    dex: DexReport | None,
    launchpad: LaunchpadReport | None,
    bundle: BundleReport | None,
) -> HyphaScore:
    c = get_settings().score
    w = c.weights
    pillars: list[PillarScore] = []

    def add(key, label, emoji, weight, value):
        pillars.append(PillarScore(
            key=key, label=label, emoji=emoji, weight=weight,
            score=round(value, 1) if value is not None else None,
        ))

    add("distribution", "Distribution", "🍄", w.distribution,
        _distribution(holders, c) if holders else None)

    bundle_ok = bundle is not None and bundle.confidence != "unavailable"
    add("bundling", "Bundling", "🕸️", w.bundling,
        _bundling(bundle, c) if bundle_ok else None)

    add("liquidity", "Liquidity", "💧", w.liquidity,
        _liquidity(dex, c) if dex is not None else None)

    add("dev_authority", "Dev & Authority", "🔑", w.dev_authority,
        _dev_authority(info, holders, c) if holders else None)

    add("launch_config", "Launch & Config", "🌱", w.launch_config,
        _launch(launchpad, dex, c) if launchpad else None)

    present = [p for p in pillars if p.score is not None]
    if present:
        total_w = sum(p.weight for p in present)
        raw = sum(p.score * p.weight for p in present) / total_w
    else:
        raw = 0.0

    # ── poison flags (hard caps) ──
    caps: list[float] = []
    flags: list[str] = []
    if dex is not None and (not dex.has_pool or dex.liquidity_usd < c.poison_min_liq_usd):
        caps.append(c.cap_no_liquidity)
        flags.append("No sellable liquidity (honeypot risk)")
    if dex is not None and dex.lp_status.value == "unlocked" and holders and holders.dev_pct > c.poison_dev_pct:
        caps.append(c.cap_unlocked_high_dev)
        flags.append("LP unlocked + high dev allocation")
    if info.mintable and holders and holders.top1_pct > c.poison_whale_pct:
        caps.append(c.cap_mintable_whale)
        flags.append("Mintable + single whale > 50%")
    if bundle_ok and bundle.bundled_pct > c.poison_bundle_pct:
        caps.append(c.cap_heavy_bundle)
        flags.append("Bundled supply > 60%")

    final = round(min([raw, *caps])) if caps else round(raw)

    tier, badge = "Toxic", "☠️"
    for lo, name, emo in c.tiers:
        if final >= lo:
            tier, badge = name, emo
            break

    return HyphaScore(
        score=int(final),
        raw=round(raw, 1),
        tier=tier,
        badge=badge,
        confidence=_confidence(len(present), bundle),
        pillars=pillars,
        poison_flags=flags,
    )
