"""
plugins/file_rename.py — Complete rename engine.

Queue behaviour:
  • Every file sent → immediately gets its own "N file added to queue" message.
  • First 3 files: their queue message is immediately edited to download bar.
  • Files 4+: keep "added to queue N" until a slot frees.
  • When slot frees → that file's OWN message is edited to download bar.
  • Single summary message updated throughout; "All Completed" at the end.

Windows file-lock fix:
  • Pyrogram downloads to a .temp file then calls shutil.move().
  • On Windows, if the destination already exists, shutil.move → os.rename
    fails with WinError 32 (file in use). We pre-delete any stale destination
    before downloading, and wrap the download in a retry loop with a short
    delay so a previous task's cleanup has time to finish.

Metadata {filename} fix:
  • Every metadata field is passed through _resolve(value, new_name) which
    replaces {filename} with the actual renamed filename before calling ffmpeg.
"""

import os
import re
import sys
import time
import asyncio
import shutil
import logging
from PIL import Image

from pyrogram import Client, filters
from pyrogram.types import Message

from config import Config
from helper.database import db
from helper.utils import (
    progress_for_pyrogram,
    humanbytes,
    convert,
    detect_duration,
    apply_format_template,
    apply_caption_template,
)
from plugins.start import check_ban, check_fsub, check_shutdown

logger = logging.getLogger(__name__)

# ══════════════════════════════════════════════════════════════════════════════
#  CONSTANTS
# ══════════════════════════════════════════════════════════════════════════════
CONCURRENT    = 3     # simultaneous files per user
_DEDUP_WINDOW = 10    # seconds — ignore re-delivered file_ids
_IS_WINDOWS   = sys.platform == "win32"


# ══════════════════════════════════════════════════════════════════════════════
#  PER-USER BATCH STATE  (all keyed by uid)
# ══════════════════════════════════════════════════════════════════════════════
_lock_map:    dict[int, asyncio.Lock]   = {}   # serialises slot management
_queue_map:   dict[int, asyncio.Queue]  = {}   # pending (message, prog_msg) pairs
_active_map:  dict[int, int]            = {}   # files currently processing
_total_map:   dict[int, int]            = {}   # files received this batch
_done_map:    dict[int, int]            = {}   # files fully renamed
_start_map:   dict[int, float]          = {}   # batch start timestamp
_summary_map: dict[int, Message]        = {}   # the "Rename Started" message
_cancel_map:  dict[int, bool]           = {}   # cancel flag

# Dedup: file_id → last processed timestamp
_dedup: dict[str, float] = {}


# ── Public helpers used by queue_cancel.py ───────────────────────────────────
def get_user_stats(uid: int) -> dict:
    q = _queue_map.get(uid)
    return {
        "processing": _active_map.get(uid, 0),
        "waiting":    q.qsize() if q else 0,
        "total":      _active_map.get(uid, 0) + (q.qsize() if q else 0),
    }


def get_global_stats() -> dict:
    return {
        "queued": sum(q.qsize() for q in _queue_map.values()),
        "active": sum(_active_map.values()),
        "users":  sum(1 for v in _active_map.values() if v > 0),
    }


def cancel_user(uid: int) -> None:
    """Called by /cancel — drain queue and set flag."""
    _cancel_map[uid] = True
    q = _queue_map.get(uid)
    if q:
        while not q.empty():
            try:
                q.get_nowait()
            except asyncio.QueueEmpty:
                break


# ══════════════════════════════════════════════════════════════════════════════
#  INTERNAL HELPERS
# ══════════════════════════════════════════════════════════════════════════════
def _get_lock(uid: int) -> asyncio.Lock:
    if uid not in _lock_map:
        _lock_map[uid] = asyncio.Lock()
    return _lock_map[uid]


def _safe_del(*paths) -> None:
    """Delete files silently, never raises."""
    for p in paths:
        if p and os.path.exists(p):
            try:
                os.remove(p)
            except Exception as e:
                logger.debug(f"safe_del {p}: {e}")


def _mkdirs(*paths) -> None:
    for p in paths:
        if p:
            os.makedirs(os.path.dirname(p), exist_ok=True)


def _resolve(value: str | None, new_name: str) -> str:
    """Replace {filename} placeholder in a metadata field with the real name."""
    if not value:
        return ""
    return value.replace("{filename}", new_name)


def _is_batch_alive(uid: int) -> bool:
    return uid in _lock_map


