"""Tracker — dedup/watermark/promotion state, the posting-policy funnel, and alert rendering."""

import pytest

from hypha.bot.channel import render_alert
from hypha.config import Settings
from hypha.models import (
    DexReport, HyphaScore, TokenInfo, TokenReport, Trade, TraderContext, TradeSide,
)
from hypha.tracker import service, state


def _report(symbol="SHROOM", price=0.001, score=72):
    return TokenReport(
        token=TokenInfo(address="EQtok", symbol=symbol),
        dex=DexReport(has_pool=True, price_usd=price, market_cap_usd=1_000_000,
                      liquidity_usd=85_000, venues=["dedust"], price_change_24h=18.0),
        score=HyphaScore(score=score, tier="Healthy Cap", badge="🍄"),
    )


def _settings(**kw):
    base = dict(
        buy_alert_usd=1000, sell_alert_usd=10000, alerts_channel_id="@x",
        promote_min_buys=3, follow_enabled=True, followed_max=150,
        promote_window_secs=604_800, alert_dedup_ttl=86_400, whale_portfolio_usd=50_000,
    )
    base.update(kw)
    return Settings(**base)


def _trade(side=TradeSide.BUY, usd=4200.0, trader="0:w", token="EQtok1", tx="h", ts=100.0):
    return Trade(side=side, token_address=token, token_symbol="SHROOM", trader=trader,
                 usd=usd, tx_hash=tx, ts=ts)


# ── state ──────────────────────────────────────────────────────────────────────
async def test_is_new_op_dedups():
    tr = _trade(tx="dedup-1", trader="0:dd", token="EQdd")
    assert await state.is_new_op(tr, 600) is True
    assert await state.is_new_op(tr, 600) is False        # same op -> suppressed


async def test_watermark_skips_history_then_yields_fresh():
    pool = "EQwm"
    first = [_trade(ts=100, tx="a"), _trade(ts=200, tx="b")]
    assert await state.new_pool_trades(pool, first) == []   # first sight: set line, replay nothing
    nxt = [_trade(ts=200, tx="b"), _trade(ts=300, tx="c")]
    fresh = await state.new_pool_trades(pool, nxt)
    assert [t.ts for t in fresh] == [300]                   # only the genuinely newer trade


async def test_followed_add_remove():
    await state.add_followed("0:fol", reason="manual")
    assert await state.is_followed("0:fol") is True
    assert "0:fol" in await state.followed_list()
    assert await state.remove_followed("0:fol") is True
    assert await state.is_followed("0:fol") is False


async def test_record_big_buy_counts_in_window():
    w = "0:counter"
    assert await state.record_big_buy(w, 604_800) == 1
    assert await state.record_big_buy(w, 604_800) == 2
    assert await state.buy_count(w, 604_800) == 2


# ── posting-policy funnel ────────────────────────────────────────────────────────
@pytest.fixture
def captured(monkeypatch):
    posts = []

    async def fake_analyze(addr, **kw):
        return _report()

    async def fake_publish(publisher, channel, text, venue_emoji):
        posts.append(text)
        return True

    monkeypatch.setattr(service, "analyze_token", fake_analyze)
    monkeypatch.setattr(service, "publish_alert", fake_publish)
    return posts


def _patch_enrich(monkeypatch, **ctx_kw):
    async def fake_enrich(addr, tonapi, s):
        return TraderContext(address=addr, **ctx_kw)
    monkeypatch.setattr(service, "enrich_trader", fake_enrich)


async def test_big_buy_posts(captured, monkeypatch):
    _patch_enrich(monkeypatch, is_whale=True, portfolio_usd=180_000)
    tr = _trade(usd=4200, trader="0:b1", token="EQb1", tx="b1")
    assert await service.handle_trade(tr, None, None, _settings()) is True
    assert "WHALE BUY" in captured[0]


async def test_small_buy_not_posted(captured, monkeypatch):
    _patch_enrich(monkeypatch, is_whale=True)              # whale, but below the size floor
    tr = _trade(usd=500, trader="0:b2", token="EQb2", tx="b2")
    assert await service.handle_trade(tr, None, None, _settings()) is False
    assert captured == []


async def test_stablecoin_token_not_posted(captured, monkeypatch):
    _patch_enrich(monkeypatch, is_whale=True)              # whale, but the token bought is USDT
    tr = _trade(usd=5000, trader="0:st", token="EQusdt", tx="st")
    tr.token_symbol = "USDT"
    assert await service.handle_trade(tr, None, None, _settings()) is False
    assert captured == []


