"""Handlers — the bot is menu-driven: paste a CA (jetton address) and you get the full
report plus a tappable menu (Holders / Whales / Liquidity / Refresh). Commands still work as
shortcuts. Heavy work runs inline for MVP; fan-out features move to the arq worker as they
land. See SPEC.md §7."""

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


# ── helpers ───────────────────────────────────────────────────────────────────
async def _guard(message: Message) -> bool:
    if not await rate_limit_ok(message.from_user.id):
        await message.answer(ui.RATE_LIMITED)
        return False
    return True


def _address_from(raw: str | None) -> str | None:
    return clean_address(raw or "")


async def _show_token(message: Message, raw: str | None, renderer, current: str):
    """Render a token view (report/holders/dex) with the full navigation menu."""
    address = _address_from(raw)
    if not address:
        await message.answer(ui.BAD_ADDRESS)
        return
    if not await _guard(message):
        return
    placeholder = await message.answer(ui.SPROUTING)
    try:
        report = await analyze_token(address)
        await placeholder.edit_text(
            renderer(report), reply_markup=menu_keyboard(report, current), disable_web_page_preview=True
        )
    except Exception as exc:  # noqa: BLE001
        log.exception("analyze_failed", address=address)
        await placeholder.edit_text(f"🍄 Something rotted in the mycelium: <code>{exc}</code>")


async def _show_whales(message: Message, raw: str | None):
    address = _address_from(raw)
    if not address:
        await message.answer(ui.BAD_ADDRESS)
        return
    if not await _guard(message):
        return
    placeholder = await message.answer(ui.SCANNING)
    try:
        report, portfolio = await analyze_whales(address)
        await placeholder.edit_text(
            ui.render_whales(report, portfolio),
            reply_markup=menu_keyboard(report, "whales"),
            disable_web_page_preview=True,
        )
    except Exception as exc:  # noqa: BLE001
        log.exception("whales_failed", address=address)
        await placeholder.edit_text(f"🐋 Couldn't scan the top wallets: <code>{exc}</code>")


# ── commands (shortcuts; the primary UX is pasting a CA) ────────────────────────
@router.message(CommandStart())
@router.message(Command("help"))
async def cmd_start(message: Message) -> None:
    await message.answer(ui.INTRO, disable_web_page_preview=True)


@router.message(Command("analyze", "score"))
async def cmd_analyze(message: Message, command: CommandObject) -> None:
    await _show_token(message, command.args, ui.render_report, "report")


@router.message(Command("holders"))
async def cmd_holders(message: Message, command: CommandObject) -> None:
    await _show_token(message, command.args, ui.render_holders, "holders")


@router.message(Command("whales", "portfolio"))
async def cmd_whales(message: Message, command: CommandObject) -> None:
    await _show_whales(message, command.args)


@router.message(Command("dex"))
async def cmd_dex(message: Message, command: CommandObject) -> None:
    await _show_token(message, command.args, ui.render_dex, "dex")


@router.message(F.text.func(lambda t: clean_address(t) is not None))
async def on_address(message: Message) -> None:
    """The main path: any message containing a TON address -> full report + menu."""
    await _show_token(message, message.text, ui.render_report, "report")


# ── callbacks (menu navigation) ─────────────────────────────────────────────────
# section -> (renderer, force-refresh, current-tab)
_TOKEN_VIEWS = {
    "report": (ui.render_report, False, "report"),
    "refresh": (ui.render_report, True, "report"),
    "holders": (ui.render_holders, False, "holders"),
    "dex": (ui.render_dex, False, "dex"),
}


@router.callback_query(F.data.regexp(r"^(report|refresh|holders|dex):"))
async def on_view(cb: CallbackQuery) -> None:
    action, _, address = cb.data.partition(":")
    renderer, force, current = _TOKEN_VIEWS[action]
    await cb.answer("🍄 reading…")
    try:
        report = await analyze_token(address, force=force)
        await cb.message.edit_text(
            renderer(report), reply_markup=menu_keyboard(report, current), disable_web_page_preview=True
        )
    except Exception as exc:  # noqa: BLE001
        log.exception("callback_failed", data=cb.data)
        await cb.answer(f"failed: {exc}", show_alert=True)


@router.callback_query(F.data.startswith("whales:"))
async def on_whales_callback(cb: CallbackQuery) -> None:
    address = cb.data.split(":", 1)[1]
    await cb.answer("🐋 scanning top wallets…")
    try:
        report, portfolio = await analyze_whales(address)
        await cb.message.edit_text(
            ui.render_whales(report, portfolio),
            reply_markup=menu_keyboard(report, "whales"),
            disable_web_page_preview=True,
        )
    except Exception as exc:  # noqa: BLE001
        log.exception("whales_callback_failed", data=cb.data)
        await cb.answer(f"failed: {exc}", show_alert=True)
