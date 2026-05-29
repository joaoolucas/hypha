"""Inline menu. The card holds everything, so navigation is minimal: a Buy link, a single
toggle between the card and the full 🐋 whale drill-down, and Refresh. See SPEC.md §7."""

from __future__ import annotations

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from ..models import TokenReport
from ..referral.router import build_buy


def menu_keyboard(report: TokenReport, current: str = "report") -> InlineKeyboardMarkup:
    addr = report.token.address
    rows: list[list[InlineKeyboardButton]] = []

    buy = build_buy(report)
    if buy:
        rows.append([InlineKeyboardButton(text=buy["label"], url=buy["url"])])

    if current == "whales":
        toggle = InlineKeyboardButton(text="📊 Back to report", callback_data=f"report:{addr}")
    else:
        toggle = InlineKeyboardButton(text="🐋 Whale details", callback_data=f"whales:{addr}")
    rows.append([
        toggle,
        InlineKeyboardButton(text="🔁 Refresh", callback_data=f"refresh:{addr}"),
    ])
    return InlineKeyboardMarkup(inline_keyboard=rows)
