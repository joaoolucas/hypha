"""Inline menu — a navigable hub so the whole bot works by tapping, no commands needed.

Every view (report / holders / whales / liquidity) shows the same menu with the *other*
sections plus a Buy link and Refresh. The current section is omitted, so "📊 Report" doubles
as a Back button from any detail view. See SPEC.md §7.
"""

from __future__ import annotations

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from ..models import TokenReport
from ..referral.router import build_buy

# section key -> button label. Order defines the menu layout.
SECTIONS: list[tuple[str, str]] = [
    ("report", "📊 Report"),
    ("holders", "🔬 Holders"),
    ("whales", "🐋 Whales"),
    ("dex", "💧 Liquidity"),
]


def menu_keyboard(report: TokenReport, current: str = "report") -> InlineKeyboardMarkup:
    addr = report.token.address
    rows: list[list[InlineKeyboardButton]] = []

    buy = build_buy(report)
    if buy:
        rows.append([InlineKeyboardButton(text=buy["label"], url=buy["url"])])

    # navigation: every section except the one we're already on
    nav = [
        InlineKeyboardButton(text=label, callback_data=f"{key}:{addr}")
        for key, label in SECTIONS
        if key != current
    ]
    for i in range(0, len(nav), 3):
        rows.append(nav[i:i + 3])

    rows.append([InlineKeyboardButton(text="🔁 Refresh", callback_data=f"refresh:{addr}")])
    return InlineKeyboardMarkup(inline_keyboard=rows)
