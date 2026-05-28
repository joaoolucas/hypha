"""Feature 2 — Bundling detection (Phase 3).

Plan: pull the launch-window transaction graph (TonAPI events/traces), build a funding graph
(who funded whom, same-block launch buys, shared consolidation sinks), then cluster via
networkx connected-components / community detection. Excludes labeled DEX/locker addresses.

Under API-only depth this is window-based and reported at `limited` confidence; the full
graph needs the self-hosted indexer (SPEC.md Tier B). Until implemented, the score engine
treats this pillar as `unavailable` so it neither rewards nor penalizes blindly.
"""

from __future__ import annotations

from ..connectors.tonapi import TonAPI
from ..models import BundleReport, TokenInfo


async def analyze_bundling(info: TokenInfo, tonapi: TonAPI | None = None) -> BundleReport:
    # TODO(phase-3): fetch jetton transfer/launch events, build networkx funding graph,
    # detect connected components, compute bundled_pct / largest_cluster_pct / dev_in_cluster.
    return BundleReport(
        confidence="unavailable",
        notes=["bundling analysis ships in Phase 3 (trace-graph clustering)"],
    )