def _init_user(uid: int) -> None:
    """Create fresh batch state. Call BEFORE acquiring the lock."""
    _lock_map[uid]    = asyncio.Lock()
    _queue_map[uid]   = asyncio.Queue()
    _active_map[uid]  = 0
    _total_map[uid]   = 0
    _done_map[uid]    = 0
    _start_map[uid]   = time.time()
    _cancel_map[uid]  = False
    _summary_map[uid] = None


def _cleanup_user(uid: int) -> None:
    """Tear down all batch state once the batch is fully complete."""
    for d in (_lock_map, _queue_map, _active_map, _total_map,
              _done_map, _start_map, _summary_map, _cancel_map):
        d.pop(uid, None)


# ══════════════════════════════════════════════════════════════════════════════
#  WINDOWS FILE-LOCK SAFE DOWNLOAD
# ══════════════════════════════════════════════════════════════════════════════
async def _safe_download(
    client,
    message: Message,
    file_path: str,
    prog_hdr: str,
    prog_msg: Message,
    uid: int = 0,
) -> str:
    """
    Download with:
      1. Windows file-lock safety  (pre-delete stale .temp, 3 retries).
      2. Cancel support  — wraps download_media in asyncio.wait_for polling
         the cancel flag every second so /cancel works mid-download.
    Returns local path on success, raises on failure / cancellation.
    """
    _safe_del(file_path, file_path + ".temp", file_path + ".part")

    for attempt in range(1, 4):
        # Check cancel before each attempt
        if uid and _cancel_map.get(uid):
            raise asyncio.CancelledError("Cancelled by user")

        try:
            t0 = time.time()

            # Run download_media in a Task so we can cancel it
            dl_task = asyncio.ensure_future(
                client.download_media(
                    message,
                    file_name=file_path,
                    progress=progress_for_pyrogram,
                    progress_args=(f"{prog_hdr}\n➥ Dᴏᴡɴʟᴏᴀᴅɪɴɢ...", prog_msg, t0),
                )
            )

            # Poll cancel flag every 1 second while download runs
            while not dl_task.done():
                if uid and _cancel_map.get(uid):
                    dl_task.cancel()
                    try:
                        await dl_task
                    except (asyncio.CancelledError, Exception):
                        pass
                    _safe_del(file_path, file_path + ".temp", file_path + ".part")
                    raise asyncio.CancelledError("Cancelled by user during download")
                await asyncio.sleep(1)

            result = dl_task.result()
            if result and os.path.exists(result):
                return result
            raise RuntimeError("Download returned empty path")

        except asyncio.CancelledError:
            raise   # propagate cancel

        except PermissionError as e:
            if attempt < 3:
                logger.warning(
                    f"Download PermissionError attempt {attempt}/3 "
                    f"file={os.path.basename(file_path)}: {e} — retrying in 2s"
                )
                _safe_del(file_path + ".temp")
                await asyncio.sleep(2)
            else:
                raise

        except Exception:
            raise

    raise RuntimeError("Download failed after 3 attempts")


# ══════════════════════════════════════════════════════════════════════════════
#  THUMBNAIL
# ══════════════════════════════════════════════════════════════════════════════
async def _get_thumbnail(client, uid: int, message: Message) -> str | None:
    fid = await db.get_thumbnail(uid)
    if not fid and message.video and message.video.thumbs:
        fid = message.video.thumbs[0].file_id
    if not fid:
        return None
    try:
        path = await client.download_media(fid)
        if path:
            img = Image.open(path).convert("RGB")
            img.save(path, "JPEG")
        return path
    except Exception as e:
        logger.debug(f"Thumbnail failed uid={uid}: {e}")
        return None


# ══════════════════════════════════════════════════════════════════════════════
#  FFMPEG HELPERS
# ══════════════════════════════════════════════════════════════════════════════
async def _ffmpeg_run(cmd: list, uid: int, timeout: int = 180) -> bool:
    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        _, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
        if proc.returncode != 0:
            logger.warning(
                f"ffmpeg non-zero uid={uid}: {stderr.decode(errors='replace')[:300]}"
            )
            return False
        return True
    except asyncio.TimeoutError:
        logger.warning(f"ffmpeg timeout uid={uid}")
        return False
    except Exception as e:
        logger.warning(f"ffmpeg exception uid={uid}: {e}")
        return False


