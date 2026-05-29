"""Inline menu. The card holds everything (incl. the full top-wallet signal), so navigation
is minimal: a Buy link and Refresh. See SPEC.md §7."""

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

    rows.append([InlineKeyboardButton(text="🔁 Refresh", callback_data=f"refresh:{addr}")])
    return InlineKeyboardMarkup(inline_keyboard=rows)