async def test_non_whale_big_buy_not_posted(captured, monkeypatch):
    # the reported bug: a big buy by a non-whale, non-followed wallet must NOT post
    _patch_enrich(monkeypatch)                              # not a whale, not followed
    tr = _trade(usd=5000, trader="0:nonwhale", token="EQnw", tx="nw")
    assert await service.handle_trade(tr, None, None, _settings()) is False
    assert captured == []


async def test_small_sell_dropped_big_sell_posted(captured, monkeypatch):
    _patch_enrich(monkeypatch, is_whale=True)              # whale seller
    small = _trade(side=TradeSide.SELL, usd=5000, trader="0:s1", token="EQs1", tx="s1")
    assert await service.handle_trade(small, None, None, _settings()) is False
    big = _trade(side=TradeSide.SELL, usd=12000, trader="0:s2", token="EQs2", tx="s2")
    assert await service.handle_trade(big, None, None, _settings()) is True


async def test_followed_buy_not_posted(captured, monkeypatch):
    _patch_enrich(monkeypatch, is_followed=True)                   # followed but not a whale
    tr = _trade(usd=4000, trader="0:fbuy", token="EQfb", tx="fb")
    assert await service.handle_trade(tr, None, None, _settings()) is False  # followed buys removed
    assert captured == []


async def test_followed_sell_still_posts(captured, monkeypatch):
    _patch_enrich(monkeypatch, is_followed=True)                   # followed, not whale
    tr = _trade(side=TradeSide.SELL, usd=12000, trader="0:fsell", token="EQfs", tx="fs")
    assert await service.handle_trade(tr, None, None, _settings()) is True


def test_buy_floor_ton_denominated():
    s = _settings(buy_alert_ton=100, buy_alert_usd=300)
    assert service._buy_floor(s, 4.0) == 400.0    # 100 TON × $4
    assert service._buy_floor(s, 0.0) == 300.0     # no TON price -> USD fallback


async def test_handle_respects_explicit_buy_floor(captured, monkeypatch):
    _patch_enrich(monkeypatch, is_whale=True)      # whale; size floor still applies to whale buys
    below = _trade(usd=350, trader="0:fl1", token="EQfl1", tx="fl1")
    assert await service.handle_trade(below, None, None, _settings(), buy_floor_usd=400) is False
    above = _trade(usd=450, trader="0:fl2", token="EQfl2", tx="fl2")
    assert await service.handle_trade(above, None, None, _settings(), buy_floor_usd=400) is True


async def test_recurring_buyer_promoted_but_buy_not_posted(captured, monkeypatch):
    # promotion still records the wallet (for future sell-tracking), but the buy itself isn't
    # posted now that followed buys are removed and the wallet isn't a whale.
    _patch_enrich(monkeypatch)                              # arrives unknown, not a whale
    s = _settings(promote_min_buys=1)
    tr = _trade(usd=2000, trader="0:promote", token="EQpr", tx="pr")
    assert await service.handle_trade(tr, None, None, s) is False
    assert await state.is_followed("0:promote") is True     # crossed the threshold -> followed
    assert captured == []


# ── rendering ───────────────────────────────────────────────────────────────────
def test_render_buy_shows_ton_size():
    tr = Trade(side=TradeSide.BUY, token_address="EQd", token_symbol="DUROVIUS",
               trader="0:b", usd=285, ton_value=100.0)
    text, emojis = render_alert(tr, TraderContext(address="0:b"), _report("DUROVIUS"))
    assert "🟢 <b>BUY · 100 TON ($285) · $DUROVIUS</b>" in text
    assert "🟡 DeDust" in text                                    # venue (report dex is dedust)
    assert ("🟡", 5391224493911876583) in emojis                 # branded venue emoji
    assert ("🔷", 5364245841525645356) in emojis                 # branded Tonviewer emoji
    assert ("🦅", 5391144822268537893) in emojis                 # branded DexScreener emoji
    assert "Tonviewer</a>" in text and "DexScreener</a>" in text
    assert "GeckoTerminal" not in text and "Chart</a>" not in text  # removed
    assert "Hypha" not in text


def test_render_sell_whale_card():
    tr = _trade(side=TradeSide.SELL, usd=14000, token="EQt", trader="0:w")
    ctx = TraderContext(address="0:w", is_whale=True, portfolio_usd=200_000)
    text, emojis = render_alert(tr, ctx, _report("CAT"))
    assert "WHALE SELL" in text and "$14.0k" in text
    assert "Hypha" not in text
