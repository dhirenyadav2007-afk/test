import asyncio
import logging
import time
from datetime import timedelta
from pyrogram import Client, filters
from pyrogram.types import Message
from config import Config
from helper.database import db
from helper.utils import get_readable_time
from plugins.start import check_ban, btn, ik

logger = logging.getLogger(__name__)

BOT_START_TIME = time.time()


def owner_or_admin(func):
    from functools import wraps
    @wraps(func)
    async def wrapper(client, message, *args, **kwargs):
        uid = message.from_user.id
        if uid == Config.OWNER_ID or await db.is_admin(uid):
            return await func(client, message, *args, **kwargs)
        await message.reply_text("<blockquote>⛔ Yᴏᴜ ᴅᴏɴ'ᴛ ʜᴀᴠᴇ ᴘᴇʀᴍɪssɪᴏɴ ᴛᴏ ᴜsᴇ ᴛʜɪs ᴄᴏᴍᴍᴀɴᴅ.</blockquote>")
    return wrapper


def owner_only(func):
    from functools import wraps
    @wraps(func)
    async def wrapper(client, message, *args, **kwargs):
        if message.from_user.id == Config.OWNER_ID:
            return await func(client, message, *args, **kwargs)
        await message.reply_text("<blockquote>⛔ Oᴡɴᴇʀ ᴏɴʟʏ ᴄᴏᴍᴍᴀɴᴅ.</blockquote>")
    return wrapper


# ─── /ban ─────────────────────────────────────────────────
@Client.on_message(filters.command("ban"))
@owner_or_admin
async def ban_cmd(client: Client, message: Message):
    target_id = None
    reason    = "No reason provided"
    if message.reply_to_message:
        target_id = message.reply_to_message.from_user.id
        args = message.text.split(None, 1)
        reason = args[1] if len(args) > 1 else reason
    else:
        parts = message.text.split()
        if len(parts) >= 2:
            try:
                target_id = int(parts[1])
                reason    = " ".join(parts[2:]) if len(parts) > 2 else reason
            except ValueError:
                await message.reply_text("Usage: /ban <user_id> [reason]")
                return
    if not target_id:
        await message.reply_text("Usage: Reply to a user or /ban <user_id>")
        return
    if target_id == Config.OWNER_ID:
        await message.reply_text("<blockquote>⛔ Cᴀɴɴᴏᴛ ʙᴀɴ ᴛʜᴇ ᴏᴡɴᴇʀ.</blockquote>")
        return
    await db.ban_user(target_id, reason)
    try:
        await client.send_message(target_id, Config.BAN_TXT)
    except Exception:
        pass
    await message.reply_text(
        f"✓ <b>Usᴇʀ {target_id} ʙᴀɴɴᴇᴅ.</b>\n"
        f"<blockquote>Rᴇᴀsᴏɴ: {reason}</blockquote>"
    )
    if Config.LOG_CHANNEL:
        await client.send_message(
            Config.LOG_CHANNEL,
            f"<b>🔨 Ban</b>\nUser: <code>{target_id}</code>\nBy: {message.from_user.mention}\nReason: {reason}"
        )


# ─── /unban ───────────────────────────────────────────────
@Client.on_message(filters.command("unban"))
@owner_or_admin
async def unban_cmd(client: Client, message: Message):
    target_id = None
    if message.reply_to_message:
        target_id = message.reply_to_message.from_user.id
    else:
        parts = message.text.split()
        if len(parts) >= 2:
            try:
                target_id = int(parts[1])
            except ValueError:
                await message.reply_text("Usage: /unban <user_id>")
                return
    if not target_id:
        await message.reply_text("Usage: Reply to a user or /unban <user_id>")
        return
    await db.unban_user(target_id)
    await message.reply_text(f"✓ <b>Usᴇʀ <code>{target_id}</code> ᴜɴʙᴀɴɴᴇᴅ.</b>")


# ─── /addadmin ────────────────────────────────────────────
@Client.on_message(filters.command("addadmin"))
@owner_only
async def addadmin_cmd(client: Client, message: Message):
    target_id = None
    if message.reply_to_message:
        target_id = message.reply_to_message.from_user.id
    else:
        parts = message.text.split()
        if len(parts) >= 2:
            try:
                target_id = int(parts[1])
            except ValueError:
                await message.reply_text("Usage: /addadmin <user_id>")
                return
    if not target_id:
        await message.reply_text("Provide a user_id or reply to a user.")
        return
    await db.add_admin(target_id)
    await message.reply_text(f"✓ <code>{target_id}</code> ᴀᴅᴅᴇᴅ ᴀs ᴀᴅᴍɪɴ.")