async def _build_meta_cmd(
    ffmpeg: str,
    input_path: str,
    output_path: str,
    uid: int,
    new_name: str,
    to_mkv: bool = False,
) -> list:
    """
    Build ffmpeg stream-copy command with all metadata fields.
    {filename} in any field is resolved to new_name before being passed.
    """
    (title, artist, author, vid, aud, sub,
     enc, ctag, cmt) = await asyncio.gather(
        db.get_title(uid),      db.get_artist(uid),   db.get_author(uid),
        db.get_video(uid),      db.get_audio(uid),    db.get_subtitle(uid),
        db.get_encoded_by(uid), db.get_custom_tag(uid), db.get_comment(uid),
    )

    r = lambda v: _resolve(v, new_name)     # noqa: E731

    cmd = [
        ffmpeg, "-hide_banner", "-y", "-i", input_path,
        "-metadata",     f"title={r(title)}",
        "-metadata",     f"artist={r(artist)}",
        "-metadata",     f"author={r(author)}",
        "-metadata",     f"encoded_by={r(enc)}",
        "-metadata",     f"comment={r(cmt)}",
        "-metadata:s:v", f"title={r(vid)}",
        "-metadata:s:a", f"title={r(aud)}",
        "-metadata:s:s", f"title={r(sub)}",
        "-map", "0", "-c", "copy",
    ]
    if to_mkv:
        cmd += ["-f", "matroska"]
    cmd += ["-loglevel", "error", output_path]
    return cmd


async def _apply_ffmpeg(
    input_path: str,
    output_path: str,
    uid: int,
    new_name: str,
    to_mkv: bool = False,
) -> str:
    """
    Run ffmpeg. Returns output_path on success, input_path on failure.
    On Windows, ensure output_path doesn't already exist to avoid lock issues.
    """
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        logger.debug("ffmpeg not found, skipping metadata injection")
        return input_path

    # Pre-delete output to avoid WinError 32
    _safe_del(output_path)

    cmd = await _build_meta_cmd(ffmpeg, input_path, output_path, uid, new_name, to_mkv)
    ok  = await _ffmpeg_run(cmd, uid, timeout=300 if to_mkv else 180)
    return output_path if (ok and os.path.exists(output_path)) else input_path


# ══════════════════════════════════════════════════════════════════════════════
#  DUMP CHANNEL  (fire-and-forget)
# ══════════════════════════════════════════════════════════════════════════════
async def _send_dump(
    client, uid: int,
    orig_msg: Message, sent: Message,
    orig_name: str, new_name: str,
    file_size: int, ph: str | None, upload_as: str,
) -> None:
    try:
        uname = f"@{orig_msg.from_user.username}" if orig_msg.from_user.username else "N/A"
        cap = (
            "<b>» Usᴇʀ Dᴇᴛᴀɪʟs «</b>\n"
            f"ID       : <code>{uid}</code>\n"
            f"Nᴀᴍᴇ    : {orig_msg.from_user.first_name}\n"
            f"Usᴇʀɴᴀᴍᴇ: {uname}\n"
            f"Oʀɪɢɪɴᴀʟ: <code>{orig_name}</code>\n"
            f"Rᴇɴᴀᴍᴇᴅ : <code>{new_name}</code>\n"
            f"Sɪᴢᴇ    : {humanbytes(file_size)}"
        )
        kw = dict(chat_id=Config.DUMP_CHANNEL, caption=cap, thumb=ph)
        if upload_as == "video" and sent.video:
            await client.send_video(video=sent.video.file_id, **kw)
        elif upload_as == "audio" and sent.audio:
            await client.send_audio(audio=sent.audio.file_id, **kw)
        elif sent.document:
            await client.send_document(document=sent.document.file_id, **kw)
    except Exception as e:
        logger.debug(f"Dump error uid={uid}: {e}")


