"""Holder-growth snapshot diffing + dev-sold detection."""

import time

from hypha.analysis.service import _dev_sold
from hypha.cache import cache_set
from hypha.snapshots import record_and_growth

DEV = "0:dev"


async def test_growth_diffs_against_prior_snapshot():
    now = time.time()
    await cache_set("snap:tokA", [[now - 600, 90]], 99999)   # 90 holders, 10 min ago
    delta, secs = await record_and_growth("tokA", 102)
    assert delta == 12
    assert 590 <= secs <= 610


async def test_growth_none_until_a_prior_snapshot_exists():
    delta, secs = await record_and_growth("tokFresh", 100)   # first ever sighting
    assert delta is None and secs is None


async def test_growth_ignores_too_recent_snapshots():
    now = time.time()
    await cache_set("snap:tokB", [[now - 5, 100]], 99999)    # younger than _MIN_GAP
    delta, secs = await record_and_growth("tokB", 130)
    assert delta is None and secs is None


def _transfer(sender, recipient):
    return {"actions": [{"type": "JettonTransfer",
                         "JettonTransfer": {"sender": {"address": sender}, "recipient": {"address": recipient}}}]}


def test_dev_sold_detects_outgoing():
    assert _dev_sold([_transfer(DEV, "0:pool")], DEV) is True


def test_dev_holding_when_only_incoming():
    assert _dev_sold([_transfer("0:someone", DEV)], DEV) is False


def test_dev_sold_unknown_without_history():
    assert _dev_sold([], DEV) is None
