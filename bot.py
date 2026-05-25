import os
import time
import asyncio
import logging
import threading
from datetime import datetime
from pytz import timezone

# ─── Load .env FIRST before anything else reads os.environ ────────────────────
from dotenv import load_dotenv
load_dotenv()

from flask import Flask
from pyrogram import Client
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton

from config import Config

logging.basicConfig(
    level=logging.WARNING,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
# Show INFO from our own code only
for _n in ("__main__", "plugins", "helper"):
    logging.getLogger(_n).setLevel(logging.INFO)
# Silence noisy pyrogram / flask internals
for _n in (
    "pyrogram.connection", "pyrogram.session.auth",
    "pyrogram.session.session", "pyrogram.client",
    "pyrogram.dispatcher", "werkzeug",
):
    logging.getLogger(_n).setLevel(logging.ERROR)
logger = logging.getLogger(__name__)

# ─── Extend Pyrogram MIN_CHANNEL_ID for private supergroups ───────────────────
import pyrogram.utils
pyrogram.utils.MIN_CHANNEL_ID = -1002999999999

# ─── Flask keep-alive ─────────────────────────────────────────────────────────
flask_app = Flask(__name__)

@flask_app.route("/")
def home():
    return "AniRename Bot is alive! 🍃", 200

def run_flask():
    flask_app.run(host="0.0.0.0", port=Config.PORT, use_reloader=False)


# ─── Bot class ────────────────────────────────────────────────────────────────
class AniRenameBot(Client):
    def __init__(self):
        super().__init__(
            name="anirename",
            api_id=Config.API_ID,
            api_hash=Config.API_HASH,
            bot_token=Config.BOT_TOKEN,
            workers=50,
            plugins={"root": "plugins"},
            sleep_threshold=15,
        )
        self.start_time = time.time()

    async def start(self):
        await super().start()
        from plugins.file_rename import start_workers
        start_workers()
        me = await self.get_me()
        self.me = me
        logger.info(f"✅ {me.first_name} (@{me.username}) started!")

        uptime = str(int(time.time() - self.start_time))
        now_ist = datetime.now(timezone("Asia/Kolkata"))
        date_str = now_ist.strftime("%d %B %Y")
        time_str = now_ist.strftime("%I:%M:%S %p")

        # Startup message for support chat
        restart_pic = Config.rand_pic("RESTART")
        restart_text = (
            "<blockquote>≡ <b>AniRename ɪs ᴀᴡᴀᴋᴇ ᴀɢᴀɪɴ</b></blockquote>\n"
            "<blockquote>⓪ Sʟᴇᴘᴛ ʟᴏsᴛ sᴏᴍᴇᴡʜᴇʀᴇ ᴀꜰᴛᴇʀ ᴍɪᴅɴɪɢʜᴛ</blockquote>\n"
            f"<blockquote>⓪ Uᴘᴛɪᴍᴇ: <code>0:00:{uptime.zfill(2)}</code></blockquote>"
        )
        restart_kb = InlineKeyboardMarkup([
            [
                InlineKeyboardButton("UPDATES ↗",   url=Config.UPDATE_CHANNEL),
                InlineKeyboardButton("CHECK BOT ↗", url=f"https://t.me/{Config.BOT_USERNAME}"),
            ],
            [InlineKeyboardButton("DEV ↗", url=Config.SUPPORT_LINK)],
        ])

        for chat_id in [Config.LOG_CHANNEL, Config.SUPPORT_CHAT]:
            try:
                if restart_pic:
                    await self.send_photo(
                        chat_id=chat_id,
                        photo=restart_pic,
                        caption=restart_text,
                        reply_markup=restart_kb,
                    )
                else:
                    await self.send_message(
                        chat_id=chat_id,
                        text=restart_text,
                        reply_markup=restart_kb,
                    )
            except Exception as e:
                logger.warning(f"Could not send restart msg to {chat_id}: {e}")

        # Owner PM notification
        try:
            await self.send_message(
                Config.OWNER_ID,
                "›› ʜᴇʏ sᴇɴᴘᴀɪ!! ɪ'ᴍ ᴀʟɪᴠᴇ ɴᴏᴡ 🍃..."
            )
        except Exception as e:
            logger.warning(f"Could not DM owner: {e}")

    async def stop(self):
        await super().stop()
        logger.info("Bot stopped.")


# ─── Entry point ──────────────────────────────────────────────────────────────
def main():
    # Start Flask in background thread
    flask_thread = threading.Thread(target=run_flask, daemon=True)
    flask_thread.start()
    logger.info(f"Flask keep-alive running on port {Config.PORT}")

    # Run the bot
    AniRenameBot().run()


if __name__ == "__main__":
    main()