# ══════════════════════════════════════════════════════════════════════════════
#  SUMMARY MESSAGE
# ══════════════════════════════════════════════════════════════════════════════
async def _edit_summary(uid: int, done: bool = False) -> None:
    msg = _summary_map.get(uid)
    if not msg:
        return

    elapsed = time.time() - _start_map.get(uid, time.time())
    h, rem  = divmod(int(elapsed), 3600)
    m, s    = divmod(rem, 60)
    t_str   = f"{h}h {m}m {s}s" if h else f"{m}m {s}s"

    total   = _total_map.get(uid, 0)
    renamed = _done_map.get(uid, 0)
    active  = _active_map.get(uid, 0)
    avg     = (elapsed / renamed) if renamed > 0 else 0
    am, as_ = divmod(int(avg), 60)
    avg_str = f"{am}m {as_}s"

    if done:
        text = (
            "≡ <b>Aʟʟ Rᴇɴᴀᴍᴇ Cᴏᴍᴘʟᴇᴛᴇᴅ...</b>\n"
            f"◍ ᴛᴏᴛᴀʟ Fɪʟᴇs   : <code>« {total} »</code>\n"
            f"◍ Fɪʟᴇ Rᴇɴᴀᴍᴇᴅ  : <code>« {renamed} »</code>\n"
            f"◍ ᴛᴏᴛᴀʟ ᴛɪᴍᴇ    : <code>« {t_str} »</code>\n"
            "<i>(Aᴜᴛᴏ-ᴅᴇʟᴇᴛᴇ: Fɪʟᴇs ᴡɪʟʟ ʙᴇ ʀᴇᴍᴏᴠᴇᴅ ɪɴ 24h 0m 0s)</i>"
        )
    else:
        text = (
            "≡ <b>Rᴇɴᴀᴍᴇ Sᴛᴀʀᴛᴇᴅ...</b>\n"
            f"◍ ᴛᴏᴛᴀʟ Fɪʟᴇs       : <code>« {total} »</code>\n"
            f"◍ ᴛᴏᴛᴀʟ ᴛɪᴍᴇ        : <code>« {t_str} »</code>\n"
            f"◍ ᴀᴠᴇʀᴀɢᴇ ᴘᴇʀ ᴛᴀsᴋ  : <code>« {avg_str} »</code>\n"
            f"◍ Pʀᴏᴄᴇssɪɴɢ Fɪʟᴇs  : <code>« {active} »</code>\n"
            f"◍ Fɪʟᴇs Rᴇɴᴀᴍᴇᴅ    : <code>« {renamed} »</code>"
        )
    try:
        await msg.edit(text)
    except Exception:
        pass


# ══════════════════════════════════════════════════════════════════════════════
#  SLOT MANAGEMENT
# ══════════════════════════════════════════════════════════════════════════════
async def _on_slot_freed(client, uid: int) -> None:
    """
    Must be called INSIDE _get_lock(uid).
    Decrements active count; pulls next queued file or signals batch done.
    """
    _active_map[uid] = max(0, _active_map.get(uid, 1) - 1)
    q = _queue_map.get(uid)

    if q and not q.empty() and not _cancel_map.get(uid):
        try:
            next_msg, next_prog = q.get_nowait()
            _active_map[uid] += 1
            asyncio.create_task(_process_one(client, uid, next_msg, next_prog))
            await _edit_summary(uid)
            return
        except asyncio.QueueEmpty:
            pass

    if _active_map.get(uid, 0) == 0:
        await _edit_summary(uid, done=True)
        _cleanup_user(uid)
    else:
        await _edit_summary(uid)


