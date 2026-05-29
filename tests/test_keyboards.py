"""The menu is minimal: a whale drill-down toggle + refresh, and back from the drill-down."""

from hypha.bot.keyboards import menu_keyboard
from hypha.models import LaunchpadReport, LaunchStatus, TokenInfo, TokenReport


def _report():
    return TokenReport(
        token=TokenInfo(address="EQ_test", symbol="X"),
        launchpad=LaunchpadReport(status=LaunchStatus.UNKNOWN),
    )


def _callbacks(kb):
    return [b.callback_data for row in kb.inline_keyboard for b in row if b.callback_data]


def test_report_view_offers_whale_drilldown_and_refresh():
    cbs = _callbacks(menu_keyboard(_report(), current="report"))
    assert "whales:EQ_test" in cbs
    assert "refresh:EQ_test" in cbs


def test_whale_view_has_back_to_report():
    cbs = _callbacks(menu_keyboard(_report(), current="whales"))
    assert "report:EQ_test" in cbs        # back to the card
    assert "whales:EQ_test" not in cbs    # not re-offering the current view
