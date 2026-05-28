"""Validate the Hypha Score engine against the SPEC §5.6 worked example + poison flags."""

from hypha.analysis.score import compute_score
from hypha.models import (
    BundleReport,
    DexReport,
    HolderReport,
    LaunchpadReport,
    LaunchStatus,
    LockStatus,
    TokenInfo,
)


def _worked_example_inputs():
    info = TokenInfo(address="EQ_test", symbol="SHROOM", mintable=False, admin_address=None)
    holders = HolderReport(
        holders_count=1800, counted_holders=1800,
        top10_pct=42, top20_pct=55, top1_pct=9, dev_pct=4, gini=0.88,
    )
    dex = DexReport(
        has_pool=True, venues=["dedust"], liquidity_usd=18000,
        market_cap_usd=300000, lp_status=LockStatus.BURNED, liq_to_mcap_pct=6,
    )
    lp = LaunchpadReport(
        launchpad="GasPump", is_known=True, status=LaunchStatus.GRADUATED,
        graduation_dex="dedust", age_days=45,
    )
    bundle = BundleReport(bundled_pct=12, largest_cluster_pct=15, dev_in_cluster=True, confidence="limited")
    return info, holders, dex, lp, bundle


def test_worked_example():
    info, holders, dex, lp, bundle = _worked_example_inputs()
    sc = compute_score(info, holders, dex, lp, bundle)
    assert sc.score == 74
    assert sc.tier == "Healthy Cap"
    assert sc.confidence == "medium"   # bundling confidence "limited" downgrades from high
    assert sc.poison_flags == []


def test_no_liquidity_poison_caps_score():
    info, holders, _, lp, bundle = _worked_example_inputs()
    dead_dex = DexReport(has_pool=False, liquidity_usd=0, lp_status=LockStatus.NONE)
    sc = compute_score(info, holders, dead_dex, lp, bundle)
    assert sc.score <= 15
    assert any("honeypot" in f.lower() for f in sc.poison_flags)


def test_missing_pillars_are_skipped_not_zeroed():
    info = TokenInfo(address="EQ_test", symbol="X")
    holders = HolderReport(holders_count=5000, top10_pct=20, top1_pct=5, dev_pct=1, gini=0.7)
    # only distribution + dev/authority available
    sc = compute_score(info, holders, dex=None, launchpad=None, bundle=None)
    present = [p for p in sc.pillars if p.score is not None]
    assert {p.key for p in present} == {"distribution", "dev_authority"}
    assert sc.score > 0
