import asyncio
import logging
from pyrogram import Client, filters
from pyrogram.types import (
    Message, CallbackQuery,
    InlineKeyboardMarkup, InlineKeyboardButton
)
from config import Config
from helper.database import db
from plugins.start import check_ban, check_fsub, check_shutdown, btn, ik

logger = logging.getLogger(__name__)


# ══════════════════════════════════════════════════════════
#  /format   /delformat   /vformat
# ══════════════════════════════════════════════════════════
FORMAT_HELP = (
    "✦ <b>Iᴍᴘᴏʀᴛᴀɴᴛ</b>: Bᴇꜰᴏʀᴇ ᴜsɪɴɢ <code>/format</code> ᴛᴏ ʀᴇɴᴀᴍᴇ ʏᴏᴜʀ ꜰɪʟᴇs, ᴜsᴇ ᴀ ᴄʟᴇᴀʀ ᴛᴇᴍᴘʟᴀᴛᴇ.\n\n"
    "<b>Fᴏʀᴍᴀᴛᴛɪɴɢ Oᴘᴛɪᴏɴs :</b>\n"
    "- <code>{title}</code>   : Cʟᴇᴀɴᴇᴅ ᴛɪᴛʟᴇ ᴀꜰᴛᴇʀ ᴊᴜɴᴋ ʀᴇᴍᴏᴠᴀʟ\n"
    "- <code>{season}</code>  : Sᴇᴀsᴏɴ ɴᴜᴍʙᴇʀ (ᴇ.ɢ., 01)\n"
    "- <code>{episode}</code> : Eᴘɪsᴏᴅᴇ ɴᴜᴍʙᴇʀ\n"
    "- <code>{quality}</code> : 480ᴘ / 720ᴘ / 1080ᴘ / 2160ᴘ\n"
    "- <code>{audio}</code>   : Sᴜʙ · Dᴜʙ · Dᴜᴀʟ · Mᴜʟᴛɪ · ᴇᴛᴄ\n\n"
    "<b>◍ Exᴀᴍᴘʟᴇs :</b>\n"
    "<code>/format [S{season}-E{episode}] {title} [{quality}] [{audio}]</code>\n"
    "<code>/format [S{season}-E{episode}] My Show [{quality}] [Multi] @OtakuFlix_Net</code>"
)


@Client.on_message(filters.command("format") & filters.private)
@check_shutdown
@check_ban
@check_fsub
async def format_cmd(client: Client, message: Message):
    uid = message.from_user.id
    args = message.text.split(None, 1)

    if len(args) < 2:
        existing = await db.get_format_template(uid)
        if existing:
            await message.reply_text(
                "ⓘ <b>𝗙𝗢𝗥𝗠𝗔𝗧 𝗔𝗟𝗥𝗘𝗔𝗗𝗬 𝗦𝗘𝗧</b>\n\n"
                "<blockquote>◍ A ꜰᴏʀᴍᴀᴛ ᴛᴇᴍᴘʟᴀᴛᴇ ɪs ᴀʟʀᴇᴀᴅʏ ᴄᴏɴꜰɪɢᴜʀᴇᴅ ᴀɴᴅ ᴀᴄᴛɪᴠᴇ ꜰᴏʀ ʏᴏᴜʀ ꜰɪʟᴇ ᴘʀᴏᴄᴇssɪɴɢ.\n"
                f"➥ <code>{existing}</code></blockquote>\n\n"
                "<blockquote>➥ Pʟᴇᴀsᴇ ᴜsᴇ <code>/delformat</code> ᴛᴏ ʀᴇᴍᴏᴠᴇ ɪᴛ ʙᴇꜰᴏʀᴇ sᴇᴛᴛɪɴɢ ᴀ ɴᴇᴡ ᴏɴᴇ.</blockquote>"
            )
        else:
            await message.reply_text(FORMAT_HELP)
        return

    template = args[1].strip()
    await db.set_format_template(uid, template)
    await message.reply_text(
        "✓ <b>𝗙𝗢𝗥𝗠𝗔𝗧 𝗦𝗔𝗩𝗘𝗗</b>\n\n"
        "<blockquote>◍ Yᴏᴜʀ ᴀᴜᴛᴏ-ʀᴇɴᴀᴍᴇ ᴛᴇᴍᴘʟᴀᴛᴇ ʜᴀs ʙᴇᴇɴ sᴜᴄᴄᴇssꜰᴜʟʟʏ ᴜᴘᴅᴀᴛᴇᴅ.\n"
        f"➥ <code>{template}</code></blockquote>"
    )


