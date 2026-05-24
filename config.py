import os, time, random
from dotenv import load_dotenv
load_dotenv()
class Config:
    # ─── Pyrogram ───
    API_ID      = int(os.environ.get("API_ID", "27226524"))
    API_HASH    = os.environ.get("API_HASH", "a14c9cd4629fde6b4d9b8c77df00fb00")
    BOT_TOKEN   = os.environ.get("BOT_TOKEN", "")
    BOT_USERNAME = os.environ.get("BOT_USERNAME", "ANIMEXRENAME_BOT")

    # ─── MongoDB ───
    DB_URL  = os.environ.get("DB_URL", "")
    DB_NAME = os.environ.get("DB_NAME", "AniRename")

    # ─── IDs ───
    OWNER_ID      = int(os.environ.get("OWNER_ID", "7156099919"))
    LOG_CHANNEL   = int(os.environ.get("LOG_CHANNEL", "-1003548938800"))
    SUPPORT_CHAT  = int(os.environ.get("SUPPORT_CHAT", "-1003435722587"))
    DUMP_CHANNEL  = int(os.environ.get("DUMP_CHANNEL", "-1002983564230"))

    # ─── ForceSub channels ───
    _fsub_raw = os.environ.get("FSUB_CHANNELS", "")
    FSUB_CHANNELS = [int(x.strip()) for x in _fsub_raw.split(",") if x.strip()] if _fsub_raw else []

    # ─── Flask ───
    PORT = int(os.environ.get("PORT", "10000"))

    # ─── Bot uptime ───
    BOT_UPTIME = time.time()

    # ─── Links ───
    UPDATE_CHANNEL  = os.environ.get("UPDATE_CHANNEL",  "https://t.me/BotifyX_Pro_Botz")
    SUPPORT_LINK    = os.environ.get("SUPPORT_LINK",    "https://t.me/+ij3pcPOXv2U4MDll")
    ADMIN_USERNAME  = os.environ.get("ADMIN_USERNAME",  "@ITsANIMEN")

    # ─── Images (space-separated lists; bot picks random each time) ───
    START_PICS        = os.environ.get("START_PICS",        "").split()
    FSUB_PICS         = os.environ.get("FSUB_PICS",         "").split()
    METADATA_PICS     = os.environ.get("METADATA_PICS",     "").split()
    LEADERBOARD_PICS  = os.environ.get("LEADERBOARD_PICS",  "").split()
    USERINFO_PICS     = os.environ.get("USERINFO_PICS",     "").split()
    RESTART_PICS      = os.environ.get("RESTART_PICS",      "").split()
    ABOUT_PICS        = os.environ.get("ABOUT_PICS",        "").split()

    @classmethod
    def rand_pic(cls, category: str) -> str | None:
        pool = getattr(cls, f"{category.upper()}_PICS", [])
        return random.choice(pool) if pool else None

    # ─── Texts ───
    START_TXT = (
        "<blockquote>›› ʜᴇʏ!!! 彡 {mention} 彡 .....</blockquote>\n"
        "<blockquote>≡ Hᴍᴍᴍ... ᴅᴇᴀʀ ᴜsᴇʀ I'ᴍ ᴀ Adᴠ-ᴀᴜᴛᴏʀᴇɴᴀᴍᴇ ʙᴏᴛ ʙᴜɪʟᴅ ᴡɪᴛʜ ʟᴏᴠᴇ!!!</blockquote>\n"
        "<blockquote>≡ Iᴛ's ɴᴏᴛ ᴀʙᴏᴜᴛ ᴡʜᴇᴛʜᴇʀ I ᴄᴀɴ ᴏʀ ᴄᴀɴ'ᴛ. I'ᴍ ᴅᴏɪɴɢ ɪᴛ. Iꜰ ᴛʜᴇ ᴡᴏʀʟᴅ ᴛᴇʟʟs ᴍᴇ ᴛᴏ sᴛᴇᴘ ʙᴀᴄᴋ, I'ʟʟ ᴊᴜsᴛ ᴘᴜsʜ ʀɪɢʜᴛ ᴛʜʀᴏᴜɢʜ.</blockquote>\n"
        "<blockquote>— Iᴄʜɪɢᴏ Kᴜʀᴏsᴀᴋɪ</blockquote>"
    )

    ABOUT_TXT = (
        "<b>⧉ Sʏsᴛᴇᴍ Oᴠᴇʀᴠɪᴇᴡ </b>\n"
        "<blockquote expandable>"
        "≡ <b>ᴠᴇʀsɪᴏɴ</b> : <code>ᴠ𝟷.𝟶𝟶𝟷</code>\n"
        "≡ <b>sʏsᴛᴇᴍ</b> : ᴘᴇʀsɪsᴛᴇɴᴛ Jᴏʙ ᴇɴɢɪɴᴇ\n"
        "≡ <b>ᴄᴏʀᴇ</b> : Aɴɪ Pᴀʀsᴇ ᴄᴏʀᴇ .ᴘJᴇ . MKV-x\n"
        "≡ <b>Aʀᴄʜ</b> : Cᴏɴᴄᴜʀʀᴇɴᴄʏ-sᴀғᴇ\n"
        "≡ <b>Mᴇᴍᴏʀʏ</b> : ᴀᴅᴠ sᴛᴀᴛᴇ ᴛʀᴀᴄᴋɪɴɢ"
        "</blockquote>\n\n"
        "<b>⧉ Dᴇᴠᴇʟᴏᴘᴇʀ Iɴғᴏ </b>\n"
        "<blockquote expandable>"
        "≡ <b>Dᴇᴠ</b> : <a href='https://t.me/ITSANIMEN'>彡 ΔNI_OTΔKU 彡</a>\n"
        "≡ <b>Mᴀsᴛᴇʀ</b> : <a href='https://t.me/ITSANIMEN'>彡 ΔNI_OTΔKU 彡</a>\n"
        "≡ <b>ᴜᴘᴅᴀᴛᴇs</b> : <a href='{update_channel}'>Bᴏᴛɪғʏx ʙᴏᴛs</a>\n"
        "≡ <b>sᴜᴘᴘᴏʀᴛ</b> : <a href='{support_link}'>Bᴏᴛɪғʏx-Bᴏᴛ Sᴜᴘᴘᴏʀᴛ</a>"
        "</blockquote>"
    )

    BAN_TXT = (
        "<b>Bᴀᴅ ᴘᴇʀsᴏɴ ʏᴏᴜ ᴀʀᴇ ʙᴀɴɴᴇᴅ ʏᴏᴜ ᴄᴀɴ'ᴛ ᴜsᴇ ᴍᴇ ... sᴛᴀʏ ᴀᴡᴀʏ.</b>\n"
        "≡ ɪғ ʏᴏᴜ ᴛʜɪɴᴋ ʏᴏᴜ ɢᴏᴛ ʙᴀɴɴᴇᴅ ᴡɪᴛʜᴏᴜᴛ ᴀɴʏ ʀᴇᴀsᴏɴ ᴄᴏɴᴛᴀᴄᴛ ᴍʏ ᴍᴀsᴛᴇʀ ....\n"
        "— <code>@ITsANIMEN</code>"
    )

    FSUB_TXT = (
        "<blockquote>›› ʜᴇʏ!!! 彡 {mention} 彡 .....</blockquote>\n"
        "<blockquote>≡ Lᴏᴏᴋ's ʟɪᴋᴇ ᴜ ᴀʀᴇ'ᴛ ᴀ ᴍᴇᴍʙᴇʀ ɪɴ ᴛʜᴇ ꜰsᴜʙ ᴄʜᴀɴɴᴇʟ sᴏ ᴊᴏɪɴ ᴛʜᴇ ʀᴇǫᴜᴇsᴛᴇᴅ ᴄʜᴀɴɴᴇʟs .... ᴊᴏɪɴ ᴛʜᴇ ᴄʜᴀɴɴᴇʟs ʙᴇꜰᴏʀᴇ ᴜsɪɴɢ ᴍᴇ ...</blockquote>\n"
        "<blockquote>≡ ꜰᴏʀ ᴀɴʏ ᴇʀʀᴏʀs ᴘʟᴢ ᴄᴏɴᴛᴀᴄᴛ ᴍʏ ᴍᴀsᴛᴇʀ — <code>@ITsANIMEN</code></blockquote>"
    )

    HELP_TXT = (
        "<b>⧉ Hᴇʟᴘ Pᴀɢᴇ :</b>\n\n"
        "<blockquote expandable>"
        "<b>≡ Sᴇᴛᴜᴘ Sᴛᴇᴘs (ᴅᴏ ᴏɴᴄᴇ):</b>\n"
        "• /format — sᴇᴛ ʏᴏᴜʀ ʀᴇɴᴀᴍᴇ ᴛᴇᴍᴘʟᴀᴛᴇ\n"
        "• /setsource — ғɪʟᴇɴᴀᴍᴇ ᴏʀ ᴄᴀᴘᴛɪᴏɴ ᴘᴀʀsɪɴɢ\n"
        "• /setmedia — ᴅᴏᴄᴜᴍᴇɴᴛ ᴏʀ ᴠɪᴅᴇᴏ ᴏᴜᴛᴘᴜᴛ\n"
        "• /sthumb — sᴇᴛ ᴛʜᴜᴍʙɴᴀɪʟ (ᴏᴘᴛɪᴏɴᴀʟ)\n"
        "• /setcap — sᴇᴛ ᴄᴀᴘᴛɪᴏɴ (ᴏᴘᴛɪᴏɴᴀʟ)\n"
        "• /metadata — ᴄᴏɴғɪɢᴜʀᴇ ᴇᴍʙᴇᴅᴅᴇᴅ ᴍᴇᴛᴀᴅᴀᴛᴀ"
        "</blockquote>\n\n" 
        "<blockquote expandable>"
        "<b>≡ Cᴏᴍᴍᴀɴᴅs:</b>\n"
        "▣ /format\n ▣ /delformat\n ▣ /vformat\n"
        "▣ /sthumb\n ▣ /del_thumb\n ▣ /vthumb\n"
        "▣ /setcap\n ▣ /delcap\n ▣ /viewcap\n"
        "▣ /metadata\n ▣ /setsource\n ▣ /setmedia\n"
        "▣ /queue\n ▣ /cancel\n ▣ /info\n ▣ /leaderboard"
        "</blockquote>"
    )

    SHUTDOWN_TXT = (
        "ʜᴍᴍᴍ... ʙᴏᴛ ɪs ᴄᴜʀʀᴇɴᴛʟʏ ɴᴏᴛ ᴡᴏʀᴋɪɴɢ ꜰᴏʀ ᴜsᴇʀs sᴏ ᴘʟᴢ ᴡᴀɪᴛ "
        "...ᴛʜᴇʀᴇ's ᴀ ᴄʜᴀɴᴄᴇ ᴏꜰ ᴅᴇᴠ ᴡᴏʀᴋɪɴɢ ᴏɴ ᴍᴇ ᴀɴᴅ ᴀꜰᴛᴇʀ ᴜᴘᴅᴀᴛᴇs "
        "ᴛʜᴇ ᴍsɢ ᴡɪʟʟ ʙᴇ sᴇɴᴅ ᴛᴏ ʏᴏᴜ ..."
    )

    RENAME_STARTED_TXT = (
        "≡ <b>Rᴇɴᴀᴍᴇ Sᴛᴀʀᴛᴇᴅ...</b>\n"
        "◍ ᴛᴏᴛᴀʟ Fɪʟᴇs : <code>« {total} »</code>\n"
        "◍ Pʀᴏᴄᴇssɪɴɢ Fɪʟᴇs : <code>« {processing} »</code>\n"
        "◍ Fɪʟᴇs Rᴇɴᴀᴍᴇᴅ : <code>« {renamed} »</code>"
    )

    RENAME_DONE_TXT = (
        "≡ <b>Aʟʟ Rᴇɴᴀᴍᴇ Cᴏᴍᴘʟᴇᴛᴇᴅ...</b>\n"
        "◍ ᴛᴏᴛᴀʟ Fɪʟᴇs : <code>« {total} »</code>\n"
        "◍ Fɪʟᴇ Rᴇɴᴀᴍᴇᴅ : <code>« {renamed} »</code>\n"
        "◍ ᴛᴏᴛᴀʟ ᴛɪᴍᴇ ᴛᴀᴋᴇɴ : <code>« {time_taken} »</code>\n"
        "<i>(Aᴜᴛᴏ-ᴅᴇʟᴇᴛᴇ: Fɪʟᴇs ᴡɪʟʟ ʙᴇ ʀᴇᴍᴏᴠᴇᴅ ɪɴ 24h 0m 0s)</i>"
    )
