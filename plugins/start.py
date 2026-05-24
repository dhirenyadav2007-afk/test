import asyncio
import random
import logging
from datetime import datetime
from functools import wraps

from pyrogram import Client, filters
from pyrogram.types import (
    Message, CallbackQuery,
    InlineKeyboardMarkup, InlineKeyboardButton
)
from pyrogram.errors import UserNotParticipant, ChatAdminRequired

from config import Config
from helper.database import db
from helper.utils import send_log

logger = logging.getLogger(__name__)

# ─── Helper: build inline keyboard ───────────────────────────────────────────
def ik(*rows) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(list(rows))

def btn(text, cd=None, url=None) -> InlineKeyboardButton:
    if url:
        return InlineKeyboardButton(text, url=url)
    return InlineKeyboardButton(text, callback_data=cd)


# ─── Decorators ──────────────────────────────────────────────────────────────
def check_ban(func):
    @wraps(func)
    async def wrapper(client, update, *args, **kwargs):
        uid = (update.from_user or update.message.from_user).id
        if await db.is_banned(uid):
            txt = Config.BAN_TXT
            kb  = ik([btn("Cᴏɴᴛᴀᴄᴛ ʜᴇʀᴇ", url=Config.SUPPORT_LINK)])
            if isinstance(update, Message):
                await update.reply_text(txt, reply_markup=kb)
            else:
                await update.answer(txt[:200], show_alert=True)
            return
        return await func(client, update, *args, **kwargs)
    return wrapper


def check_fsub(func):
    @wraps(func)
    async def wrapper(client, update, *args, **kwargs):
        # skip if fsub is disabled globally
        if not await db.get_fsub_enabled():
            return await func(client, update, *args, **kwargs)
        if not Config.FSUB_CHANNELS:
            return await func(client, update, *args, **kwargs)

        user = getattr(update, "from_user", None) or getattr(update, "message", {})
        if hasattr(user, "id"):
            uid = user.id
        else:
            return await func(client, update, *args, **kwargs)

        not_joined = []
        for ch in Config.FSUB_CHANNELS:
            try:
                member = await client.get_chat_member(ch, uid)
                if member.status.name in ("LEFT", "BANNED", "KICKED"):
                    not_joined.append(ch)
            except UserNotParticipant:
                not_joined.append(ch)
            except Exception:
                pass

        if not_joined:
            mention = update.from_user.mention if isinstance(update, Message) else update.message.from_user.mention
            pic = Config.rand_pic("FSUB")
            text = Config.FSUB_TXT.format(mention=mention)
            buttons = []
            for i, ch in enumerate(not_joined):
                try:
                    chat = await client.get_chat(ch)
                    inv = chat.invite_link or await client.export_chat_invite_link(ch)
                    buttons.append([btn(f"Join : {chat.title}", url=inv)])
                except Exception:
                    buttons.append([btn(f"Join Channel {i+1}", url="https://t.me")])
            buttons.append([btn("✓ ᴛʀʏ ᴄʜᴇᴄᴋ ɴᴏᴡ", cd="fsub_check")])
            kb = InlineKeyboardMarkup(buttons)
            if isinstance(update, Message):
                if pic:
                    await update.reply_photo(pic, caption=text, reply_markup=kb)
                else:
                    await update.reply_text(text, reply_markup=kb)
            else:
                await update.answer("ᴘʟᴇᴀsᴇ ᴊᴏɪɴ ᴛʜᴇ ʀᴇǫᴜɪʀᴇᴅ ᴄʜᴀɴɴᴇʟs ᴛᴏ ᴜsᴇ ᴍᴇ!", show_alert=True)
            return
        return await func(client, update, *args, **kwargs)
    return wrapper


def check_shutdown(func):
    """Block regular users when shutdown mode is on."""
    @wraps(func)
    async def wrapper(client, update, *args, **kwargs):
        uid = getattr(getattr(update, "from_user", None), "id", None)
        if uid in [Config.OWNER_ID] or await db.is_admin(uid or 0):
            return await func(client, update, *args, **kwargs)
        if await db.get_shutdown():
            txt = Config.SHUTDOWN_TXT
            if isinstance(update, Message):
                await update.reply_text(txt)
            else:
                await update.answer(txt[:200], show_alert=True)
            return
        return await func(client, update, *args, **kwargs)
    return wrapper


# ─── /start ──────────────────────────────────────────────────────────────────
@Client.on_message(filters.command("start") & filters.private)
@check_shutdown
@check_ban
@check_fsub
async def start_cmd(client: Client, message: Message):
    user = message.from_user
    is_new = not await db.is_user_exist(user.id)
    await db.add_user(user.id)
    if is_new:
        await send_log(client, user)

    pic  = Config.rand_pic("START")
    text = Config.START_TXT.format(mention=user.mention)
    kb = ik(
        [btn("ᴜᴘᴅᴀᴛᴇ", url=Config.UPDATE_CHANNEL),
         btn("sᴜᴘᴘᴏʀᴛ",  url=Config.SUPPORT_LINK)],
        [btn("ʜᴇʟᴘ", cd="help_home"),
         btn("ᴀʙᴏᴜᴛ",  cd="about_page")],
    )
    if pic:
        await message.reply_photo(pic, caption=text, reply_markup=kb)
    else:
        await message.reply_text(text, reply_markup=kb)