@Client.on_message(filters.command("delformat") & filters.private)
@check_shutdown
@check_ban
@check_fsub
async def delformat_cmd(client: Client, message: Message):
    uid = message.from_user.id
    if not await db.get_format_template(uid):
        await message.reply_text(
            "ⓘ <b>𝗡𝗢 𝗙𝗢𝗥𝗠𝗔𝗧 𝗙𝗢𝗨𝗡𝗗</b>\n\n"
            "<blockquote>◍ Yᴏᴜ ᴅᴏɴ'ᴛ ʜᴀᴠᴇ ᴀɴʏ Aᴜᴛᴏ-Rᴇɴᴀᴍᴇ ᴛᴇᴍᴘʟᴀᴛᴇ sᴇᴛ.\n"
            "➥ Pʟᴇᴀsᴇ sᴇᴛ ᴏɴᴇ ᴜsɪɴɢ <code>/format</code></blockquote>"
        )
        return
    await db.del_format_template(uid)
    await message.reply_text(
        "✓ <b>𝗙𝗢𝗥𝗠𝗔𝗧 𝗗𝗘𝗟𝗘𝗧𝗘𝗗</b>\n\n"
        "<blockquote>◍ Yᴏᴜʀ ᴀᴜᴛᴏ-ʀᴇɴᴀᴍᴇ ᴛᴇᴍᴘʟᴀᴛᴇ ʜᴀs ʙᴇᴇɴ sᴜᴄᴄᴇssꜰᴜʟʟʏ ʀᴇᴍᴏᴠᴇᴅ.</blockquote>"
    )


@Client.on_message(filters.command("vformat") & filters.private)
@check_shutdown
@check_ban
@check_fsub
async def vformat_cmd(client: Client, message: Message):
    uid = message.from_user.id
    t   = await db.get_format_template(uid)
    if t:
        await message.reply_text(
            "ⓘ <b>𝗖𝗨𝗥𝗥𝗘𝗡𝗧 𝗙𝗢𝗥𝗠𝗔𝗧</b>\n\n"
            "<blockquote>◍ Tʜᴇ ꜰᴏʟʟᴏᴡɪɴɢ ꜰᴏʀᴍᴀᴛ ɪs ᴄᴜʀʀᴇɴᴛʟʏ ᴄᴏɴꜰɪɢᴜʀᴇᴅ ᴀɴᴅ ᴀᴄᴛɪᴠᴇ ꜰᴏʀ ʏᴏᴜʀ ꜰɪʟᴇ ᴘʀᴏᴄᴇssɪɴɢ.\n"
            f"➥ <code>{t}</code></blockquote>"
        )
    else:
        await message.reply_text(
            "ⓘ <b>𝗡𝗢 𝗙𝗢𝗥𝗠𝗔𝗧 𝗙𝗢𝗨𝗡𝗗</b>\n\n"
            "<blockquote>◍ Yᴏᴜ ᴅᴏɴ'ᴛ ʜᴀᴠᴇ ᴀɴʏ Aᴜᴛᴏ-Rᴇɴᴀᴍᴇ ᴛᴇᴍᴘʟᴀᴛᴇ sᴇᴛ.\n"
            "➥ Pʟᴇᴀsᴇ sᴇᴛ ᴏɴᴇ ᴜsɪɴɢ <code>/format</code></blockquote>"
        )