# ══════════════════════════════════════════════════════════════════════════════
#  CORE: PROCESS ONE FILE
# ══════════════════════════════════════════════════════════════════════════════
async def _process_one(
    client,
    uid: int,
    message: Message,
    prog_msg: Message,
) -> None:
    """
    Full pipeline for a single file. prog_msg is the "N file added to queue"
    message that we edit in-place throughout download → metadata → upload.
    On finish (success/fail) calls _on_slot_freed() to chain the next file.
    """

    # ── File info ──────────────────────────────────────────────────────────────
    file_obj  = message.document or message.video or message.audio
    if not file_obj:
        async with _get_lock(uid):
            await _on_slot_freed(client, uid)
        return

    file_id   = file_obj.file_id
    orig_name = getattr(file_obj, "file_name", None) or "unnamed"
    file_size = getattr(file_obj, "file_size", 0) or 0
    media_src = (
        "audio"    if message.audio else
        "video"    if message.video else
        "document"
    )

    # ── Dedup ─────────────────────────────────────────────────────────────────
    now = time.time()
    if now - _dedup.get(file_id, 0) < _DEDUP_WINDOW:
        logger.debug(f"Skipping duplicate file_id={file_id} uid={uid}")
        async with _get_lock(uid):
            await _on_slot_freed(client, uid)
        return
    _dedup[file_id] = now

    # ── Extension ──────────────────────────────────────────────────────────────
    _, ext    = os.path.splitext(orig_name)
    ext       = ext.lower() if ext else ".mkv"
    is_mp4    = ext in (".mp4", ".m4v")
    final_ext = ".mkv" if is_mp4 else ext

    # ── Rename source ──────────────────────────────────────────────────────────
    src_pref    = await db.get_rename_source(uid)
    source_text = (
        (message.caption or orig_name) if src_pref == "caption" else orig_name
    )

    # ── Format template ────────────────────────────────────────────────────────
    template = await db.get_format_template(uid)
    if not template:
        try:
            await prog_msg.edit(
                "<blockquote>ⓘ Pʟᴇᴀsᴇ sᴇᴛ ᴀ ʀᴇɴᴀᴍᴇ ꜰᴏʀᴍᴀᴛ ᴜsɪɴɢ "
                "<code>/format</code></blockquote>"
            )
        except Exception:
            pass
        async with _get_lock(uid):
            await _on_slot_freed(client, uid)
        return

    base     = apply_format_template(template, source_text)
    if not base:
        base = os.path.splitext(orig_name)[0]
    new_name = f"{base}{final_ext}"

    # ── Paths ──────────────────────────────────────────────────────────────────
    u       = str(uid)
    dl_path = os.path.join("downloads", u, new_name)
    md_path = os.path.join("metadata",  u, new_name)
    _mkdirs(dl_path, md_path)

    # orig_hdr → shown during download (original filename user sent)
    # new_hdr  → shown during upload   (the renamed output name)
    orig_hdr = f"❐ <code>{orig_name}</code>"
    new_hdr  = f"❐ <code>{new_name}</code>"

    dl_result  = None
    final_path = None
    ph_path    = None
    keep_prog  = False    # True → error message, don't delete prog_msg

    try:
        if _cancel_map.get(uid):
            return

        # ── DOWNLOAD ────────────────────────────────────────────────────────────
        # Show ORIGINAL filename during download so user knows what's being fetched
        await prog_msg.edit(f"{orig_hdr}\n➥ Dᴏᴡɴʟᴏᴀᴅɪɴɢ...")

        dl_result = await _safe_download(client, message, dl_path, orig_hdr, prog_msg, uid)

        if _cancel_map.get(uid):
            return

        # ── METADATA / MKV CONVERSION ───────────────────────────────────────────
        meta_on = await db.get_metadata_mode(uid)

        if is_mp4:
            await prog_msg.edit(f"{new_hdr}\n➥ Cᴏɴᴠᴇʀᴛɪɴɢ MP4 → MKV + Mᴇᴛᴀᴅᴀᴛᴀ...")
            final_path = await _apply_ffmpeg(
                dl_result, md_path, uid, new_name, to_mkv=True
            )
        elif meta_on:
            await prog_msg.edit(f"{new_hdr}\n➥ Aᴅᴅɪɴɢ Mᴇᴛᴀᴅᴀᴛᴀ...")
            final_path = await _apply_ffmpeg(
                dl_result, md_path, uid, new_name, to_mkv=False
            )
        else:
            final_path = dl_result

        # ── THUMBNAIL ──────────────────────────────────────────────────────────
        ph_path = await _get_thumbnail(client, uid, message)

        # ── DURATION ───────────────────────────────────────────────────────────
        duration = 0.0
        if media_src in ("video", "audio"):
            duration = await detect_duration(final_path)

        # ── CAPTION ────────────────────────────────────────────────────────────
        cap_tpl = await db.get_caption(uid)
        caption = (
            apply_caption_template(
                cap_tpl, new_name, source_text, file_size, duration
            ) if cap_tpl
            else f"<b>{new_name}</b>"
        )

        # ── MEDIA PREFERENCE ────────────────────────────────────────────────────
        pref = await db.get_media_preference(uid)
        # Audio files always upload as audio regardless of user pref
        upload_as = media_src if message.audio else pref

        # ── UPLOAD ─────────────────────────────────────────────────────────────
        await prog_msg.edit(f"{new_hdr}\n➥ Uᴘʟᴏᴀᴅɪɴɢ...")
        t1 = time.time()
        kw = dict(
            chat_id=message.chat.id,
            caption=caption,
            thumb=ph_path,
            progress=progress_for_pyrogram,
            progress_args=(f"{new_hdr}\n➥ Uᴘʟᴏᴀᴅɪɴɢ...", prog_msg, t1),
        )

        sent = None
        if upload_as == "video":
            sent = await client.send_video(
                video=final_path,
                duration=int(duration) if duration else 0,
                supports_streaming=True,
                **kw,
            )
        elif upload_as == "audio":
            sent = await client.send_audio(
                audio=final_path,
                duration=int(duration) if duration else 0,
                **kw,
            )
        else:
            sent = await client.send_document(document=final_path, **kw)

        # ── DUMP CHANNEL ────────────────────────────────────────────────────────
        if Config.DUMP_CHANNEL and sent:
            asyncio.create_task(
                _send_dump(client, uid, message, sent,
                           orig_name, new_name, file_size, ph_path, upload_as)
            )

        # ── UPDATE DB STATS ─────────────────────────────────────────────────────
        await db.increment_rename(
            uid,
            message.from_user.first_name,
            message.from_user.username,
        )
        async with _get_lock(uid):
            _done_map[uid] = _done_map.get(uid, 0) + 1

    except asyncio.CancelledError:
        pass

    except Exception as e:
        logger.error(
            f"Rename error uid={uid} file={orig_name}: {e}", exc_info=True
        )
        try:
            await prog_msg.edit(
                f"{orig_hdr}\n"
                f"❌ <b>Eʀʀᴏʀ</b>: <code>{str(e)[:200]}</code>"
            )
            keep_prog = True
        except Exception:
            pass

    finally:
        # Delete progress message unless it's an error we want to show
        if not keep_prog:
            try:
                await prog_msg.delete()
            except Exception:
                pass

        # Clean up all temp files — always, even on error
        # On Windows we must ensure the files are not open before deleting.
        # Small sleep gives the OS time to release any handles.
        if _IS_WINDOWS:
            await asyncio.sleep(0.3)

        paths_to_del = set(filter(None, [dl_path, md_path]))
        if final_path and final_path not in paths_to_del:
            paths_to_del.add(final_path)
        _safe_del(*paths_to_del)
        if ph_path:
            _safe_del(ph_path)

        # Release slot and pull next queued file
        async with _get_lock(uid):
            await _on_slot_freed(client, uid)


