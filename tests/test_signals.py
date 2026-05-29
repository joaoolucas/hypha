"""Holder-growth time-series diffing + dev-sold detection."""

from hypha.analysis.service import _dev_sold
from hypha.snapshots import _delta

DEV = "0:dev"


def test_delta_picks_nearest_in_window():
    now = 1_000_000.0
    snaps = [[now - 3600, 100], [now - 86400, 50], [now - 100, 199]]
    assert _delta(snaps, now, 200, target=3600, lo=1800, hi=7200) == 100     # +100 in ~1h
    assert _delta(snaps, now, 200, target=86400, lo=43200, hi=129600) == 150  # +150 in ~24h


def test_delta_none_when_no_snapshot_in_window():
    now = 1_000_000.0
    assert _delta([[now - 100, 199]], now, 200, target=3600, lo=1800, hi=7200) is None


def _transfer(sender, recipient):
    return {"actions": [{"type": "JettonTransfer",
                         "JettonTransfer": {"sender": {"address": sender}, "recipient": {"address": recipient}}}]}


def test_dev_sold_detects_outgoing():
    assert _dev_sold([_transfer(DEV, "0:pool")], DEV) is True


def test_dev_holding_when_only_incoming():
    assert _dev_sold([_transfer("0:someone", DEV)], DEV) is False


def test_dev_sold_unknown_without_history():
    assert _dev_sold([], DEV) is None