# ─── /help ───────────────────────────────────────────────────────────────────
@Client.on_message(filters.command("help") & filters.private)
@check_shutdown
@check_ban
@check_fsub
async def help_cmd(client: Client, message: Message):
    pic = Config.rand_pic("START")
    kb = ik(
        [btn("« ʙᴀᴄᴋ", cd="start_back"),
         btn("✕ ᴄʟᴏsᴇ", cd="close_msg")],
    )
    await message.reply_photo(pic, caption=Config.HELP_TXT, reply_markup=kb)


# ─── Callbacks: about / help / fsub_check / close ────────────────────────────
@Client.on_callback_query(filters.regex("^about_page$"))
@check_ban
async def cb_about(client: Client, cq: CallbackQuery):
    pic  = Config.rand_pic("ABOUT")
    text = Config.ABOUT_TXT.format(
        update_channel=Config.UPDATE_CHANNEL,
        support_link=Config.SUPPORT_LINK,
    )
    kb = ik(
        [btn("« ʙᴀᴄᴋ", cd="start_back"),
         btn("✕ ᴄʟᴏsᴇ", cd="close_msg")],
    )
    try:
        if pic:
            await cq.message.edit_media(
                __import__("pyrogram.types", fromlist=["InputMediaPhoto"]).InputMediaPhoto(pic, caption=text),
                reply_markup=kb
            )
        else:
            await cq.message.edit_text(text, reply_markup=kb)
    except Exception:
        pass
    await cq.answer()


@Client.on_callback_query(filters.regex("^start_back$"))
async def cb_start_back(client: Client, cq: CallbackQuery):
    user = cq.from_user
    pic  = Config.rand_pic("START")
    text = Config.START_TXT.format(mention=user.mention)
    kb = ik(
        [btn("ᴜᴘᴅᴀᴛᴇ", url=Config.UPDATE_CHANNEL),
         btn("sᴜᴘᴘᴏʀᴛ",  url=Config.SUPPORT_LINK)],
        [btn("ʜᴇʟᴘ", cd="help_home"),
         btn("ᴀʙᴏᴜᴛ",  cd="about_page")],
    )
    try:
        if pic:
            await cq.message.edit_media(
                __import__("pyrogram.types", fromlist=["InputMediaPhoto"]).InputMediaPhoto(pic, caption=text),
                reply_markup=kb
            )
        else:
            await cq.message.edit_text(text, reply_markup=kb)
    except Exception:
        pass
    await cq.answer()


@Client.on_callback_query(filters.regex("^help_home$"))
@check_ban
async def cb_help(client: Client, cq: CallbackQuery):
    kb = ik(
        [btn("« ʙᴀᴄᴋ", cd="start_back"),
         btn("✕ ᴄʟᴏsᴇ", cd="close_msg")],
    )
    try:
        await cq.message.edit_text(Config.HELP_TXT, reply_markup=kb)
    except Exception:
        pass
    await cq.answer()


@Client.on_callback_query(filters.regex("^fsub_check$"))
@check_ban
@check_fsub
async def cb_fsub_check(client: Client, cq: CallbackQuery):
    await cq.answer("THANKS ^-^\nɴᴏᴡ ʏᴏᴜ ᴄᴀɴ ᴜsᴇ ᴍᴇ ....", show_alert=True)
    # Resend start message
    user = cq.from_user
    pic  = Config.rand_pic("START")
    text = Config.START_TXT.format(mention=user.mention)
    kb = ik(
        [btn("ᴜᴘᴅᴀᴛᴇ", url=Config.UPDATE_CHANNEL),
         btn("sᴜᴘᴘᴏʀᴛ",  url=Config.SUPPORT_LINK)],
        [btn("ʜᴇʟᴘ", cd="help_home"),
         btn("ᴀʙᴏᴜᴛ",  cd="about_page")],
    )
    try:
        if pic:
            await cq.message.edit_media(
                __import__("pyrogram.types", fromlist=["InputMediaPhoto"]).InputMediaPhoto(pic, caption=text),
                reply_markup=kb
            )
        else:
            await cq.message.edit_text(text, reply_markup=kb)
    except Exception:
        pass


@Client.on_callback_query(filters.regex("^close_msg$"))
async def cb_close(client: Client, cq: CallbackQuery):
    await cq.message.delete()
    await cq.answer()


# ─── /info ───────────────────────────────────────────────────────────────────
@Client.on_message(filters.command("info") & filters.private)
@check_shutdown
@check_ban
@check_fsub
async def info_cmd(client: Client, message: Message):
    target = message.reply_to_message.from_user if message.reply_to_message else message.from_user
    await _send_user_info(client, message, target)


