"""The card holds everything, so the menu is just Buy (when available) + Refresh."""

from hypha.bot.keyboards import menu_keyboard
from hypha.models import LaunchpadReport, LaunchStatus, TokenInfo, TokenReport


def _report():
    return TokenReport(
        token=TokenInfo(address="EQ_test", symbol="X"),
        launchpad=LaunchpadReport(status=LaunchStatus.UNKNOWN),
    )


def _callbacks(kb):
    return [b.callback_data for row in kb.inline_keyboard for b in row if b.callback_data]


def test_menu_has_refresh_and_no_subtabs():
    cbs = _callbacks(menu_keyboard(_report()))
    assert "refresh:EQ_test" in cbs
    assert "whales:EQ_test" not in cbs
    assert "holders:EQ_test" not in cbs