# ─── /deladmin ────────────────────────────────────────────
@Client.on_message(filters.command("deladmin"))
@owner_only
async def deladmin_cmd(client: Client, message: Message):
    target_id = None
    if message.reply_to_message:
        target_id = message.reply_to_message.from_user.id
    else:
        parts = message.text.split()
        if len(parts) >= 2:
            try:
                target_id = int(parts[1])
            except ValueError:
                await message.reply_text("Usage: /deladmin <user_id>")
                return
    if not target_id:
        await message.reply_text("Provide a user_id or reply to a user.")
        return
    await db.del_admin(target_id)
    await message.reply_text(f"✓ <code>{target_id}</code> ʀᴇᴍᴏᴠᴇᴅ ꜰʀᴏᴍ ᴀᴅᴍɪɴs.")


# ─── /status ──────────────────────────────────────────────
@Client.on_message(filters.command("status"))
@owner_or_admin
async def status_cmd(client: Client, message: Message):
    from plugins.file_rename import get_global_stats
    total_users = await db.total_users_count()
    uptime_sec  = int(time.time() - BOT_START_TIME)
    uptime_str  = get_readable_time(uptime_sec)
    gs          = get_global_stats()
    shutdown    = await db.get_shutdown()
    fsub_on     = await db.get_fsub_enabled()
    admins      = await db.get_admins()
    await message.reply_text(
        "<b>✦ BOT STATUS</b>\n\n"
        "<blockquote>"
        f"⓪ Uᴘᴛɪᴍᴇ         : <code>{uptime_str}</code>\n"
        f"⓪ Tᴏᴛᴀʟ Usᴇʀs    : <code>{total_users}</code>\n"
        f"⓪ Aᴄᴛɪᴠᴇ Rᴇɴᴀᴍᴇs: <code>{gs['active']}</code>\n"
        f"⓪ Qᴜᴇᴜᴇᴅ         : <code>{gs['queued']}</code>\n"
        f"⓪ Aᴄᴛɪᴠᴇ Usᴇʀs   : <code>{gs['users']}</code>\n"
        f"⓪ Sʜᴜᴛᴅᴏᴡɴ Mᴏᴅᴇ  : <code>{'ON 🔴' if shutdown else 'OFF 🟢'}</code>\n"
        f"⓪ Fsᴜʙ Mᴏᴅᴇ      : <code>{'ON 🟢' if fsub_on else 'OFF 🔴'}</code>\n"
        f"⓪ Aᴅᴍɪɴs          : <code>{len(admins)}</code>"
        "</blockquote>"
    )


# ─── /users ───────────────────────────────────────────────
@Client.on_message(filters.command("users"))
@owner_or_admin
async def users_cmd(client: Client, message: Message):
    total = await db.total_users_count()
    await message.reply_text(
        f"<blockquote>⓪ Tᴏᴛᴀʟ Usᴇʀs : <code>{total}</code></blockquote>"
    )


# ─── /shutdown ────────────────────────────────────────────
@Client.on_message(filters.command("shutdown"))
@owner_only
async def shutdown_cmd(client: Client, message: Message):
    current = await db.get_shutdown()
    await db.set_shutdown(not current)
    state = "ON 🔴" if not current else "OFF 🟢"
    await message.reply_text(
        f"<blockquote>⓪ Sʜᴜᴛᴅᴏᴡɴ Mᴏᴅᴇ ɪs ɴᴏᴡ <b>{state}</b></blockquote>"
    )
    if Config.LOG_CHANNEL:
        await client.send_message(
            Config.LOG_CHANNEL,
            f"<b>Shutdown mode → {state}</b>\nBy: {message.from_user.mention}"
        )


# ─── /fsub toggle ─────────────────────────────────────────
@Client.on_message(filters.command("fsub"))
@owner_or_admin
async def fsub_toggle_cmd(client: Client, message: Message):
    current = await db.get_fsub_enabled()
    await db.set_fsub_enabled(not current)
    state = "ON 🟢" if not current else "OFF 🔴"
    await message.reply_text(
        f"<blockquote>⓪ Fsᴜʙ Mᴏᴅᴇ ɪs ɴᴏᴡ <b>{state}</b></blockquote>"
    )


# ─── Broadcast (owner) ────────────────────────────────────
@Client.on_message(filters.command("broadcast"))
@owner_only
async def broadcast_cmd(client: Client, message: Message):
    if not message.reply_to_message:
        await message.reply_text("Reply to a message to broadcast.")
        return
    bcast_msg = message.reply_to_message
    sent = failed = 0
    m = await message.reply_text("Broadcasting...")
    async for user in db.col.find({}):
        try:
            await bcast_msg.copy(user["_id"])
            sent += 1
        except Exception:
            failed += 1
        await asyncio.sleep(0.05)
    await m.edit_text(
        f"<blockquote>✓ Broadcast done.\nSent: {sent}\nFailed: {failed}</blockquote>"
    )
