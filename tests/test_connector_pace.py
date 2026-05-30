"""Connector request pacing — keeps bursty fan-out under a source's rate limit."""

import time

from hypha.connectors import base
from hypha.connectors.base import BaseConnector


async def test_pace_serializes_rapid_calls():
    base._pace_locks.clear()
    base._pace_last.clear()
    c = BaseConnector("https://x", min_interval=0.05)
    c.name = "pacetest"
    start = time.monotonic()
    await c._pace()      # first call: no wait
    await c._pace()      # +0.05
    await c._pace()      # +0.05
    elapsed = time.monotonic() - start
    assert elapsed >= 0.09          # two intervals enforced between three calls
    await c.aclose()


async def test_pace_noop_when_unthrottled():
    c = BaseConnector("https://y")  # min_interval defaults to 0
    start = time.monotonic()
    await c._pace()
    await c._pace()
    assert time.monotonic() - start < 0.02
    await c.aclose()
