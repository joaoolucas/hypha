"""Tracker — dedup/watermark/promotion state, the posting-policy funnel, and alert rendering."""

import pytest

from hypha.bot.channel import render_alert, render_trending
from hypha.config import Settings
from hypha.models import (
    DexReport, HyphaScore, TokenInfo, TokenReport, Trade, TraderContext, TradeSide,
)
from hypha.tracker import service, state
from hypha.tracker.enrich import enrich_trader


def _report(symbol="SHROOM", price=0.001, score=72, mcap=1_000_000):
    return TokenReport(
        token=TokenInfo(address="EQtok", symbol=symbol),
        dex=DexReport(has_pool=True, price_usd=price, market_cap_usd=mcap,
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


async def test_record_token_whale_buy_counts_distinct():
    n, total = await state.record_token_whale_buy("0:tokX", "0:a", 100, 3600)
    assert n == 1 and total == 100
    n, total = await state.record_token_whale_buy("0:tokX", "0:a", 150, 3600)   # same trader again
    assert n == 1 and total == 150                                              # still 1, latest usd
    n, total = await state.record_token_whale_buy("0:tokX", "0:b", 50, 3600)
    assert n == 2 and total == 200                                             # 150 (a) + 50 (b)


async def test_mark_trending_cooldown():
    assert await state.mark_trending("0:tokY", 3600) is True
    assert await state.mark_trending("0:tokY", 3600) is False                  # claimed -> on cooldown


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


async def test_unknown_symbol_resolved_from_onchain(captured, monkeypatch):
    # DexScreener placeholder 'UNKWN' is replaced by the on-chain ticker (here _report -> SHROOM)
    _patch_enrich(monkeypatch, is_whale=True, portfolio_usd=180_000)
    tr = _trade(usd=4200, trader="0:uk1", token="EQuk1", tx="uk1")
    tr.token_symbol = "UNKWN"
    assert await service.handle_trade(tr, None, None, _settings()) is True
    assert "$SHROOM" in captured[0] and "UNKWN" not in captured[0]
    assert tr.token_symbol == "SHROOM"


async def test_unknown_symbol_dropped_when_onchain_also_unknown(captured, monkeypatch):
    async def junk_analyze(addr, **kw):
        return _report(symbol="?")                         # on-chain metadata is nameless too
    monkeypatch.setattr(service, "analyze_token", junk_analyze)
    _patch_enrich(monkeypatch, is_whale=True)
    tr = _trade(usd=4200, trader="0:uk2", token="EQuk2", tx="uk2")
    tr.token_symbol = "UNKWN"
    assert await service.handle_trade(tr, None, None, _settings()) is False
    assert captured == []


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


async def test_high_mcap_buy_not_posted(captured, monkeypatch):
    async def big_analyze(addr, **kw):
        return _report(mcap=50_000_000)                # above the $10M cap
    monkeypatch.setattr(service, "analyze_token", big_analyze)
    _patch_enrich(monkeypatch, is_whale=True)
    tr = _trade(usd=5000, trader="0:big", token="EQbig", tx="big")
    assert await service.handle_trade(tr, None, None, _settings()) is False
    assert captured == []


async def test_wrapped_ton_token_not_posted(captured, monkeypatch):
    _patch_enrich(monkeypatch, is_whale=True)             # whale, but the token is staked TON
    tr = _trade(usd=5000, trader="0:wt", token="EQtston", tx="wt")
    tr.token_symbol = "tsTON"
    assert await service.handle_trade(tr, None, None, _settings()) is False
    assert captured == []


async def test_lp_token_buy_not_posted(captured, monkeypatch):
    _patch_enrich(monkeypatch, is_whale=True)             # whale, but the token is an LP token
    tr = _trade(usd=5000, trader="0:lp", token="EQlp", tx="lp")
    tr.token_symbol = "STON-LP"
    assert await service.handle_trade(tr, None, None, _settings()) is False
    assert captured == []


class _FakeTon:
    def __init__(self, balances):
        self._b = balances

    async def account_jettons(self, addr):
        return self._b

    async def ton_usd(self):
        return 5.0

    async def account_ton(self, addr):
        return 0.0


def _bal(symbol, usd, name="", decimals=9):
    return {"balance": str(int(usd) * 10 ** decimals), "price": {"prices": {"USD": 1.0}},
            "jetton": {"symbol": symbol, "name": name, "decimals": decimals}}


async def test_enrich_excludes_lp_staked_stables_from_holdings():
    bals = [_bal("DOGS", 5000), _bal("STON-LP", 9000), _bal("STAKED", 24000),
            _bal("USDT", 3000), _bal("CAT", 2000)]
    ctx = await enrich_trader("0:hold", _FakeTon(bals), _settings())
    syms = [b["symbol"] for b in ctx.top_bags]
    assert "DOGS" in syms and "CAT" in syms
    assert "STON-LP" not in syms and "STAKED" not in syms and "USDT" not in syms


async def test_whale_floor_is_ton_denominated():
    # 1000 TON × $5 = $5000 whale floor (FakeTon prices TON at $5, holds no native TON)
    s = _settings(whale_portfolio_ton=1000)
    assert (await enrich_trader("0:w2", _FakeTon([_bal("DOGS", 6000)]), s)).is_whale is True
    assert (await enrich_trader("0:w3", _FakeTon([_bal("DOGS", 4000)]), s)).is_whale is False


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


async def test_trending_fires_after_enough_distinct_whales(captured, monkeypatch):
    _patch_enrich(monkeypatch, is_whale=True)
    s = _settings(trending_min_whales=5, trending_window_secs=3600, trending_cooldown_secs=3600)
    for i in range(5):                                             # 5 distinct whales, same token
        tr = _trade(usd=2000, trader=f"0:tw{i}", token="EQtrend", tx=f"tw{i}")
        await service.handle_trade(tr, None, None, s)
    trending = [p for p in captured if "TRENDING" in p]
    assert len(trending) == 1                                     # fires once, on the 5th whale
    assert "5 whales bought in the last hour" in trending[0]
    assert "$TRENDING" not in trending[0]                         # symbol comes from the trade (SHROOM)


async def test_trending_needs_distinct_not_repeat_buyers(captured, monkeypatch):
    _patch_enrich(monkeypatch, is_whale=True)
    s = _settings(trending_min_whales=5, trending_window_secs=3600)
    for i in range(6):                                            # one whale buying 6 times != trending
        tr = _trade(usd=2000, trader="0:same", token="EQrepeat", tx=f"rp{i}")
        await service.handle_trade(tr, None, None, s)
    assert [p for p in captured if "TRENDING" in p] == []


def test_render_trending_format():
    report = _report(symbol="SIGNETRING", mcap=5_500)
    html, kb = render_trending(report, "SIGNETRING", 5, 2_400, 3600)
    assert "🔥🐋 <b>TRENDING · $SIGNETRING</b>" in html
    assert "5 whales bought in the last hour · $2.4k total" in html
    assert "🧬 CA:" in html and kb is not None


def test_buy_floor_ton_denominated():
    s = _settings(buy_alert_ton=100, buy_alert_usd=300)
    assert service._buy_floor(s, 4.0) == 400.0    # 100 TON × $4
    assert service._buy_floor(s, 0.0) == 300.0     # no TON price -> USD fallback


def test_launchpad_buy_floor_ton_denominated():
    s = _settings(launchpad_buy_alert_ton=20, launchpad_buy_alert_usd=38)
    assert service._launchpad_buy_floor(s, 4.0) == 80.0    # 20 TON × $4
    assert service._launchpad_buy_floor(s, 0.0) == 38.0    # no TON price -> USD fallback


async def test_launchpad_buy_uses_lower_floor(captured, monkeypatch):
    # a small whale buy on a launchpad token clears the low launchpad floor; the same size on an
    # established pool is dropped by the higher regular floor. The whale gate still applies to both.
    _patch_enrich(monkeypatch, is_whale=True)
    s = _settings(buy_alert_usd=1000, launchpad_buy_alert_usd=40)
    lp = _trade(usd=60, trader="0:lp1", token="EQlp1", tx="lp1")
    lp.is_launchpad = True
    assert await service.handle_trade(lp, None, None, s) is True
    assert "WHALE BUY" in captured[0]
    reg = _trade(usd=60, trader="0:lp2", token="EQlp2", tx="lp2")     # not launchpad -> 1000 floor
    assert await service.handle_trade(reg, None, None, s) is False


async def test_launchpad_non_whale_still_blocked(captured, monkeypatch):
    # the low floor is not a bypass of the whale gate: a non-whale small launchpad buy still drops
    _patch_enrich(monkeypatch)                                        # not a whale
    s = _settings(launchpad_buy_alert_usd=40)
    lp = _trade(usd=60, trader="0:lp3", token="EQlp3", tx="lp3")
    lp.is_launchpad = True
    assert await service.handle_trade(lp, None, None, s) is False
    assert captured == []


async def test_handle_respects_explicit_buy_floor(captured, monkeypatch):
    _patch_enrich(monkeypatch, is_whale=True)      # whale; size floor still applies to whale buys
    below = _trade(usd=350, trader="0:fl1", token="EQfl1", tx="fl1")
    assert await service.handle_trade(below, None, None, _settings(), buy_floor_usd=400) is False
    above = _trade(usd=450, trader="0:fl2", token="EQfl2", tx="fl2")
    assert await service.handle_trade(above, None, None, _settings(), buy_floor_usd=400) is True


async def test_handle_respects_explicit_sell_floor(captured, monkeypatch):
    _patch_enrich(monkeypatch, is_whale=True)
    below = _trade(side=TradeSide.SELL, usd=800, trader="0:s9", token="EQs9", tx="s9")
    assert await service.handle_trade(below, None, None, _settings(), sell_floor_usd=950) is False
    above = _trade(side=TradeSide.SELL, usd=1200, trader="0:s10", token="EQs10", tx="s10")
    assert await service.handle_trade(above, None, None, _settings(), sell_floor_usd=950) is True


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
def test_render_buy_card_and_buttons():
    tr = Trade(side=TradeSide.BUY, token_address="EQd", token_symbol="DUROVIUS",
               trader="0:b", usd=285, ton_value=100.0)
    html, kb = render_alert(tr, TraderContext(address="0:b", is_whale=True, portfolio_usd=42_000),
                            _report("DUROVIUS"))
    assert "🟢🐋 <b>WHALE BUY · 100 TON ($285) · $DUROVIUS</b>" in html
    assert 'via <a href="https://dedust.io/">DeDust</a>' in html   # venue links to the DEX
    assert "💰 Price " in html and "📈 24h " in html
    assert "🏦 MC " in html and "💧 Liq " in html and "📊 Vol " in html
    assert "💼 " in html and "Wallet" in html
    assert "🧬 CA: <code>" in html
    assert "GeckoTerminal" not in html and "Hypha" not in html
    labels = [b.text for row in kb.inline_keyboard for b in row]
    urls = [b.url for row in kb.inline_keyboard for b in row]
    assert "⚡ DTrade" in labels and "🐶 RedoTrade" in labels
    assert "🔎 Tonviewer" in labels and "🦅 DexScreener" in labels
    assert not any("Buy" in lbl for lbl in labels)               # Buy button removed
    assert any("t.me/dtrade?start=25BSDKtN0o_EQ" in u for u in urls)
    assert any("t.me/redotrade?start=mAJe4lm0_EQ" in u for u in urls)


def test_render_shows_ton_in_holdings():
    tr = Trade(side=TradeSide.BUY, token_address="EQd", token_symbol="X", trader="0:b",
               usd=300, ton_value=100.0)
    ctx = TraderContext(address="0:b", is_whale=True, portfolio_usd=50_000,
                        ton_balance=8791.0, ton_value_usd=45_600.0,
                        top_bags=[{"symbol": "REDO", "usd": 8000}])
    html, _ = render_alert(tr, ctx, _report("X"))
    assert '>Holdings:</a>' in html and "tonviewer.com" in html   # Holdings links to the whale's tonviewer
    assert "• $TON $45.6k" in html                               # native TON, styled like other tokens
    assert "• $REDO $8.0k" in html


def test_render_sell_whale_card():
    tr = _trade(side=TradeSide.SELL, usd=14000, token="EQt", trader="0:w")
    ctx = TraderContext(address="0:w", is_whale=True, portfolio_usd=200_000)
    html, kb = render_alert(tr, ctx, _report("CAT"))
    assert "🔴🐋 <b>WHALE SELL" in html and "$14.0k" in html
    assert kb.inline_keyboard       # buttons present
