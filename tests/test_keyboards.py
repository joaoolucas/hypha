"""The menu must be self-navigating: every view links to the others + a way back to report."""

from hypha.bot.keyboards import menu_keyboard
from hypha.models import LaunchpadReport, LaunchStatus, TokenInfo, TokenReport


def _report():
    return TokenReport(
        token=TokenInfo(address="EQ_test", symbol="X"),
        launchpad=LaunchpadReport(status=LaunchStatus.UNKNOWN),
    )


def _callbacks(kb):
    return [b.callback_data for row in kb.inline_keyboard for b in row if b.callback_data]


def test_report_menu_offers_the_other_sections():
    cbs = _callbacks(menu_keyboard(_report(), current="report"))
    assert "holders:EQ_test" in cbs
    assert "whales:EQ_test" in cbs
    assert "dex:EQ_test" in cbs
    assert "refresh:EQ_test" in cbs
    # the current section is not repeated as a button
    assert "report:EQ_test" not in cbs


def test_detail_view_has_back_to_report():
    cbs = _callbacks(menu_keyboard(_report(), current="holders"))
    assert "report:EQ_test" in cbs        # 📊 Report acts as Back
    assert "holders:EQ_test" not in cbs   # not on the current tab
    assert "whales:EQ_test" in cbs