# ══════════════════════════════════════════════════════════
#  /setsource
# ══════════════════════════════════════════════════════════
@Client.on_message(filters.command("setsource") & filters.private)
@check_shutdown
@check_ban
@check_fsub
async def setsource_cmd(client: Client, message: Message):
    uid = message.from_user.id
    src = await db.get_rename_source(uid)
    label = "✓ Fɪʟᴇɴᴀᴍᴇ" if src == "filename" else "Fɪʟᴇɴᴀᴍᴇ"
    label2 = "✓ Cᴀᴘᴛɪᴏɴ" if src == "caption" else "Cᴀᴘᴛɪᴏɴ"
    kb = ik([btn(label, cd="src_filename"), btn(label2, cd="src_caption")])
    await message.reply_text(
        "ⓘ <b>𝗥𝗘𝗡𝗔𝗠𝗘 𝗦𝗢𝗨𝗥𝗖𝗘</b>\n\n"
        "<blockquote>⓪ Cʜᴏᴏsᴇ ᴡʜᴇʀᴇ ᴛʜᴇ ʙᴏᴛ ᴇxᴛʀᴀᴄᴛs ᴠᴀʀɪᴀʙʟᴇs ꜰʀᴏᴍ (Fɪʟᴇɴᴀᴍᴇ ᴏʀ Cᴀᴘᴛɪᴏɴ).</blockquote>\n"
        f"<blockquote>↳ <b>Cᴜʀʀᴇɴᴛ</b> : <code>{src.upper()}</code></blockquote>",
        reply_markup=kb
    )


@Client.on_callback_query(filters.regex(r"^src_(filename|caption)$"))
@check_ban
async def cb_setsource(client: Client, cq: CallbackQuery):
    src = cq.data.split("_", 1)[1]
    await db.set_rename_source(cq.from_user.id, src)
    label  = "✓ Fɪʟᴇɴᴀᴍᴇ" if src == "filename" else "Fɪʟᴇɴᴀᴍᴇ"
    label2 = "✓ Cᴀᴘᴛɪᴏɴ"  if src == "caption"  else "Cᴀᴘᴛɪᴏɴ"
    kb = ik([btn(label, cd="src_filename"), btn(label2, cd="src_caption")])
    try:
        await cq.message.edit_text(
            "ⓘ <b>𝗥𝗘𝗡𝗔𝗠𝗘 𝗦𝗢𝗨𝗥𝗖𝗘</b>\n\n"
            "<blockquote>⓪ Cʜᴏᴏsᴇ ᴡʜᴇʀᴇ ᴛʜᴇ ʙᴏᴛ ᴇxᴛʀᴀᴄᴛs ᴠᴀʀɪᴀʙʟᴇs ꜰʀᴏᴍ (Fɪʟᴇɴᴀᴍᴇ ᴏʀ Cᴀᴘᴛɪᴏɴ).</blockquote>\n"
            f"<blockquote>↳ <b>Cᴜʀʀᴇɴᴛ</b> : <code>{src.upper()}</code></blockquote>",
            reply_markup=kb
        )
    except Exception:
        pass
    await cq.answer(f"Source set to {src}", show_alert=False)


# ══════════════════════════════════════════════════════════
#  /setmedia
# ══════════════════════════════════════════════════════════
@Client.on_message(filters.command("setmedia") & filters.private)
@check_shutdown
@check_ban
@check_fsub
async def setmedia_cmd(client: Client, message: Message):
    uid  = message.from_user.id
    pref = await db.get_media_preference(uid)
    d_lbl = "✓ DOCUMENT" if pref == "document" else "DOCUMENT"
    v_lbl = "✓ VIDEO"    if pref == "video"    else "VIDEO"
    kb = ik([btn(d_lbl, cd="media_document"), btn(v_lbl, cd="media_video")])
    await message.reply_text(
        "ⓘ <b>𝗠𝗘𝗗𝗜𝗔 𝗣𝗥𝗘𝗙𝗘𝗥𝗘𝗡𝗖𝗘</b>\n\n"
        "<blockquote>◍ Cʜᴏᴏsᴇ ʜᴏᴡ ᴛʜᴇ ʙᴏᴛ sʜᴏᴜʟᴅ ʜᴀɴᴅʟᴇ ʏᴏᴜʀ ᴜᴘʟᴏᴀᴅᴇᴅ ꜰɪʟᴇs.</blockquote>\n"
        f"<blockquote>➥ Cᴜʀʀᴇɴᴛ : <code>{pref.upper()}</code></blockquote>",
        reply_markup=kb
    )


