import logging
import motor.motor_asyncio
from datetime import datetime, date, timezone, timedelta
from config import Config

logger = logging.getLogger(__name__)

class Database:
    def __init__(self, uri: str, name: str):
        self._client = motor.motor_asyncio.AsyncIOMotorClient(uri)
        db = self._client[name]
        self.col          = db["users"]
        self.admins_col   = db["admins"]
        self.fsub_col     = db["fsub_settings"]
        self.rename_log   = db["rename_log"]
        self.shutdown_col = db["shutdown"]

    # ─── User helpers ───────────────────────────────────────────────
    def _default_user(self, uid: int) -> dict:
        return {
            "_id": uid,
            "join_date": date.today().isoformat(),
            "format_template": None,
            "rename_source": "filename",          # 'filename' | 'caption'
            "media_preference": "document",       # 'document' | 'video'
            "file_id": None,                      # thumbnail file_id
            "caption": None,
            "metadata_mode": True,
            "metadata": {
                "title": None, "author": None, "artist": None,
                "audio": None, "subtitle": None, "video": None,
                "encoded_by": None, "custom_tag": None, "comment": None,
            },
            "rename_count": 0,
            "is_banned": False,
            "ban_reason": "",
            "first_name": "",
            "username": None,
            "last_seen": datetime.utcnow().isoformat(),
        }

    async def add_user(self, uid: int) -> None:
        if not await self.col.find_one({"_id": uid}):
            await self.col.insert_one(self._default_user(uid))

    async def is_user_exist(self, uid: int) -> bool:
        return bool(await self.col.find_one({"_id": uid}))

    async def get_user(self, uid: int) -> dict | None:
        return await self.col.find_one({"_id": uid})

    async def update_user(self, uid: int, data: dict) -> None:
        await self.col.update_one({"_id": uid}, {"$set": data}, upsert=True)

    async def total_users_count(self) -> int:
        return await self.col.count_documents({})

    # ─── Ban ────────────────────────────────────────────────────────
    async def ban_user(self, uid: int, reason: str = "") -> None:
        await self.col.update_one(
            {"_id": uid},
            {"$set": {"is_banned": True, "ban_reason": reason}},
            upsert=True
        )

    async def unban_user(self, uid: int) -> None:
        await self.col.update_one(
            {"_id": uid},
            {"$set": {"is_banned": False, "ban_reason": ""}}
        )

    async def is_banned(self, uid: int) -> bool:
        u = await self.col.find_one({"_id": uid})
        return bool(u and u.get("is_banned", False))

    # ─── Admins ─────────────────────────────────────────────────────
    async def add_admin(self, uid: int) -> None:
        await self.admins_col.update_one({"_id": uid}, {"$set": {"_id": uid}}, upsert=True)

    async def del_admin(self, uid: int) -> None:
        await self.admins_col.delete_one({"_id": uid})

    async def get_admins(self) -> list[int]:
        return [doc["_id"] async for doc in self.admins_col.find({})]

    async def is_admin(self, uid: int) -> bool:
        return bool(await self.admins_col.find_one({"_id": uid}))

    # ─── Format template ────────────────────────────────────────────
    async def set_format_template(self, uid: int, template: str) -> None:
        await self.update_user(uid, {"format_template": template})

    async def get_format_template(self, uid: int) -> str | None:
        u = await self.col.find_one({"_id": uid})
        return u.get("format_template") if u else None

    async def del_format_template(self, uid: int) -> None:
        await self.update_user(uid, {"format_template": None})

    # ─── Rename source ──────────────────────────────────────────────
    async def set_rename_source(self, uid: int, src: str) -> None:
        await self.update_user(uid, {"rename_source": src})

    async def get_rename_source(self, uid: int) -> str:
        u = await self.col.find_one({"_id": uid})
        return (u or {}).get("rename_source", "filename")

    # ─── Media preference ───────────────────────────────────────────
    async def set_media_preference(self, uid: int, pref: str) -> None:
        await self.update_user(uid, {"media_preference": pref})

    async def get_media_preference(self, uid: int) -> str:
        u = await self.col.find_one({"_id": uid})
        return (u or {}).get("media_preference", "document")

    # ─── Thumbnail ──────────────────────────────────────────────────
    async def set_thumbnail(self, uid: int, file_id: str) -> None:
        await self.update_user(uid, {"file_id": file_id})

    async def get_thumbnail(self, uid: int) -> str | None:
        u = await self.col.find_one({"_id": uid})
        return u.get("file_id") if u else None

    async def del_thumbnail(self, uid: int) -> None:
        await self.update_user(uid, {"file_id": None})

    # ─── Caption ────────────────────────────────────────────────────
    async def set_caption(self, uid: int, caption: str) -> None:
        await self.update_user(uid, {"caption": caption})

    async def get_caption(self, uid: int) -> str | None:
        u = await self.col.find_one({"_id": uid})
        return u.get("caption") if u else None

    async def del_caption(self, uid: int) -> None:
        await self.update_user(uid, {"caption": None})

    # ─── Metadata ───────────────────────────────────────────────────
    async def set_metadata_mode(self, uid: int, mode: bool) -> None:
        await self.update_user(uid, {"metadata_mode": mode})

    async def get_metadata_mode(self, uid: int) -> bool:
        u = await self.col.find_one({"_id": uid})
        return (u or {}).get("metadata_mode", True)

    async def set_metadata_field(self, uid: int, field: str, value: str) -> None:
        await self.col.update_one(
            {"_id": uid},
            {"$set": {f"metadata.{field}": value}},
            upsert=True
        )

    async def get_metadata_field(self, uid: int, field: str) -> str | None:
        u = await self.col.find_one({"_id": uid})
        if not u:
            return None
        return u.get("metadata", {}).get(field)

    async def get_all_metadata(self, uid: int) -> dict:
        u = await self.col.find_one({"_id": uid})
        return (u or {}).get("metadata", {})

    async def clear_all_metadata(self, uid: int) -> None:
        empty = {k: None for k in ["title","author","artist","audio","subtitle","video","encoded_by","custom_tag","comment"]}
        await self.update_user(uid, {"metadata": empty})

    # Convenience getters used in file_rename
    async def get_title(self, uid: int) -> str:
        return (await self.get_metadata_field(uid, "title")) or ""
    async def get_author(self, uid: int) -> str:
        return (await self.get_metadata_field(uid, "author")) or ""
    async def get_artist(self, uid: int) -> str:
        return (await self.get_metadata_field(uid, "artist")) or ""
    async def get_audio(self, uid: int) -> str:
        return (await self.get_metadata_field(uid, "audio")) or ""
    async def get_subtitle(self, uid: int) -> str:
        return (await self.get_metadata_field(uid, "subtitle")) or ""
    async def get_video(self, uid: int) -> str:
        return (await self.get_metadata_field(uid, "video")) or ""
    async def get_encoded_by(self, uid: int) -> str:
        return (await self.get_metadata_field(uid, "encoded_by")) or ""
    async def get_custom_tag(self, uid: int) -> str:
        return (await self.get_metadata_field(uid, "custom_tag")) or ""
    async def get_comment(self, uid: int) -> str:
        return (await self.get_metadata_field(uid, "comment")) or ""

    # ─── Rename count / leaderboard ─────────────────────────────────
    async def increment_rename(self, uid: int, name: str, username: str | None) -> None:
        now = datetime.utcnow()
        await self.col.update_one(
            {"_id": uid},
            {"$inc": {"rename_count": 1}, "$set": {"first_name": name, "username": username, "last_seen": now.isoformat()}},
            upsert=True
        )
        await self.rename_log.insert_one({"user_id": uid, "ts": now})

    async def get_leaderboard(self, period: str) -> list[dict]:
        now = datetime.utcnow()
        if period == "today":
            start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        elif period == "week":
            start = now - timedelta(days=now.weekday())
            start = start.replace(hour=0, minute=0, second=0, microsecond=0)
        elif period == "month":
            start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        elif period == "year":
            start = now.replace(month=1, day=1, hour=0, minute=0, second=0, microsecond=0)
        else:  # lifetime
            start = datetime(2000, 1, 1)

        pipeline = [
            {"$match": {"ts": {"$gte": start}}},
            {"$group": {"_id": "$user_id", "count": {"$sum": 1}}},
            {"$sort": {"count": -1}},
            {"$limit": 10},
        ]
        results = []
        async for doc in self.rename_log.aggregate(pipeline):
            u = await self.col.find_one({"_id": doc["_id"]})
            name = u.get("first_name", "Unknown") if u else "Unknown"
            results.append({"user_id": doc["_id"], "name": name, "count": doc["count"]})
        return results

    async def get_user_rank(self, uid: int, period: str) -> int | None:
        board = await self.get_leaderboard(period)
        for i, entry in enumerate(board, 1):
            if entry["user_id"] == uid:
                return i
        return None

    # ─── FSUB toggle ────────────────────────────────────────────────
    async def get_fsub_enabled(self) -> bool:
        doc = await self.fsub_col.find_one({"_id": "settings"})
        return (doc or {}).get("enabled", True)

    async def set_fsub_enabled(self, val: bool) -> None:
        await self.fsub_col.update_one(
            {"_id": "settings"}, {"$set": {"enabled": val}}, upsert=True
        )

    # ─── Shutdown mode ──────────────────────────────────────────────
    async def get_shutdown(self) -> bool:
        doc = await self.shutdown_col.find_one({"_id": "settings"})
        return (doc or {}).get("active", False)

    async def set_shutdown(self, val: bool) -> None:
        await self.shutdown_col.update_one(
            {"_id": "settings"}, {"$set": {"active": val}}, upsert=True
        )

db = Database(Config.DB_URL, Config.DB_NAME)
