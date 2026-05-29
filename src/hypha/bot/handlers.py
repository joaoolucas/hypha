"""Handlers — paste a CA (jetton address) and get ONE card with everything: price, momentum,
holder growth and the smart-money read on the top holders. A single "🐋 Whales" button drills
into the full portfolio scan; Refresh re-pulls. Commands remain as optional shortcuts.
See SPEC.md §7."""

from __future__ import annotations

import structlog
from aiogram import F, Router
from aiogram.filters import Command, CommandObject, CommandStart
from aiogram.types import CallbackQuery, Message

from ..analysis.service import analyze_token, analyze_whales
from ..cache import rate_limit_ok
from ..utils import clean_address
from . import ui
from .keyboards import menu_keyboard

log = structlog.get_logger(__name__)
router = Router()


async def _guard(message: Message) -> bool:
    if not await rate_limit_ok(message.from_user.id):
        await message.answer(ui.RATE_LIMITED)
        return False
    return True


async def _show_card(message: Message, raw: str | None):
    """The main path: full report + smart-money read + menu, in one card."""
    address = clean_address(raw or "")
    if not address:
        await message.answer(ui.BAD_ADDRESS)
        return
    if not await _guard(message):
        return
    placeholder = await message.answer(ui.SPROUTING)
    try:
        report, pf = await analyze_whales(address)
        await placeholder.edit_text(
            ui.render_report(report, pf),
            reply_markup=menu_keyboard(report, "report"),
            disable_web_page_preview=True,
        )
    except Exception as exc:  # noqa: BLE001
        log.exception("analyze_failed", address=address)
        await placeholder.edit_text(f"🍄 Something rotted in the mycelium: <code>{exc}</code>")


# ── commands (optional shortcuts; the primary UX is pasting a CA) ────────────────
@router.message(CommandStart())
@router.message(Command("help"))
async def cmd_start(message: Message) -> None:
    await message.answer(ui.INTRO, disable_web_page_preview=True)


@router.message(Command("analyze", "score", "whales", "portfolio"))
async def cmd_analyze(message: Message, command: CommandObject) -> None:
    await _show_card(message, command.args)


@router.message(F.text.func(lambda t: clean_address(t) is not None))
async def on_address(message: Message) -> None:
    await _show_card(message, message.text)


# ── callbacks ────────────────────────────────────────────────────────────────────
@router.callback_query(F.data.startswith("report:"))
@router.callback_query(F.data.startswith("refresh:"))
async def on_report(cb: CallbackQuery) -> None:
    address = cb.data.split(":", 1)[1]
    force = cb.data.startswith("refresh:")
    await cb.answer("🍄 reading…")
    try:
        report, pf = await analyze_whales(address, force=force)
        await cb.message.edit_text(
            ui.render_report(report, pf),
            reply_markup=menu_keyboard(report, "report"),
            disable_web_page_preview=True,
        )
    except Exception as exc:  # noqa: BLE001
        log.exception("report_callback_failed", data=cb.data)
        await cb.answer(f"failed: {exc}", show_alert=True)


@router.callback_query(F.data.startswith("whales:"))
async def on_whales(cb: CallbackQuery) -> None:
    address = cb.data.split(":", 1)[1]
    await cb.answer("🐋 reading the whales…")
    try:
        report, pf = await analyze_whales(address)
        await cb.message.edit_text(
            ui.render_whales(report, pf),
            reply_markup=menu_keyboard(report, "whales"),
            disable_web_page_preview=True,
        )
    except Exception as exc:  # noqa: BLE001
        log.exception("whales_callback_failed", data=cb.data)
        await cb.answer(f"failed: {exc}", show_alert=True)