@Client.on_callback_query(filters.regex(r"^media_(document|video)$"))
@check_ban
async def cb_setmedia(client: Client, cq: CallbackQuery):
    pref = cq.data.split("_", 1)[1]
    await db.set_media_preference(cq.from_user.id, pref)
    d_lbl = "✓ DOCUMENT" if pref == "document" else "DOCUMENT"
    v_lbl = "✓ VIDEO"    if pref == "video"    else "VIDEO"
    kb = ik([btn(d_lbl, cd="media_document"), btn(v_lbl, cd="media_video")])
    try:
        await cq.message.edit_text(
            "ⓘ <b>𝗠𝗘𝗗𝗜𝗔 𝗣𝗥𝗘𝗙𝗘𝗥𝗘𝗡𝗖𝗘</b>\n\n"
            "<blockquote>◍ Cʜᴏᴏsᴇ ʜᴏᴡ ᴛʜᴇ ʙᴏᴛ sʜᴏᴜʟᴅ ʜᴀɴᴅʟᴇ ʏᴏᴜʀ ᴜᴘʟᴏᴀᴅᴇᴅ ꜰɪʟᴇs.</blockquote>\n"
            f"<blockquote>➥ Cᴜʀʀᴇɴᴛ : <code>{pref.upper()}</code></blockquote>",
            reply_markup=kb
        )
    except Exception:
        pass
    await cq.answer(f"Media type set to {pref}", show_alert=False)


# ══════════════════════════════════════════════════════════
#  /sthumb  /del_thumb  /vthumb
# ══════════════════════════════════════════════════════════
@Client.on_message(filters.command("sthumb") & filters.private)
@check_shutdown
@check_ban
@check_fsub
async def sthumb_cmd(client: Client, message: Message):
    uid = message.from_user.id
    # If there's already a thumbnail set
    if await db.get_thumbnail(uid):
        await message.reply_text(
            "ⓘ <b>𝗧𝗛𝗨𝗠𝗕𝗡𝗔𝗜𝗟 𝗔𝗟𝗥𝗘𝗔𝗗𝗬 𝗦𝗘𝗧</b>\n\n"
            "<blockquote>◍ A ᴄᴜsᴛᴏᴍ ᴛʜᴜᴍʙɴᴀɪʟ ɪs ᴀʟʀᴇᴀᴅʏ ᴄᴏɴꜰɪɢᴜʀᴇᴅ ᴀɴᴅ ᴀᴄᴛɪᴠᴇ ꜰᴏʀ ʏᴏᴜʀ ꜰɪʟᴇ ᴘʀᴏᴄᴇssɪɴɢ.\n"
            "➥ Pʟᴇᴀsᴇ ᴜsᴇ <code>/del_thumb</code> ᴛᴏ ʀᴇᴍᴏᴠᴇ ɪᴛ ʙᴇꜰᴏʀᴇ sᴇᴛᴛɪɴɢ ᴀ ɴᴇᴡ ᴏɴᴇ.</blockquote>"
        )
        return
    # Must be a reply to a photo
    if not (message.reply_to_message and message.reply_to_message.photo):
        await message.reply_text(
            "ⓘ <b>𝗜𝗡𝗩𝗔𝗟𝗜𝗗 𝗥𝗘𝗤𝗨𝗘𝗦𝗧</b>\n\n"
            "<blockquote>◍ Pʟᴇᴀsᴇ ʀᴇᴘʟʏ ᴛᴏ ᴀ ᴘʜᴏᴛᴏ ᴡɪᴛʜ <code>/sthumb</code> ᴛᴏ sᴇᴛ ɪᴛ ᴀs ʏᴏᴜʀ ᴛʜᴜᴍʙɴᴀɪʟ.</blockquote>"
        )
        return
    fid = message.reply_to_message.photo.file_id
    await db.set_thumbnail(uid, fid)
    await message.reply_text(
        "✓ <b>𝗧𝗛𝗨𝗠𝗕𝗡𝗔𝗜𝗟 𝗦𝗔𝗩𝗘𝗗</b>\n\n"
        "<blockquote>◍ Yᴏᴜʀ ᴄᴜsᴛᴏᴍ ᴛʜᴜᴍʙɴᴀɪʟ ʜᴀs ʙᴇᴇɴ sᴜᴄᴄᴇssꜰᴜʟʟʏ ᴜᴘᴅᴀᴛᴇᴅ.</blockquote>"
    )


