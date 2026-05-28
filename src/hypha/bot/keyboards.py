"""Inline keyboards — Buy / Refresh / Details, with referral-tagged buy links (SPEC.md §6–7)."""

from __future__ import annotations

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from ..models import TokenReport
from ..referral.router import build_buy


def report_keyboard(report: TokenReport) -> InlineKeyboardMarkup | None:
    addr = report.token.address
    rows: list[list[InlineKeyboardButton]] = []

    buy = build_buy(report)
    if buy:
        rows.append([InlineKeyboardButton(text=buy["label"], url=buy["url"])])

    rows.append([
        InlineKeyboardButton(text="🔬 Holders", callback_data=f"holders:{addr}"),
        InlineKeyboardButton(text="🐋 Whales", callback_data=f"whales:{addr}"),
    ])
    rows.append([
        InlineKeyboardButton(text="💧 DEX", callback_data=f"dex:{addr}"),
        InlineKeyboardButton(text="🔁 Refresh", callback_data=f"refresh:{addr}"),
    ])
    return InlineKeyboardMarkup(inline_keyboard=rows)
