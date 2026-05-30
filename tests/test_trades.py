"""Swap classification — Gecko pool trades + TonAPI events into normalized buy/sell Trades."""

from hypha.analysis.trades import parse_gecko_trades, parse_tonapi_events
from hypha.models import HotPool, TradeSide
from hypha.utils import to_raw

TOKEN = "EQToken_aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
TON = "EQTon__bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"
POOL = HotPool(pool_address="EQpool", token_address=TOKEN, token_symbol="SHROOM",
               quote_symbol="TON", token_is_base=True, venue="dedust")


def _gtrade(kind, vol, *, frm, to, buyer="EQbuyer_cccccccccccccccccccccccccccccccccccccc"):
    return {"attributes": {
        "kind": kind, "volume_in_usd": str(vol),
        "from_token_address": frm, "to_token_address": to,
        "from_token_amount": "1000", "to_token_amount": "2000",
        "price_from_in_usd": "0.5", "price_to_in_usd": "0.25",
        "tx_from_address": buyer, "tx_hash": f"hash_{kind}_{vol}",
        "block_timestamp": "2026-05-30T12:00:00Z",
    }}


def test_gecko_buy_classified_by_token_direction():
    # received the memecoin (to == token) -> BUY, regardless of `kind`
    trades = parse_gecko_trades([_gtrade("buy", 4200, frm=TON, to=TOKEN)], POOL, buy_min=1000, sell_min=10000)
    assert len(trades) == 1
    t = trades[0]
    assert t.side == TradeSide.BUY
    assert t.usd == 4200.0
    assert t.token_symbol == "SHROOM"
    assert t.trader == to_raw("EQbuyer_cccccccccccccccccccccccccccccccccccccc")


def test_gecko_sell_classified_and_thresholded():
    # a $5k sell is below the $10k sell floor -> dropped; a $12k sell passes
    small = parse_gecko_trades([_gtrade("sell", 5000, frm=TOKEN, to=TON)], POOL, buy_min=1000, sell_min=10000)
    assert small == []
    big = parse_gecko_trades([_gtrade("sell", 12000, frm=TOKEN, to=TON)], POOL, buy_min=1000, sell_min=10000)
    assert len(big) == 1 and big[0].side == TradeSide.SELL


def test_gecko_buy_below_floor_dropped():
    trades = parse_gecko_trades([_gtrade("buy", 500, frm=TON, to=TOKEN)], POOL, buy_min=1000, sell_min=10000)
    assert trades == []


def test_gecko_falls_back_to_kind_when_addresses_missing():
    raw = {"attributes": {"kind": "buy", "volume_in_usd": "2000",
                          "from_token_amount": "1", "to_token_amount": "2",
                          "tx_from_address": "EQx", "tx_hash": "h", "block_timestamp": "2026-05-30T12:00:00Z"}}
    trades = parse_gecko_trades([raw], POOL, buy_min=1000, sell_min=10000)
    assert len(trades) == 1 and trades[0].side == TradeSide.BUY   # token_is_base + kind=buy


def _swap(*, ton_in=0, ton_out=0, jin=None, jout=None):
    sw = {"dex": "stonfi", "amount_in": "1000000000", "amount_out": "5000000000"}
    if ton_in:
        sw["ton_in"] = ton_in
    if ton_out:
        sw["ton_out"] = ton_out
    if jin:
        sw["jetton_master_in"] = jin
    if jout:
        sw["jetton_master_out"] = jout
    return {"timestamp": 1717070400, "event_id": "ev1",
            "actions": [{"type": "JettonSwap", "status": "ok", "JettonSwap": sw}]}


def test_tonapi_buy_with_ton_in():
    # paid TON, received SHROOM -> BUY of SHROOM
    jout = {"address": TOKEN, "symbol": "SHROOM", "decimals": 9}
    trades = parse_tonapi_events([_swap(ton_in=1_000_000_000, jout=jout)], "0:wallet")
    assert len(trades) == 1
    t = trades[0]
    assert t.side == TradeSide.BUY and t.token_symbol == "SHROOM"
    assert t.token_amount == 5.0               # amount_out 5e9 / 1e9
    assert t.usd == 0.0 and t.source == "tonapi"   # priced later


def test_tonapi_sell_with_ton_out():
    jin = {"address": TOKEN, "symbol": "SHROOM", "decimals": 9}
    trades = parse_tonapi_events([_swap(ton_out=2_000_000_000, jin=jin)], "0:wallet")
    assert len(trades) == 1 and trades[0].side == TradeSide.SELL


def test_tonapi_skips_failed_and_jetton_to_jetton():
    jin = {"address": "EQa", "symbol": "AAA", "decimals": 9}
    jout = {"address": "EQb", "symbol": "BBB", "decimals": 9}
    # pure jetton<->jetton (no TON, no stable) is ambiguous -> skipped
    assert parse_tonapi_events([_swap(jin=jin, jout=jout)], "0:wallet") == []
    # failed swaps are ignored
    failed = {"timestamp": 1, "event_id": "e",
              "actions": [{"type": "JettonSwap", "status": "failed",
                           "JettonSwap": {"ton_in": 1, "jetton_master_out": jout}}]}
    assert parse_tonapi_events([failed], "0:wallet") == []
