"""Feature 3 — top-wallet holdings aggregation + whale flagging + self-exclusion."""

import pytest

from hypha.analysis.portfolios import analyze_portfolios
from hypha.models import Holder

SELF_RAW = "0:self"


def _bag(symbol, addr, usd, decimals=9, verified=False):
    # price fixed at 1.0 USD so balance(smallest units)/10^9 == usd
    return {
        "balance": str(int(usd) * 10 ** decimals),
        "price": {"prices": {"USD": 1.0}},
        "jetton": {
            "address": addr, "symbol": symbol, "decimals": decimals,
            "name": symbol, "verification": "whitelist" if verified else "none",
        },
    }


class FakeTonAPI:
    def __init__(self, by_owner: dict[str, list[dict]]):
        self.by_owner = by_owner

    async def account_jettons(self, owner: str) -> list[dict]:
        return self.by_owner.get(owner, [])


@pytest.fixture
def portfolio_data():
    by_owner = {
        "A": [_bag("SELF", SELF_RAW, 999), _bag("DOGS", "0:dogs", 30_000, verified=True), _bag("STON", "0:ston", 5_000)],
        "B": [_bag("SELF", SELF_RAW, 500), _bag("DOGS", "0:dogs", 20_000, verified=True), _bag("USDT", "0:usdt", 1_000)],
        "C": [_bag("DOGS", "0:dogs", 2_000, verified=True), _bag("CAT", "0:cat", 50_000)],
    }
    holders = [Holder(owner=o, balance=1) for o in ("A", "B", "C")]
    return by_owner, holders


async def test_shared_bags_and_whale_counts(portfolio_data):
    by_owner, holders = portfolio_data
    pf = await analyze_portfolios(
        SELF_RAW, "SELF", holders, FakeTonAPI(by_owner),
        max_wallets=10, whale_usd=10_000, min_shared=2, top_shared=8,
    )
    assert pf.scanned == 3
    # only DOGS is held by >= 2 wallets (SELF is excluded)
    assert [t.symbol for t in pf.shared_tokens] == ["DOGS"]
    dogs = pf.shared_tokens[0]
    assert dogs.held_by == 3
    assert dogs.whales == 2                  # A ($30k) and B ($20k); C ($2k) is not a whale
    assert dogs.total_usd == 52_000
    assert dogs.verified is True


async def test_self_token_excluded_and_wallets_ranked(portfolio_data):
    by_owner, holders = portfolio_data
    pf = await analyze_portfolios(
        SELF_RAW, "SELF", holders, FakeTonAPI(by_owner),
        max_wallets=10, whale_usd=10_000, min_shared=2, top_shared=8,
    )
    # SELF must never appear in shared bags or any wallet's bags
    assert all(t.symbol != "SELF" for t in pf.shared_tokens)
    assert all(b["symbol"] != "SELF" for w in pf.wallets for b in w.top_bags)
    # ranked by portfolio USD: C (52k) > A (35k) > B (21k)
    assert [w.owner for w in pf.wallets] == ["C", "A", "B"]
    assert pf.wallets[0].portfolio_usd == 52_000
    assert pf.wallets[0].top_bags[0]["symbol"] == "CAT"
    assert pf.wallets[0].top_bags[0]["whale"] is True


async def test_dust_airdrops_filtered_from_shared_bags():
    # DUST is held by 2 wallets but worth ~nothing and no whale -> must be dropped.
    # (regression: forces evaluation of the `total_usd >= dust_usd` branch.)
    by_owner = {
        "A": [_bag("DUST", "0:dust", 10), _bag("DOGS", "0:dogs", 30_000)],
        "B": [_bag("DUST", "0:dust", 10), _bag("DOGS", "0:dogs", 20_000)],
    }
    holders = [Holder(owner="A", balance=1), Holder(owner="B", balance=1)]
    pf = await analyze_portfolios(
        SELF_RAW, "SELF", holders, FakeTonAPI(by_owner),
        max_wallets=10, whale_usd=10_000, min_shared=2, top_shared=8, dust_usd=1_000,
    )
    assert [t.symbol for t in pf.shared_tokens] == ["DOGS"]   # DUST filtered out


async def test_excluded_holders_are_skipped():
    holders = [Holder(owner="P", balance=1, is_excluded=True)]
    pf = await analyze_portfolios(
        SELF_RAW, "SELF", holders, FakeTonAPI({}),
        max_wallets=10, whale_usd=10_000, min_shared=2, top_shared=8,
    )
    assert pf.scanned == 0
    assert pf.shared_tokens == []
