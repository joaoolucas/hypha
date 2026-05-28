"""Cover GeckoTerminal-shaped venue/liquidity extraction + LP-status logic (dex.py)."""

from hypha.analysis.dex import analyze_dex, extract_venues, pool_liquidity
from hypha.models import LaunchpadReport, LaunchStatus, LockStatus, TokenInfo

GECKO_POOLS = [
    {"attributes": {"name": "NOT / TON", "reserve_in_usd": "200000.5"},
     "relationships": {"dex": {"data": {"id": "stonfi", "type": "dex"}}}},
    {"attributes": {"name": "NOT / USDT", "reserve_in_usd": "50000"},
     "relationships": {"dex": {"data": {"id": "dedust", "type": "dex"}}}},
    {"attributes": {"name": "NOT / TON v2", "reserve_in_usd": None},
     "relationships": {"dex": {"data": {"id": "ston-fi-v2", "type": "dex"}}}},
]


def test_extract_venues_dedupes_and_normalizes():
    assert extract_venues(GECKO_POOLS) == ["stonfi", "dedust"]


def test_pool_liquidity_sums_and_ignores_nulls():
    assert pool_liquidity(GECKO_POOLS) == 250000.5


def test_analyze_dex_prefers_market_liquidity():
    info = TokenInfo(address="EQ_x", symbol="NOT")
    market = {"liquidity_usd": 181403.0, "market_cap_usd": 43_800_000.0, "price_usd": 0.0004}
    d = analyze_dex(info, market, GECKO_POOLS, launchpad=None)
    assert d.has_pool
    assert d.venues == ["stonfi", "dedust"]
    assert d.liquidity_usd == 181403.0
    assert d.lp_status == LockStatus.UNLOCKED  # not verified -> conservative


def test_analyze_dex_burns_lp_on_dedust_graduation():
    info = TokenInfo(address="EQ_x", symbol="GASX")
    lp = LaunchpadReport(launchpad="GasPump", status=LaunchStatus.GRADUATED, graduation_dex="dedust")
    d = analyze_dex(info, {"liquidity_usd": 20000, "market_cap_usd": 100000}, GECKO_POOLS, launchpad=lp)
    assert d.lp_status == LockStatus.BURNED
