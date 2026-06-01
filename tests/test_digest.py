"""Daily 'Top Whale Buys' digest — leaderboard rendering, feed-handle derivation, empty no-op."""

from datetime import datetime, timezone

from hypha.config import Settings
from hypha.tracker import digest


def _settings(**kw):
    base = dict(digest_top_n=5, alerts_channel_id="@WhaleSignalsTON")
    base.update(kw)
    return Settings(**base)


def test_render_matches_example_format():
    rows = [
        ("UTYA", "EQutya", 12_400, 3),
        ("FLOWGAIA", "EQflow", 8_100, 2),
        ("AUM", "EQaum", 5_700, 4),
    ]
    html = digest.render_digest(rows, "WhaleSignalsTON")
    assert "<b>🐋 Top TON Meme Whale Buys Today</b>" in html
    assert "1. $UTYA — $12.4k" in html
    assert "2. $FLOWGAIA — $8.1k" in html
    assert "3. $AUM — $5.7k" in html
    assert 'Full live feed: <a href="https://t.me/WhaleSignalsTON">@WhaleSignalsTON</a>' in html


def test_render_falls_back_to_address_when_symbol_blank():
    rows = [("", "0:" + "aa" * 32, 9_000, 5)]
    html = digest.render_digest(rows, "")
    assert "<code>" in html and "$ —" not in html        # no bare "$ —" for unlabelled tokens
    assert "Full live feed" not in html                  # footer omitted without a handle


def test_render_escapes_symbol():
    html = digest.render_digest([("A<b>", "EQx", 1000, 1)], "")
    assert "&lt;b&gt;" in html and "<b>A" not in html


def test_feed_handle_prefers_config_then_channel():
    assert digest._feed_handle(_settings(feed_handle="@Custom")) == "Custom"
    assert digest._feed_handle(_settings(alerts_channel_id="@WhaleSignalsTON")) == "WhaleSignalsTON"
    assert digest._feed_handle(_settings(alerts_channel_id="-1001234567")) == ""   # numeric id -> no link


def test_since_start_of_utc_day():
    since = digest._since(None)
    assert since.tzinfo == timezone.utc
    assert (since.hour, since.minute, since.second) == (0, 0, 0)


def test_since_rolling_window():
    now = datetime.now(timezone.utc)
    since = digest._since(24)
    assert 23.9 < (now - since).total_seconds() / 3600 < 24.1


class _CapturePublisher:
    def __init__(self):
        self.calls = []

    async def publish(self, channel, html, keyboard):
        self.calls.append((channel, html, keyboard))
        return True


async def test_build_post_skips_when_no_rows(monkeypatch):
    # no data (or DB down) -> top_whale_buys returns [] -> nothing posted, publisher untouched
    async def _none(since, limit):
        return []
    monkeypatch.setattr(digest, "top_whale_buys", _none)

    class _Boom:
        async def publish(self, *a, **k):
            raise AssertionError("should not publish on empty digest")
    assert await digest.build_and_post_digest(_Boom(), _settings()) is False


async def test_build_post_publishes_leaderboard(monkeypatch):
    async def _rows(since, limit):
        return [("UTYA", "EQutya", 12_400, 3), ("AUM", "EQaum", 5_700, 2)]
    monkeypatch.setattr(digest, "top_whale_buys", _rows)
    pub = _CapturePublisher()
    ok = await digest.build_and_post_digest(pub, _settings(alerts_channel_id="@WhaleSignalsTON"))
    assert ok is True and len(pub.calls) == 1
    channel, html, keyboard = pub.calls[0]
    assert channel == "@WhaleSignalsTON" and keyboard is None
    assert "1. $UTYA — $12.4k" in html and "@WhaleSignalsTON" in html
