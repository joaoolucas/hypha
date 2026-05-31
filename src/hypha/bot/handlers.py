"""Handlers — paste a CA (jetton address) and get ONE card with everything: price, momentum,
holder growth and the smart-money read on the top holders. A single "🐋 Whales" button drills
into the full portfolio scan; Refresh re-pulls. Commands remain as optional shortcuts.
See SPEC.md §7."""

from __future__ import annotations

import structlog
from aiogram import F, Router
from aiogram.filters import Command, CommandObject, CommandStart
from aiogram.types import CallbackQuery, Message

from ..analysis.service import analyze_whales
from ..cache import rate_limit_ok
from ..config import get_settings
from ..tracker import state as tracker_state
from ..utils import clean_address, to_friendly, to_raw
from . import ui
from .keyboards import menu_keyboard

log = structlog.get_logger(__name__)
router = Router()


def _is_admin(uid: int) -> bool:
    """Open when no admins are configured (local dev); gated to admin_ids in production."""
    admins = get_settings().admin_id_set
    return not admins or uid in admins


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


# ── followed-wallet management (admin; feeds the tracker's wallet-centric loop) ──
@router.message(Command("track"))
async def cmd_track(message: Message, command: CommandObject) -> None:
    if not _is_admin(message.from_user.id):
        await message.answer("🍄 Only admins can manage the followed list.")
        return
    addr = clean_address(command.args or "")
    if not addr:
        await message.answer("Usage: <code>/track &lt;wallet address&gt;</code>")
        return
    raw = to_raw(addr)
    await tracker_state.add_followed(raw, reason="manual")
    await message.answer(
        f"👣 Now following <code>{to_friendly(raw)}</code> — its buys & big sells will hit the channel."
    )


@router.message(Command("untrack"))
async def cmd_untrack(message: Message, command: CommandObject) -> None:
    if not _is_admin(message.from_user.id):
        await message.answer("🍄 Only admins can manage the followed list.")
        return
    addr = clean_address(command.args or "")
    if not addr:
        await message.answer("Usage: <code>/untrack &lt;wallet address&gt;</code>")
        return
    removed = await tracker_state.remove_followed(to_raw(addr))
    await message.answer("👣 Unfollowed." if removed else "🍄 That wallet wasn't on the list.")


@router.message(Command("emojiid"))
async def cmd_emojiid(message: Message) -> None:
    """Reply with the custom_emoji_id of any custom emoji in the message — so we can wire the
    real branded venue emoji into alerts. Send: /emojiid <custom emoji> (needs Telegram Premium)."""
    if not _is_admin(message.from_user.id):
        return
    ents = list(message.entities or []) + list(message.caption_entities or [])
    ids = [e.custom_emoji_id for e in ents if e.type == "custom_emoji"]
    if not ids:
        await message.answer(
            "Send <code>/emojiid</code> followed by the custom emoji(s) and I'll return their IDs.\n"
            "<i>(You need Telegram Premium to send custom emoji.)</i>"
        )
        return
    await message.answer("Custom emoji IDs:\n" + "\n".join(f"<code>{i}</code>" for i in ids))


@router.message(Command("followed"))
async def cmd_followed(message: Message) -> None:
    wallets = await tracker_state.followed_list()
    if not wallets:
        await message.answer("🍄 Not following any wallets yet — they're auto-promoted from recurring big buys.")
        return
    lines = [f"• <code>{to_friendly(w)}</code>" for w in wallets[:50]]
    more = f"\n…and {len(wallets) - 50} more" if len(wallets) > 50 else ""
    await message.answer(f"👣 <b>Followed wallets ({len(wallets)})</b>\n" + "\n".join(lines) + more)


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
