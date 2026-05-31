"""Token-centric discovery — picking the memecoin side of a pool and dropping non-targets."""

from hypha.analysis.discovery import (
    dedupe_pools, hot_pools, is_lp_or_staked, is_quote_asset, normalize_dexscreener, normalize_pools,
)


def test_is_lp_or_staked():
    assert is_lp_or_staked("STON-LP") and is_lp_or_staked("LP")
    assert is_lp_or_staked("STAKED") and is_lp_or_staked("stTON Staked")
    assert is_lp_or_staked("X", "STON.fi Liquidity Provider")
    assert is_lp_or_staked("X", "DeDust Pool: TOKEN/TON")
    assert not is_lp_or_staked("ALPHA")   # 'lp' substring, not a token
    assert not is_lp_or_staked("UTYA") and not is_lp_or_staked("STON")


def _pool(addr, name, base_id, quote_id, dex="stonfi", reserve="50000", vol="100000"):
    return {
        "id": f"ton_{addr}",
        "attributes": {"address": addr, "name": name, "reserve_in_usd": reserve,
                       "volume_usd": {"h24": vol}},
        "relationships": {
            "base_token": {"data": {"id": f"ton_{base_id}"}},
            "quote_token": {"data": {"id": f"ton_{quote_id}"}},
            "dex": {"data": {"id": dex}},
        },
    }


def test_is_quote_asset():
    assert is_quote_asset("TON") and is_quote_asset("USDT") and is_quote_asset("usdt")
    assert not is_quote_asset("SHROOM")


def test_memecoin_is_base_side():
    pools = normalize_pools([_pool("EQp1", "SHROOM / TON", "EQshroom", "EQton")], "trending")
    assert len(pools) == 1
    p = pools[0]
    assert p.token_symbol == "SHROOM"
    assert p.token_address == "EQshroom"
    assert p.quote_symbol == "TON"
    assert p.token_is_base is True
    assert p.venue == "stonfi"
    assert p.reason == "trending"


def test_memecoin_is_quote_side_when_base_is_ton():
    pools = normalize_pools([_pool("EQp2", "TON / CAT", "EQton", "EQcat")], "new")
    assert len(pools) == 1
    p = pools[0]
    assert p.token_symbol == "CAT" and p.token_address == "EQcat"
    assert p.token_is_base is False


def test_pure_quote_pair_dropped():
    # TON/USDT has no memecoin to alert on
    assert normalize_pools([_pool("EQp3", "TON / USDT", "EQton", "EQusdt")], "trending") == []


def test_dedust_fee_suffix_stripped():
    # DeDust appends the fee tier to symbols: "USD₮ / TON 0.1%" must still read as quote/quote
    # (both money) and be dropped — and a memecoin's quote symbol comes out clean.
    assert normalize_pools([_pool("EQp4", "USD₮ / TON 0.1%", "EQusdt", "EQton")], "trending") == []
    pools = normalize_pools([_pool("EQp5", "DUROVIUS / TON 0.25%", "EQduro", "EQton")], "trending")
    assert len(pools) == 1
    assert pools[0].token_symbol == "DUROVIUS"
    assert pools[0].quote_symbol == "TON"          # fee suffix stripped, not "TON 0.25%"


class _FakeGecko:
    def __init__(self, top=None, trending=None, new=None):
        self._top, self._trending, self._new = top or [], trending or [], new or []

    async def top_pools(self, page=1):
        return self._top if page == 1 else []

    async def trending_pools(self, page=1):
        return self._trending if page == 1 else []

    async def new_pools(self, page=1):
        return self._new if page == 1 else []


def _ds_pair(symbol, pair, dex="uranus", base_addr="EQbase", quote_sym="TON", vol=100):
    return {
        "chainId": "ton", "dexId": dex, "pairAddress": pair,
        "baseToken": {"address": base_addr, "symbol": symbol},
        "quoteToken": {"address": "EQton", "symbol": quote_sym},
        "volume": {"h24": vol}, "liquidity": {"usd": 5000},
    }


class _FakeDex:
    def __init__(self, pairs):
        self._pairs = pairs

    async def search_ton(self, query):
        return self._pairs


def test_normalize_dexscreener_picks_memecoin_and_venue():
    pools = normalize_dexscreener([_ds_pair("PEPEGRINCH", "EQpair1")])
    assert len(pools) == 1
    p = pools[0]
    assert p.token_symbol == "PEPEGRINCH" and p.pool_address == "EQpair1"
    assert p.venue == "uranus" and p.quote_symbol == "TON" and p.token_is_base is True


def test_normalize_dexscreener_drops_quote_quote():
    assert normalize_dexscreener([_ds_pair("TON", "EQp", base_addr="EQton", quote_sym="USDT")]) == []


async def test_hot_pools_includes_dexscreener_launchpad(monkeypatch):
    from hypha.analysis import discovery
    from hypha.config import Settings
    # enable DexScreener for this test (it's off by default until Uranus detection lands)
    monkeypatch.setattr(discovery, "get_settings",
                        lambda: Settings(dexscreener_queries="uranus", hot_pools_max=10, new_pools_reserve=50))
    top = [_pool("EQbig", "BIG / TON", "EQb", "EQton", vol="9999999")]
    ds = _FakeDex([_ds_pair("PEPEGRINCH", "EQuranus1", vol=50)])
    pools = await hot_pools(_FakeGecko(top=top), limit=10, dexscreener=ds)
    addrs = {p.pool_address for p in pools}
    assert "EQuranus1" in addrs       # low-volume Uranus pair reserved, not crowded out
    assert "EQbig" in addrs


async def test_hot_pools_reserves_fresh_launches_over_volume():
    # a huge-volume established pool and a brand-new low-volume launch
    top = [_pool("EQbig", "BIG / TON", "EQb", "EQton", vol="9999999")]
    new = [_pool("EQfresh", "FRESH / TON", "EQf", "EQton", vol="5")]
    pools = await hot_pools(_FakeGecko(top=top, new=new), limit=10)
    addrs = {p.pool_address for p in pools}
    assert "EQfresh" in addrs       # low-volume launch is reserved, not crowded out
    assert "EQbig" in addrs


def test_dedupe_and_volume_sort_and_cap():
    pools = normalize_pools([
        _pool("EQp1", "AAA / TON", "EQa", "EQton", vol="100"),
        _pool("EQp2", "BBB / TON", "EQb", "EQton", vol="900"),
        _pool("EQp1", "AAA / TON", "EQa", "EQton", vol="100"),   # duplicate pool address
    ], "trending")
    capped = dedupe_pools(pools, limit=10)
    assert [p.pool_address for p in capped] == ["EQp2", "EQp1"]   # higher volume first, deduped
    assert len(dedupe_pools(pools, limit=1)) == 1
