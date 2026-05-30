"""Token-centric discovery — picking the memecoin side of a pool and dropping non-targets."""

from hypha.analysis.discovery import dedupe_pools, is_quote_asset, normalize_pools


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


def test_dedupe_and_volume_sort_and_cap():
    pools = normalize_pools([
        _pool("EQp1", "AAA / TON", "EQa", "EQton", vol="100"),
        _pool("EQp2", "BBB / TON", "EQb", "EQton", vol="900"),
        _pool("EQp1", "AAA / TON", "EQa", "EQton", vol="100"),   # duplicate pool address
    ], "trending")
    capped = dedupe_pools(pools, limit=10)
    assert [p.pool_address for p in capped] == ["EQp2", "EQp1"]   # higher volume first, deduped
    assert len(dedupe_pools(pools, limit=1)) == 1
