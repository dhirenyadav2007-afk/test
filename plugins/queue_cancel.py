"""
plugins/queue_cancel.py  —  /queue and /cancel commands.
Imports live stat functions from file_rename to read real-time state.
"""
import asyncio
import random
import logging

from pyrogram import Client, filters
from pyrogram.types import Message

from config import Config
from helper.database import db
from plugins.start import check_ban, check_fsub, check_shutdown, btn, ik

logger = logging.getLogger(__name__)

# Pending cancel codes: uid → code string
_cancel_codes: dict[int, str] = {}

# Commands list — used by both /cancel reply handler and metadata.py
ALL_COMMANDS = [
    "start", "help", "format", "delformat", "vformat",
    "setsource", "setmedia", "sthumb", "del_thumb", "vthumb",
    "setcap", "viewcap", "delcap", "metadata",
    "queue", "cancel", "info", "leaderboard",
    "ban", "unban", "addadmin", "deladmin",
    "status", "users", "shutdown", "fsub", "broadcast",
]


def _get_stats(uid: int) -> tuple[dict, dict]:
    """Import lazily to avoid circular import at module load time."""
    from plugins.file_rename import get_user_stats, get_global_stats
    return get_user_stats(uid), get_global_stats()


# ─── /queue ──────────────────────────────────────────────────────────────────
@Client.on_message(filters.command("queue") & filters.private)
@check_shutdown
@check_ban
@check_fsub
async def queue_cmd(client: Client, message: Message):
    uid    = message.from_user.id
    us, gs = _get_stats(uid)

    text = (
        "<b>✦ 𝗬𝗢𝗨𝗥 𝗤𝗨𝗘𝗨𝗘</b>\n\n"
        "<blockquote>"
        f"┌ Pʀᴏᴄᴇssɪɴɢ : {us['processing']}/3 ꜰɪʟᴇs\n"
        f"├ Wᴀɪᴛɪɴɢ    : {us['waiting']} ꜰɪʟᴇs\n"
        f"└ Tᴏᴛᴀʟ      : {us['total']} ꜰɪʟᴇs"
        "</blockquote>\n\n"
        "<b>✦ 𝗦𝗘𝗥𝗩𝗘𝗥 𝗟𝗢𝗔𝗗</b>\n\n"
        "<blockquote>"
        f"┌ Aᴄᴛɪᴠᴇ Tᴀsᴋs : {gs['active']}\n"
        f"├ Qᴜᴇᴜᴇᴅ       : {gs['queued']}\n"
        f"└ Aᴄᴛɪᴠᴇ Usᴇʀs  : {gs['users']}"
        "</blockquote>\n\n"
        "<blockquote>ⓘ Usᴇ /cancel ᴛᴏ ᴄᴀɴᴄᴇʟ ᴀʟʟ ʏᴏᴜʀ ᴛᴀsᴋs</blockquote>"
    )
    await message.reply_text(text)


# ─── /cancel ─────────────────────────────────────────────────────────────────
@Client.on_message(filters.command("cancel") & filters.private)
@check_shutdown
@check_ban
@check_fsub
async def cancel_cmd(client: Client, message: Message):
    uid    = message.from_user.id
    us, _  = _get_stats(uid)

    if us["total"] == 0:
        await message.reply_text(
            "<blockquote>ⓘ Nᴏ ᴛᴀsᴋs ᴛᴏ ᴄᴀɴᴄᴇʟ.</blockquote>"
        )
        return

    code = str(random.randint(100000, 999999))
    _cancel_codes[uid] = code

    await message.reply_text(
        "ⓘ <b>𝗖𝗢𝗡𝗙𝗜𝗥𝗠 𝗖𝗔𝗡𝗖𝗘𝗟𝗟𝗔𝗧𝗜𝗢𝗡</b>\n\n"
        "<blockquote>◍ Aʀᴇ ʏᴏᴜ ᴀʙsᴏʟᴜᴛᴇʟʏ sᴜʀᴇ ʏᴏᴜ ᴡᴀɴᴛ ᴛᴏ "
        "ᴘᴇʀᴍᴀɴᴇɴᴛʟʏ ᴄᴀɴᴄᴇʟ ᴀɴᴅ ʀᴇᴍᴏᴠᴇ ᴀʟʟ ᴀᴄᴛɪᴠᴇ ᴛᴀsᴋs?</blockquote>\n"
        f"<blockquote>➥ Pʟᴇᴀsᴇ ᴛʏᴘᴇ ᴛʜɪs ᴄᴏᴅᴇ : <code>{code}</code></blockquote>\n"
        "<blockquote>⧗ Exᴘɪʀᴇs ɪɴ 60 sᴇᴄᴏɴᴅs</blockquote>"
    )

    # Auto-expire in background — never blocks handler
    async def _expire(u: int, c: str):
        await asyncio.sleep(60)
        if _cancel_codes.get(u) == c:
            _cancel_codes.pop(u, None)

    asyncio.create_task(_expire(uid, code))


# ─── Cancel code reply (group=1 so it never swallows command messages) ────────
@Client.on_message(
    filters.private & filters.text & ~filters.command(ALL_COMMANDS),
    group=1,
)
async def handle_cancel_code(client: Client, message: Message):
    uid  = message.from_user.id
    code = _cancel_codes.get(uid)
    if not code or message.text.strip() != code:
        return

    _cancel_codes.pop(uid, None)

    # Tell file_rename to stop
    from plugins.file_rename import cancel_user
    cancel_user(uid)

    await message.reply_text(
        "<blockquote>ⓘ Aʟʟ ʏᴏᴜʀ ᴛᴀsᴋs ʜᴀᴠᴇ ʙᴇᴇɴ ᴄᴀɴᴄᴇʟʟᴇᴅ.</blockquote>"
    )