@Client.on_message(filters.command("del_thumb") & filters.private)
@check_shutdown
@check_ban
@check_fsub
async def del_thumb_cmd(client: Client, message: Message):
    uid = message.from_user.id
    if not await db.get_thumbnail(uid):
        await message.reply_text(
            "ⓘ <b>𝗡𝗢 𝗧𝗛𝗨𝗠𝗕𝗡𝗔𝗜𝗟 𝗙𝗢𝗨𝗡𝗗</b>\n\n"
            "<blockquote>◍ Yᴏᴜ ᴅᴏɴ'ᴛ ʜᴀᴠᴇ ᴀɴʏ ᴄᴜsᴛᴏᴍ ᴛʜᴜᴍʙɴᴀɪʟ sᴇᴛ.</blockquote>"
        )
        return
    await db.del_thumbnail(uid)
    await message.reply_text(
        "✓ <b>𝗧𝗛𝗨𝗠𝗕𝗡𝗔𝗜𝗟 𝗗𝗘𝗟𝗘𝗧𝗘𝗗</b>\n\n"
        "<blockquote>◍ Yᴏᴜʀ ᴄᴜsᴛᴏᴍ ᴛʜᴜᴍʙɴᴀɪʟ ʜᴀs ʙᴇᴇɴ sᴜᴄᴄᴇssꜰᴜʟʟʏ ʀᴇᴍᴏᴠᴇᴅ.</blockquote>"
    )


@Client.on_message(filters.command("vthumb") & filters.private)
@check_shutdown
@check_ban
@check_fsub
async def vthumb_cmd(client: Client, message: Message):
    uid = message.from_user.id
    fid = await db.get_thumbnail(uid)
    if fid:
        await message.reply_photo(
            fid,
            caption=(
                "ⓘ <b>𝗖𝗨𝗥𝗥𝗘𝗡𝗧 𝗧𝗛𝗨𝗠𝗕𝗡𝗔𝗜𝗟</b>\n\n"
                "<blockquote>◍ Tʜɪs ᴛʜᴜᴍʙɴᴀɪʟ ɪs ᴄᴜʀʀᴇɴᴛʟʏ ᴄᴏɴꜰɪɢᴜʀᴇᴅ ᴀɴᴅ ᴀᴄᴛɪᴠᴇ ꜰᴏʀ ʏᴏᴜʀ ꜰɪʟᴇ ᴘʀᴏᴄᴇssɪɴɢ.</blockquote>"
            )
        )
    else:
        await message.reply_text(
            "ⓘ <b>𝗡𝗢 𝗧𝗛𝗨𝗠𝗕𝗡𝗔𝗜𝗟 𝗙𝗢𝗨𝗡𝗗</b>\n\n"
            "<blockquote>◍ Yᴏᴜ ʜᴀᴠᴇ ɴᴏ ᴄᴜsᴛᴏᴍ ᴛʜᴜᴍʙɴᴀɪʟ sᴇᴛ. ᴛʜᴇ ᴏʀɪɢɪɴᴀʟ ꜰɪʟᴇ's ᴛʜᴜᴍʙɴᴀɪʟ ᴡɪʟʟ ʙᴇ ᴜsᴇᴅ.</blockquote>"
        )


# ══════════════════════════════════════════════════════════
#  /setcap  /viewcap  /delcap
# ══════════════════════════════════════════════════════════
CAP_HELP = (
    "✦ <b>Iᴍᴘᴏʀᴛᴀɴᴛ</b>: Bᴇꜰᴏʀᴇ ᴜsɪɴɢ <code>/setcap</code>, ᴄʜᴇᴄᴋ ʏᴏᴜʀ ᴛᴇᴍᴘʟᴀᴛᴇ ᴄᴀʀᴇꜰᴜʟʟʏ.\n\n"
    "<b>Cᴀᴘᴛɪᴏɴ Vᴀʀɪᴀʙʟᴇs :</b>\n"
    "- <code>{filename}</code>  : Gᴇᴛs ᴛʜᴇ ʀᴇɴᴀᴍᴇᴅ ꜰɪʟᴇ ɴᴀᴍᴇ\n"
    "- <code>{title}</code>     : Exᴛʀᴀᴄᴛs ᴛʜᴇ ᴛɪᴛʟᴇ\n"
    "- <code>{season}</code>    : Sᴇᴀsᴏɴ ɴᴜᴍʙᴇʀ\n"
    "- <code>{episode}</code>   : Eᴘɪsᴏᴅᴇ ɴᴜᴍʙᴇʀ\n"
    "- <code>{quality}</code>   : Vɪᴅᴇᴏ ǫᴜᴀʟɪᴛʏ\n"
    "- <code>{audio}</code>     : Aᴜᴅɪᴏ ᴛʏᴘᴇ\n\n"
    "<b>➥ Example:</b> <code>/setcap File : {filename}</code>\n"
    "<b>➥ Example:</b> <code>/setcap {title} - S{season}E{episode} [{quality}] {audio}</code>"
)