async def _send_user_info(client, message, target):
    uid  = target.id
    u    = await db.get_user(uid) or {}
    pic  = Config.rand_pic("USERINFO")
    name = f"{target.first_name or ''} {target.last_name or ''}".strip()
    mention = target.mention
    uname = f"@{target.username}" if target.username else "N/A"
    lang  = getattr(target, "language_code", "N/A")
    renames = u.get("rename_count", 0)
    trust_val = min(100, 30 + renames * 2)
    trust_bar = "▰" * (trust_val // 10) + "▱" * (10 - trust_val // 10)
    status = "Banned 🔴" if u.get("is_banned") else "Normal 🟢"
    joined = u.get("join_date", "Unknown")
    last   = u.get("last_seen", "Recently")
    if isinstance(last, str) and "T" in last:
        try:
            last = datetime.fromisoformat(last).strftime("%d %b %Y")
        except Exception:
            pass
    bio = target.bio if hasattr(target, "bio") else ""

    text = (
        "<b>□ USER INFORMATION</b>\n\n"
        "<blockquote>"
        f"⓪ <b>User ID</b> : <code>{uid}</code>\n"
        f"⓪ <b>Name</b>    : {name}\n"
        f"⓪ <b>Mention</b> : {mention}\n"
        f"⓪ <b>Username</b>: {uname}\n"
        f"⓪ <b>Language</b>: {lang}\n\n"
        f"⓪ <b>Trust</b> : <code>{trust_bar}</code> {trust_val}/100\n\n"
        f"⓪ <b>Status</b>  : {status}\n"
        f"⓪ <b>Joined</b>  : {joined}"
        "</blockquote>\n\n"
        "<blockquote>"
        f"↳ <b>Last seen</b> : {last}\n"
        + (f"↳ <b>Bio</b>: {bio}" if bio else "")
        + "</blockquote>"
    )
    kb = ik([btn("✕ ᴄʟᴏsᴇ", cd="close_msg")])
    if pic:
        m = await message.reply_photo(pic, caption=text, reply_markup=kb)
    else:
        m = await message.reply_text(text, reply_markup=kb)
    asyncio.create_task(_auto_delete(m, 30))


async def _safe_delete(msg):
    try:
        await msg.delete()
    except Exception:
        pass


async def _auto_delete(msg, delay: int):
    """Delete a message after `delay` seconds."""
    await asyncio.sleep(delay)
    await _safe_delete(msg)


# ─── /leaderboard ────────────────────────────────────────────────────────────
@Client.on_message(filters.command("leaderboard") & filters.private)
@check_shutdown
@check_ban
@check_fsub
async def leaderboard_cmd(client: Client, message: Message):
    m = await message.reply_text("⟳ ʟᴏᴀᴅɪɴɢ ʟᴇᴀᴅᴇʀʙᴏᴀʀᴅ...")
    await _show_leaderboard(client, m, message.from_user.id, "today", edit=True)
    asyncio.create_task(_auto_delete(m, 60))


async def _show_leaderboard(client, msg, viewer_id: int, period: str, edit=False):
    pic    = Config.rand_pic("LEADERBOARD")
    board  = await db.get_leaderboard(period)
    rank   = await db.get_user_rank(viewer_id, period)
    period_label = period.upper()

    lines = []
    medals = ["🥇", "🥈", "🥉"]
    for i, entry in enumerate(board[:10], 1):
        medal = medals[i-1] if i <= 3 else f"{i:02d}•"
        lines.append(f"{medal} <b>{entry['name']}</b>\n   └ {entry['count']} Renames")

    rank_txt = f"≡ <b>Yᴏᴜʀ ʀᴀɴᴋ</b> : {rank if rank else 'Unranked'}"

    body = "\n\n".join(lines) if lines else "<i>No data yet...</i>"
    text = (
        f"<b>✦ {period_label} LEADERBOARD</b>\n"
        f"<blockquote>≡ Tᴏᴘ {min(10, len(board))} ᴍᴏsᴛ ᴀᴄᴛɪᴠᴇ ᴜsᴇʀs</blockquote>\n\n"
        f"{body}\n\n"
        f"<blockquote>{rank_txt}</blockquote>"
    )
    kb = ik(
        [btn("Today",    cd="lb_today"),  btn("Week",     cd="lb_week"),  btn("Month",    cd="lb_month")],
        [btn("Year",     cd="lb_year"),   btn("Lifetime", cd="lb_life")],
        [btn("✕ ᴄʟᴏsᴇ", cd="close_msg")],
    )
    try:
        await msg.edit_text(text, reply_markup=kb)
    except Exception:
        pass


@Client.on_callback_query(filters.regex(r"^lb_(today|week|month|year|life)$"))
async def cb_leaderboard(client: Client, cq: CallbackQuery):
    period_map = {"today": "today", "week": "week", "month": "month", "year": "year", "life": "lifetime"}
    key = cq.data.split("_", 1)[1]
    await _show_leaderboard(client, cq.message, cq.from_user.id, period_map[key], edit=True)
    await cq.answer()
