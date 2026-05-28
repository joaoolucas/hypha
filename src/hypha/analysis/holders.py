"""Feature 1 — Holder analysis.

Computes Top10/Top20 concentration, Gini, dev allocation and holder spread against the
*circulating* supply (i.e. excluding DEX pools, burn and locker addresses, which hold supply
backing liquidity rather than being real whales). See SPEC.md Feature 1 / §8.
"""

from __future__ import annotations

import numpy as np

from ..models import Holder, HolderReport, TokenInfo
from ..registry import BURN_ADDRESSES, is_excluded_label


def _gini(balances: list[int]) -> float:
    """Gini coefficient of a balance distribution (0 = equal, ~1 = one holder)."""
    if len(balances) < 2:
        return 0.0
    x = np.sort(np.array(balances, dtype=float))
    total = x.sum()
    if total <= 0:
        return 0.0
    n = len(x)
    idx = np.arange(1, n + 1)
    return float((np.sum((2 * idx - n - 1) * x)) / (n * total))


def _mark_exclusions(holders: list[Holder]) -> None:
    for h in holders:
        if h.owner in BURN_ADDRESSES or h.wallet in BURN_ADDRESSES:
            h.is_excluded = True
            h.label = h.label or "burn"
        elif is_excluded_label(h.label):
            h.is_excluded = True


def analyze_holders(info: TokenInfo, holders: list[Holder]) -> HolderReport:
    _mark_exclusions(holders)

    excluded = [h for h in holders if h.is_excluded]
    real = sorted((h for h in holders if not h.is_excluded), key=lambda h: h.balance, reverse=True)

    excluded_balance = sum(h.balance for h in excluded)
    circulating = max(info.total_supply - excluded_balance, 1)

    def share(bals: list[int]) -> float:
        return round(sum(bals) / circulating * 100, 2)

    top10 = share([h.balance for h in real[:10]])
    top20 = share([h.balance for h in real[:20]])
    top1 = share([real[0].balance]) if real else 0.0

    dev_pct = 0.0
    if info.admin_address:
        dev_bal = sum(h.balance for h in real if h.owner == info.admin_address)
        dev_pct = round(dev_bal / circulating * 100, 2)

    gini = round(_gini([h.balance for h in real]), 3)

    notes: list[str] = []
    if excluded:
        notes.append(f"{len(excluded)} pool/burn/locker address(es) excluded from concentration")
    if info.holders_count > len(holders):
        notes.append(f"holder list capped at {len(holders)} of {info.holders_count} (API limit)")
    if dev_pct == 0.0 and not info.admin_address:
        notes.append("mint authority renounced — no admin/dev wallet to attribute")

    return HolderReport(
        holders_count=info.holders_count or len(holders),
        counted_holders=len(real),
        top10_pct=top10,
        top20_pct=top20,
        top1_pct=top1,
        dev_pct=dev_pct,
        gini=gini,
        excluded_pct=round(excluded_balance / max(info.total_supply, 1) * 100, 2),
        top_holders=real[:10],
        notes=notes,
    )