@Client.on_message(filters.command("setcap") & filters.private)
@check_shutdown
@check_ban
@check_fsub
async def setcap_cmd(client: Client, message: Message):
    uid  = message.from_user.id
    args = message.text.split(None, 1)
    if len(args) < 2:
        await message.reply_text(CAP_HELP)
        return
    cap = args[1].strip()
    await db.set_caption(uid, cap)
    await message.reply_text(
        "✓ <b>𝗖𝗔𝗣𝗧𝗜𝗢𝗡 𝗦𝗔𝗩𝗘𝗗</b>\n\n"
        "<blockquote>◍ Yᴏᴜʀ ᴄᴜsᴛᴏᴍ ᴄᴀᴘᴛɪᴏɴ ʜᴀs ʙᴇᴇɴ sᴜᴄᴄᴇssꜰᴜʟʟʏ ᴜᴘᴅᴀᴛᴇᴅ.\n"
        f"➥ <code>{cap}</code></blockquote>"
    )


@Client.on_message(filters.command("viewcap") & filters.private)
@check_shutdown
@check_ban
@check_fsub
async def viewcap_cmd(client: Client, message: Message):
    uid = message.from_user.id
    cap = await db.get_caption(uid)
    if cap:
        await message.reply_text(
            "ⓘ <b>𝗖𝗨𝗥𝗥𝗘𝗡𝗧 𝗖𝗔𝗣𝗧𝗜𝗢𝗡</b>\n\n"
            "<blockquote>◍ Tʜɪs ᴄᴀᴘᴛɪᴏɴ ɪs ᴄᴜʀʀᴇɴᴛʟʏ ᴄᴏɴꜰɪɢᴜʀᴇᴅ ᴀɴᴅ ᴀᴄᴛɪᴠᴇ ꜰᴏʀ ʏᴏᴜʀ ꜰɪʟᴇs.\n"
            f"➥ <code>{cap}</code></blockquote>"
        )
    else:
        await message.reply_text(
            "ⓘ <b>𝗡𝗢 𝗖𝗔𝗣𝗧𝗜𝗢𝗡 𝗙𝗢𝗨𝗡𝗗</b>\n\n"
            "<blockquote>◍ Yᴏᴜ ᴅᴏɴ'ᴛ ʜᴀᴠᴇ ᴀɴʏ ᴄᴜsᴛᴏᴍ ᴄᴀᴘᴛɪᴏɴ sᴇᴛ.\n"
            "➥ Pʟᴇᴀsᴇ sᴇᴛ ᴏɴᴇ ᴜsɪɴɢ <code>/setcap</code></blockquote>"
        )


@Client.on_message(filters.command("delcap") & filters.private)
@check_shutdown
@check_ban
@check_fsub
async def delcap_cmd(client: Client, message: Message):
    uid = message.from_user.id
    if not await db.get_caption(uid):
        await message.reply_text(
            "ⓘ <b>𝗡𝗢 𝗖𝗔𝗣𝗧𝗜𝗢𝗡 𝗙𝗢𝗨𝗡𝗗</b>\n\n"
            "<blockquote>◍ Yᴏᴜ ᴅᴏɴ'ᴛ ʜᴀᴠᴇ ᴀɴʏ ᴄᴜsᴛᴏᴍ ᴄᴀᴘᴛɪᴏɴ sᴇᴛ.</blockquote>"
        )
        return
    await db.del_caption(uid)
    await message.reply_text(
        "✓ <b>𝗖𝗔𝗣𝗧𝗜𝗢𝗡 𝗗𝗘𝗟𝗘𝗧𝗘𝗗</b>\n\n"
        "<blockquote>◍ Yᴏᴜʀ ᴄᴜsᴛᴏᴍ ᴄᴀᴘᴛɪᴏɴ ʜᴀs ʙᴇᴇɴ sᴜᴄᴄᴇssꜰᴜʟʟʏ ʀᴇᴍᴏᴠᴇᴅ.</blockquote>"
    )