# ══════════════════════════════════════════════════════════════════════════════
#  MAIN HANDLER
# ══════════════════════════════════════════════════════════════════════════════
@Client.on_message(
    filters.private & (filters.document | filters.video | filters.audio)
)
@check_shutdown
@check_ban
@check_fsub
async def auto_rename_files(client, message: Message) -> None:
    uid = message.from_user.id

    # ── Guard: format must be set ────────────────────────────────────────────
    if not await db.get_format_template(uid):
        await message.reply_text(
            "<blockquote>ⓘ Pʟᴇᴀsᴇ sᴇᴛ ᴀ ʀᴇɴᴀᴍᴇ ꜰᴏʀᴍᴀᴛ ꜰɪʀsᴛ ᴜsɪɴɢ "
            "<code>/format</code></blockquote>"
        )
        return

    # ── Init batch state on very first file ────────────────────────────────
    if not _is_batch_alive(uid):
        _init_user(uid)

    async with _get_lock(uid):
        _total_map[uid] = _total_map.get(uid, 0) + 1
        file_num        = _total_map[uid]

        # Create the summary message exactly ONCE per batch (on file #1)
        if file_num == 1:
            _start_map[uid]   = time.time()
            _summary_map[uid] = await message.reply_text(
                "≡ <b>Rᴇɴᴀᴍᴇ Sᴛᴀʀᴛᴇᴅ...</b>\n"
                "◍ ᴛᴏᴛᴀʟ Fɪʟᴇs       : <code>« 1 »</code>\n"
                "◍ Pʀᴏᴄᴇssɪɴɢ Fɪʟᴇs  : <code>« 0 »</code>\n"
                "◍ Fɪʟᴇs Rᴇɴᴀᴍᴇᴅ    : <code>« 0 »</code>"
            )

        # Every file gets its own queue message IMMEDIATELY
        prog_msg = await message.reply_text(
            f"<blockquote>{file_num} ꜰɪʟᴇ ᴀᴅᴅᴇᴅ ᴛᴏ ǫᴜᴇᴜᴇ....</blockquote>"
        )

        # Free slot → start now (prog_msg gets edited to download bar)
        if _active_map.get(uid, 0) < CONCURRENT:
            _active_map[uid] = _active_map.get(uid, 0) + 1
            asyncio.create_task(_process_one(client, uid, message, prog_msg))
            await _edit_summary(uid)

        # No free slot → park in queue; _on_slot_freed will start it
        else:
            await _queue_map[uid].put((message, prog_msg))
            await _edit_summary(uid)