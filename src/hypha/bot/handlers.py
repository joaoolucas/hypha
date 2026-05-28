"""Command + callback handlers. Paste an address or use /analyze, /score, /holders, /dex.
Heavy work runs inline for MVP (API-only = mostly awaiting HTTP); fan-out features move to
the arq worker as they land. See SPEC.md §7."""

from __future__ import annotations

import structlog
from aiogram import F, Router
from aiogram.filters import Command, CommandObject, CommandStart
from aiogram.types import CallbackQuery, Message

from ..analysis.service import analyze_token, analyze_whales
from ..cache import rate_limit_ok
from ..utils import clean_address
from . import ui
from .keyboards import report_keyboard

log = structlog.get_logger(__name__)
router = Router()


# ── helpers ───────────────────────────────────────────────────────────────────
async def _guard(message: Message) -> bool:
    if not await rate_limit_ok(message.from_user.id):
        await message.answer(ui.RATE_LIMITED)
        return False
    return True


async def _run(message: Message, raw: str | None, renderer, *, with_kb: bool, force: bool = False):
    address = clean_address(raw or "")
    if not address:
        await message.answer(ui.BAD_ADDRESS)
        return
    if not await _guard(message):
        return
    placeholder = await message.answer(ui.SPROUTING)
    try:
        report = await analyze_token(address, force=force)
        kb = report_keyboard(report) if with_kb else None
        await placeholder.edit_text(renderer(report), reply_markup=kb, disable_web_page_preview=True)
    except Exception as exc:  # noqa: BLE001
        log.exception("analyze_failed", address=address)
        await placeholder.edit_text(f"🍄 Something rotted in the mycelium: <code>{exc}</code>")


async def _run_whales(message: Message, raw: str | None, *, force: bool = False):
    address = clean_address(raw or "")
    if not address:
        await message.answer(ui.BAD_ADDRESS)
        return
    if not await _guard(message):
        return
    placeholder = await message.answer(ui.SCANNING)
    try:
        report, portfolio = await analyze_whales(address, force=force)
        await placeholder.edit_text(ui.render_whales(report, portfolio), disable_web_page_preview=True)
    except Exception as exc:  # noqa: BLE001
        log.exception("whales_failed", address=address)
        await placeholder.edit_text(f"🐋 Couldn't scan the top wallets: <code>{exc}</code>")


# ── commands ──────────────────────────────────────────────────────────────────
@router.message(CommandStart())
@router.message(Command("help"))
async def cmd_start(message: Message) -> None:
    await message.answer(ui.INTRO, disable_web_page_preview=True)


@router.message(Command("analyze", "score"))
async def cmd_analyze(message: Message, command: CommandObject) -> None:
    await _run(message, command.args, ui.render_report, with_kb=True)


@router.message(Command("holders"))
async def cmd_holders(message: Message, command: CommandObject) -> None:
    await _run(message, command.args, ui.render_holders, with_kb=False)


@router.message(Command("whales", "portfolio"))
async def cmd_whales(message: Message, command: CommandObject) -> None:
    await _run_whales(message, command.args)


@router.message(Command("dex"))
async def cmd_dex(message: Message, command: CommandObject) -> None:
    await _run(message, command.args, ui.render_dex, with_kb=False)


@router.message(F.text.func(lambda t: clean_address(t) is not None))
async def on_address(message: Message) -> None:
    await _run(message, message.text, ui.render_report, with_kb=True)


# ── callbacks ─────────────────────────────────────────────────────────────────
_RENDERERS = {
    "refresh": (ui.render_report, True, True),
    "holders": (ui.render_holders, False, False),
    "dex": (ui.render_dex, False, False),
}


@router.callback_query(F.data.regexp(r"^(refresh|holders|dex):"))
async def on_callback(cb: CallbackQuery) -> None:
    action, _, address = cb.data.partition(":")
    renderer, with_kb, force = _RENDERERS[action]
    await cb.answer("🍄 reading…")
    try:
        report = await analyze_token(address, force=force)
        kb = report_keyboard(report) if with_kb else cb.message.reply_markup
        await cb.message.edit_text(renderer(report), reply_markup=kb, disable_web_page_preview=True)
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
            reply_markup=cb.message.reply_markup,
            disable_web_page_preview=True,
        )
    except Exception as exc:  # noqa: BLE001
        log.exception("whales_callback_failed", data=cb.data)
        await cb.answer(f"failed: {exc}", show_alert=True)
