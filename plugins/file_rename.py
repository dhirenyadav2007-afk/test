"""
plugins/file_rename.py  —  Production-grade concurrent rename pipeline.

ARCHITECTURE
────────────────────────────────────────────────────────────────────────────
True pipeline concurrency using asyncio.Semaphore per stage:

  _DL_SEM(3)     — up to 3 downloads active simultaneously
  _FFMPEG_SEM(2) — up to 2 ffmpeg processes simultaneously  
  _UL_SEM(3)     — up to 3 uploads simultaneously

Each file runs its own independent coroutine (_process_one) and moves
through every stage immediately after the previous one completes:

  File A:  ▓▓▓▓▓▓ DOWNLOAD ▓▓▓▓▓▓  ░░░ META ░░░  ▒▒▒▒ UPLOAD ▒▒▒▒
  File B:    ▓▓▓▓▓▓ DOWNLOAD ▓▓▓▓▓▓  ░░░ META ░░░  ▒▒▒▒ UPLOAD ▒▒▒▒
  File C:      ▓▓▓▓▓▓ DOWNLOAD ▓▓▓▓▓▓  ░░░ META ░░░  ▒▒▒▒ UPLOAD ▒▒▒▒
  File D:               (waiting for DL slot)  ▓▓▓▓▓▓ DOWNLOAD ...

  → While A is uploading + B is adding metadata + C is downloading,
    D is waiting for one of the 3 DL slots to free up.
  → The moment A finishes uploading, the NEXT queued file for that user
    gets its slot and starts immediately.

WORKER SYSTEM
────────────────────────────────────────────────────────────────────────────
A global asyncio.Queue receives ALL jobs from ALL users.
NUM_WORKERS background coroutines run permanently, each pulling from the
queue and running _process_one. Workers never stop — they loop forever.

Per-user state is tracked separately for /cancel, /queue, summary messages.

FLOODWAIT + RETRY
────────────────────────────────────────────────────────────────────────────
Every Telegram API call (download, upload) is wrapped with FloodWait
handling: catch FloodWait, sleep for the required time + 5 s buffer,
retry up to MAX_RETRIES times before giving up.

CANCEL
────────────────────────────────────────────────────────────────────────────
cancel_user(uid) → sets _cancel_map[uid]=True + drains per-user queue +
cancels all running asyncio.Task objects for that user.
Each stage checks the cancel flag before starting.

WINDOWS WINAPI ERROR 32
────────────────────────────────────────────────────────────────────────────
Pre-delete stale .temp/.part files, 3 retries with 2 s backoff,
300 ms sleep in finally before deleting on Windows.
"""

import os
import sys
import time
import asyncio
import shutil
import logging
from concurrent.futures import ThreadPoolExecutor
from PIL import Image

from pyrogram import Client, filters
from pyrogram.types import Message
from pyrogram.errors import FloodWait, RPCError

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
#  GLOBAL CONCURRENCY CONTROLS
# ══════════════════════════════════════════════════════════════════════════════
MAX_CONCURRENT_DOWNLOADS = 3   # simultaneous downloads (all users combined)
MAX_CONCURRENT_FFMPEG    = 2   # simultaneous ffmpeg processes
MAX_CONCURRENT_UPLOADS   = 3   # simultaneous uploads
NUM_WORKERS              = 6   # permanent background workers
MAX_RETRIES              = 3   # retries for FloodWait / network errors
CONCURRENT_PER_USER      = 3   # max in-flight files per user

_DL_SEM     = asyncio.Semaphore(MAX_CONCURRENT_DOWNLOADS)
_FFMPEG_SEM = asyncio.Semaphore(MAX_CONCURRENT_FFMPEG)
_UL_SEM     = asyncio.Semaphore(MAX_CONCURRENT_UPLOADS)

# Thread pool for any blocking CPU work (PIL image resize, etc.)
_THREAD_POOL = ThreadPoolExecutor(max_workers=4)

_IS_WINDOWS   = sys.platform == "win32"
_DEDUP_WINDOW = 10   # seconds — ignore re-delivered file_ids


# ══════════════════════════════════════════════════════════════════════════════
#  GLOBAL JOB QUEUE + WORKERS
#  All files from all users go into one queue.
#  NUM_WORKERS coroutines drain it permanently.
# ══════════════════════════════════════════════════════════════════════════════
_GLOBAL_QUEUE: asyncio.Queue = asyncio.Queue()
_worker_tasks: list[asyncio.Task] = []

# Job format: (client, uid, message, prog_msg)
Job = tuple  # type alias for readability


async def _worker_loop() -> None:
    """
    Permanent worker coroutine.  Pulls jobs from _GLOBAL_QUEUE and processes
    them one by one.  Never exits — runs for the lifetime of the bot.
    """
    while True:
        try:
            client, uid, message, prog_msg = await _GLOBAL_QUEUE.get()
            try:
                await _process_one(client, uid, message, prog_msg)
            except Exception as e:
                logger.error(f"Worker unhandled exception uid={uid}: {e}", exc_info=True)
            finally:
                _GLOBAL_QUEUE.task_done()
        except asyncio.CancelledError:
            break
        except Exception as e:
            logger.error(f"Worker loop error: {e}")
            await asyncio.sleep(1)   # brief pause before retrying


def start_workers(client_ref=None) -> None:
    """
    Spawn NUM_WORKERS background worker tasks.
    Called once from bot.py after the client connects.
    Safe to call multiple times — skips if already running.
    """
    alive = [t for t in _worker_tasks if not t.done()]
    if len(alive) >= NUM_WORKERS:
        return
    for _ in range(NUM_WORKERS - len(alive)):
        t = asyncio.create_task(_worker_loop())
        _worker_tasks.append(t)
    logger.info(f"✓ {NUM_WORKERS} rename workers running")


# ══════════════════════════════════════════════════════════════════════════════
#  PER-USER BATCH STATE
# ══════════════════════════════════════════════════════════════════════════════
_lock_map:      dict[int, asyncio.Lock]  = {}
_active_map:    dict[int, int]           = {}   # in-flight files this batch
_total_map:     dict[int, int]           = {}   # total files received
_done_map:      dict[int, int]           = {}   # fully renamed
_start_map:     dict[int, float]         = {}   # batch start time
_summary_map:   dict[int, Message]       = {}   # summary message
_cancel_map:    dict[int, bool]          = {}   # cancel flag
_process_tasks: dict[int, list]          = {}   # uid → [Task, ...]
_user_queued:   dict[int, int]           = {}   # files waiting in global queue

_dedup: dict[str, float] = {}


# ── Public helpers ────────────────────────────────────────────────────────────
def get_user_stats(uid: int) -> dict:
    return {
        "processing": _active_map.get(uid, 0),
        "waiting":    _user_queued.get(uid, 0),
        "total":      _active_map.get(uid, 0) + _user_queued.get(uid, 0),
    }


def get_global_stats() -> dict:
    return {
        "queued": _GLOBAL_QUEUE.qsize(),
        "active": sum(_active_map.values()),
        "users":  sum(1 for v in _active_map.values() if v > 0),
    }


def cancel_user(uid: int) -> None:
    """Drain queued jobs, set cancel flag, cancel all live tasks."""
    _cancel_map[uid]   = True
    _user_queued[uid]  = 0
    # Cancel running tasks
    for t in list(_process_tasks.get(uid, [])):
        if not t.done():
            t.cancel()
    _process_tasks.pop(uid, None)


# ══════════════════════════════════════════════════════════════════════════════
#  INTERNAL HELPERS
# ══════════════════════════════════════════════════════════════════════════════
def _get_lock(uid: int) -> asyncio.Lock:
    if uid not in _lock_map:
        _lock_map[uid] = asyncio.Lock()
    return _lock_map[uid]


def _safe_del(*paths) -> None:
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


def _resolve(val: str | None, fname: str) -> str:
    return val.replace("{filename}", fname) if val else ""


def _init_user(uid: int) -> None:
    _lock_map[uid]     = asyncio.Lock()
    _active_map[uid]   = 0
    _total_map[uid]    = 0
    _done_map[uid]     = 0
    _user_queued[uid]  = 0
    _start_map[uid]    = time.time()
    _cancel_map[uid]   = False
    _summary_map[uid]  = None


def _cleanup_user(uid: int) -> None:
    for d in (_lock_map, _active_map, _total_map, _done_map, _user_queued,
              _start_map, _summary_map, _cancel_map, _process_tasks):
        d.pop(uid, None)


def _track_task(uid: int, task: asyncio.Task) -> None:
    lst = _process_tasks.setdefault(uid, [])
    lst.append(task)
    def _remove(t):
        if t in lst:
            lst.remove(t)
    task.add_done_callback(_remove)


def _is_alive(uid: int) -> bool:
    return uid in _lock_map


# ══════════════════════════════════════════════════════════════════════════════
#  FLOODWAIT-SAFE WRAPPERS
# ══════════════════════════════════════════════════════════════════════════════
async def _floodwait_download(
    client,
    message: Message,
    file_path: str,
    prog_hdr: str,
    prog_msg: Message,
    uid: int,
) -> str:
    """
    Download with FloodWait retry + PermissionError retry (Windows).
    Acquires _DL_SEM before starting — up to 3 concurrent downloads.
    The semaphore is RELEASED as soon as the download completes so the
    next queued file can start its download immediately.
    """
    if _cancel_map.get(uid):
        raise asyncio.CancelledError("Cancelled before download")

    # Show waiting state briefly if all DL slots are taken
    if _DL_SEM._value == 0:
        try:
            await prog_msg.edit(
                f"{prog_hdr}\n"
                "⧗ Wᴀɪᴛɪɴɢ ꜰᴏʀ ᴅᴏᴡɴʟᴏᴀᴅ sʟᴏᴛ..."
            )
        except Exception:
            pass

    async with _DL_SEM:
        if _cancel_map.get(uid):
            raise asyncio.CancelledError("Cancelled waiting for DL slot")

        _safe_del(file_path, file_path + ".temp", file_path + ".part")

        for attempt in range(1, MAX_RETRIES + 2):
            if _cancel_map.get(uid):
                raise asyncio.CancelledError("Cancelled during download")
            try:
                try:
                    await prog_msg.edit(f"{prog_hdr}\n➥ Dᴏᴡɴʟᴏᴀᴅɪɴɢ...")
                except Exception:
                    pass

                t0     = time.time()
                result = await client.download_media(
                    message,
                    file_name=file_path,
                    progress=progress_for_pyrogram,
                    progress_args=(
                        f"{prog_hdr}\n➥ Dᴏᴡɴʟᴏᴀᴅɪɴɢ...",
                        prog_msg, t0,
                    ),
                )
                if result and os.path.exists(result):
                    return result
                raise RuntimeError("Download returned empty path")

            except asyncio.CancelledError:
                _safe_del(file_path, file_path + ".temp", file_path + ".part")
                raise

            except FloodWait as e:
                wait = e.value + 5
                logger.warning(f"FloodWait {wait}s on download uid={uid}")
                try:
                    await prog_msg.edit(
                        f"{prog_hdr}\n⏳ FloodWait {wait}s..."
                    )
                except Exception:
                    pass
                await asyncio.sleep(wait)

            except PermissionError as e:
                if attempt <= MAX_RETRIES:
                    logger.warning(
                        f"PermissionError attempt {attempt} uid={uid}: {e}"
                    )
                    _safe_del(file_path + ".temp")
                    await asyncio.sleep(2)
                else:
                    raise

            except Exception:
                raise

    raise RuntimeError(f"Download failed after {MAX_RETRIES} attempts")


async def _floodwait_upload(
    client,
    uid: int,
    upload_as: str,
    final_path: str,
    duration: float,
    caption: str,
    thumb: str | None,
    chat_id: int,
    prog_hdr: str,
    prog_msg: Message,
) -> Message | None:
    """
    Upload with FloodWait retry + _UL_SEM(3) concurrency limit.
    Returns the sent Message or None on failure.
    """
    async with _UL_SEM:
        if _cancel_map.get(uid):
            return None

        for attempt in range(1, MAX_RETRIES + 2):
            try:
                t0 = time.time()
                kw = dict(
                    chat_id=chat_id,
                    caption=caption,
                    thumb=thumb,
                    progress=progress_for_pyrogram,
                    progress_args=(
                        f"{prog_hdr}\n➥ Uᴘʟᴏᴀᴅɪɴɢ...",
                        prog_msg, t0,
                    ),
                )
                if upload_as == "video":
                    return await client.send_video(
                        video=final_path,
                        duration=int(duration) if duration else 0,
                        supports_streaming=True,
                        **kw,
                    )
                elif upload_as == "audio":
                    return await client.send_audio(
                        audio=final_path,
                        duration=int(duration) if duration else 0,
                        **kw,
                    )
                else:
                    return await client.send_document(
                        document=final_path, **kw
                    )

            except asyncio.CancelledError:
                raise

            except FloodWait as e:
                wait = e.value + 5
                logger.warning(f"FloodWait {wait}s on upload uid={uid}")
                try:
                    await prog_msg.edit(
                        f"{prog_hdr}\n⏳ FloodWait {wait}s..."
                    )
                except Exception:
                    pass
                await asyncio.sleep(wait)

            except RPCError as e:
                if attempt <= MAX_RETRIES:
                    logger.warning(
                        f"Upload RPCError attempt {attempt} uid={uid}: {e}"
                    )
                    await asyncio.sleep(3)
                else:
                    raise

            except Exception:
                raise

    return None


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
            # Run PIL in thread pool — blocking CPU operation
            loop = asyncio.get_running_loop()
            await loop.run_in_executor(
                _THREAD_POOL,
                lambda: Image.open(path).convert("RGB").save(path, "JPEG"),
            )
        return path
    except Exception as e:
        logger.debug(f"Thumbnail uid={uid}: {e}")
        return None


# ══════════════════════════════════════════════════════════════════════════════
#  FFMPEG  (semaphore-controlled, non-blocking)
# ══════════════════════════════════════════════════════════════════════════════
async def _ffmpeg_run(cmd: list, uid: int, timeout: int = 300) -> bool:
    """asyncio.create_subprocess_exec — never blocks the event loop."""
    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        _, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
        if proc.returncode != 0:
            logger.warning(
                f"ffmpeg uid={uid}: {stderr.decode(errors='replace')[:200]}"
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
    # Fetch all 9 metadata fields in parallel (asyncio.gather)
    (title, artist, author, vid, aud, sub,
     enc, ctag, cmt) = await asyncio.gather(
        db.get_title(uid),      db.get_artist(uid),   db.get_author(uid),
        db.get_video(uid),      db.get_audio(uid),    db.get_subtitle(uid),
        db.get_encoded_by(uid), db.get_custom_tag(uid), db.get_comment(uid),
    )
    r   = lambda v: _resolve(v, new_name)
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
    Run ffmpeg under _FFMPEG_SEM(2) — max 2 simultaneous processes.
    Returns output_path on success, input_path on failure.
    """
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        return input_path
    _safe_del(output_path)

    async with _FFMPEG_SEM:
        cmd = await _build_meta_cmd(
            ffmpeg, input_path, output_path, uid, new_name, to_mkv
        )
        ok = await _ffmpeg_run(
            cmd, uid, timeout=600 if to_mkv else 300
        )
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
        logger.debug(f"Dump uid={uid}: {e}")


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
    avg     = elapsed / renamed if renamed > 0 else 0
    am, as_ = divmod(int(avg), 60)
    avg_s   = f"{am}m {as_}s"

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
            f"◍ ᴀᴠᴇʀᴀɢᴇ ᴘᴇʀ ᴛᴀsᴋ  : <code>« {avg_s} »</code>\n"
            f"◍ Pʀᴏᴄᴇssɪɴɢ Fɪʟᴇs  : <code>« {active} »</code>\n"
            f"◍ Fɪʟᴇs Rᴇɴᴀᴍᴇᴅ    : <code>« {renamed} »</code>"
        )
    try:
        await msg.edit(text)
    except Exception:
        pass


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
    Full pipeline for a single file:

      [DOWNLOAD]  → acquired _DL_SEM(3), runs download_media
                  → DL_SEM RELEASED immediately on completion
      [FFMPEG]    → acquired _FFMPEG_SEM(2), injects metadata
                  → runs concurrently with other downloads/uploads
      [UPLOAD]    → acquired _UL_SEM(3), sends to Telegram
                  → runs concurrently with other downloads/ffmpeg

    Key: each semaphore is held ONLY for its own stage.
    File B's download starts the moment File A finishes downloading,
    regardless of where File A is in its metadata/upload pipeline.
    """
    # Track this task for cancel support
    current_task = asyncio.current_task()
    if current_task:
        _track_task(uid, current_task)

    # Update queued count
    async with _get_lock(uid):
        _user_queued[uid] = max(0, _user_queued.get(uid, 1) - 1)
        _active_map[uid]  = _active_map.get(uid, 0) + 1

    file_obj  = message.document or message.video or message.audio
    if not file_obj:
        async with _get_lock(uid):
            _active_map[uid] = max(0, _active_map.get(uid, 1) - 1)
        await _check_batch_done(uid)
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
        async with _get_lock(uid):
            _active_map[uid] = max(0, _active_map.get(uid, 1) - 1)
        await _check_batch_done(uid)
        return
    _dedup[file_id] = now

    # ── Extension ─────────────────────────────────────────────────────────────
    _, ext    = os.path.splitext(orig_name)
    ext       = ext.lower() if ext else ".mkv"
    is_mp4    = ext in (".mp4", ".m4v")
    final_ext = ".mkv" if is_mp4 else ext

    # ── Source text + template ────────────────────────────────────────────────
    src_pref    = await db.get_rename_source(uid)
    source_text = (
        (message.caption or orig_name) if src_pref == "caption" else orig_name
    )
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
            _active_map[uid] = max(0, _active_map.get(uid, 1) - 1)
        await _check_batch_done(uid)
        return

    base     = apply_format_template(template, source_text)
    base     = base or os.path.splitext(orig_name)[0]
    new_name = f"{base}{final_ext}"

    # ── Paths ─────────────────────────────────────────────────────────────────
    u       = str(uid)
    dl_path = os.path.join("downloads", u, new_name)
    md_path = os.path.join("metadata",  u, new_name)
    _mkdirs(dl_path, md_path)

    orig_hdr = f"❐ <code>{orig_name}</code>"
    new_hdr  = f"❐ <code>{new_name}</code>"

    dl_result  = None
    final_path = None
    ph_path    = None
    keep_prog  = False

    try:
        if _cancel_map.get(uid):
            return

        # ════════════════════════════════════
        #  STAGE 1 — DOWNLOAD
        #  _DL_SEM(3): up to 3 simultaneous
        # ════════════════════════════════════
        dl_result = await _floodwait_download(
            client, message, dl_path, orig_hdr, prog_msg, uid
        )
        # ↑ _DL_SEM is RELEASED here — next file starts downloading immediately

        if _cancel_map.get(uid):
            return

        await _edit_summary(uid)

        # ════════════════════════════════════
        #  STAGE 2 — FFMPEG METADATA / MKV
        #  _FFMPEG_SEM(2): up to 2 simultaneous
        #  Runs while OTHER files download/upload
        # ════════════════════════════════════
        meta_on = await db.get_metadata_mode(uid)

        if is_mp4:
            try:
                await prog_msg.edit(
                    f"{new_hdr}\n➥ Cᴏɴᴠᴇʀᴛɪɴɢ MP4 → MKV + Mᴇᴛᴀᴅᴀᴛᴀ..."
                )
            except Exception:
                pass
            final_path = await _apply_ffmpeg(
                dl_result, md_path, uid, new_name, to_mkv=True
            )
        elif meta_on:
            try:
                await prog_msg.edit(f"{new_hdr}\n➥ Aᴅᴅɪɴɢ Mᴇᴛᴀᴅᴀᴛᴀ...")
            except Exception:
                pass
            final_path = await _apply_ffmpeg(
                dl_result, md_path, uid, new_name, to_mkv=False
            )
        else:
            final_path = dl_result
        # ↑ _FFMPEG_SEM released here

        if _cancel_map.get(uid):
            return

        # ════════════════════════════════════
        #  STAGE 3 — PREPARE UPLOAD
        # ════════════════════════════════════
        # Fetch thumbnail + duration + caption concurrently
        thumb_task    = asyncio.create_task(_get_thumbnail(client, uid, message))
        duration_task = asyncio.create_task(
            detect_duration(final_path)
            if media_src in ("video", "audio")
            else asyncio.coroutine(lambda: 0.0)()
        )
        ph_path, duration = await asyncio.gather(
            thumb_task, duration_task, return_exceptions=False
        )
        if isinstance(ph_path, Exception):
            ph_path = None
        if isinstance(duration, Exception):
            duration = 0.0

        cap_tpl = await db.get_caption(uid)
        caption = (
            apply_caption_template(
                cap_tpl, new_name, source_text, file_size, duration
            ) if cap_tpl else f"<b>{new_name}</b>"
        )

        pref      = await db.get_media_preference(uid)
        upload_as = media_src if message.audio else pref

        # ════════════════════════════════════
        #  STAGE 4 — UPLOAD
        #  _UL_SEM(3): up to 3 simultaneous
        #  Runs while OTHER files download/metadata
        # ════════════════════════════════════
        try:
            await prog_msg.edit(f"{new_hdr}\n➥ Uᴘʟᴏᴀᴅɪɴɢ...")
        except Exception:
            pass

        sent = await _floodwait_upload(
            client, uid, upload_as,
            final_path, duration,
            caption, ph_path,
            message.chat.id,
            new_hdr, prog_msg,
        )
        # ↑ _UL_SEM released here

        # ════════════════════════════════════
        #  STAGE 5 — POST-UPLOAD
        # ════════════════════════════════════
        if Config.DUMP_CHANNEL and sent:
            asyncio.create_task(
                _send_dump(
                    client, uid, message, sent,
                    orig_name, new_name, file_size, ph_path, upload_as,
                )
            )

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
        if not keep_prog:
            try:
                await prog_msg.delete()
            except Exception:
                pass

        if _IS_WINDOWS:
            await asyncio.sleep(0.3)

        to_del = {dl_path, md_path}
        if final_path and final_path not in to_del:
            to_del.add(final_path)
        _safe_del(*to_del)
        if ph_path:
            _safe_del(ph_path)

        # Decrement active count + check if batch is complete
        async with _get_lock(uid):
            _active_map[uid] = max(0, _active_map.get(uid, 1) - 1)
        await _check_batch_done(uid)
        await _edit_summary(uid)


async def _check_batch_done(uid: int) -> None:
    """Send 'All Completed' and clean up if no active or queued files remain."""
    if _active_map.get(uid, 0) == 0 and _user_queued.get(uid, 0) == 0:
        # Small sleep to let any in-flight _edit_summary calls finish
        await asyncio.sleep(0.5)
        # Double-check — another task might have started in the interim
        if _active_map.get(uid, 0) == 0 and _user_queued.get(uid, 0) == 0:
            await _edit_summary(uid, done=True)
            _cleanup_user(uid)


# ══════════════════════════════════════════════════════════════════════════════
#  MAIN HANDLER — receives incoming file messages
# ══════════════════════════════════════════════════════════════════════════════
@Client.on_message(
    filters.private & (filters.document | filters.video | filters.audio)
)
@check_shutdown
@check_ban
@check_fsub
async def auto_rename_files(client, message: Message) -> None:
    uid = message.from_user.id

    # ── Ensure workers are running ─────────────────────────────────────────
    start_workers()

    # ── Format must be set ────────────────────────────────────────────────
    if not await db.get_format_template(uid):
        await message.reply_text(
            "<blockquote>ⓘ Pʟᴇᴀsᴇ sᴇᴛ ᴀ ʀᴇɴᴀᴍᴇ ꜰᴏʀᴍᴀᴛ ꜰɪʀsᴛ ᴜsɪɴɢ "
            "<code>/format</code></blockquote>"
        )
        return

    # ── Init per-user state ────────────────────────────────────────────────
    if not _is_alive(uid):
        _init_user(uid)

    async with _get_lock(uid):
        _total_map[uid] = _total_map.get(uid, 0) + 1
        file_num        = _total_map[uid]
        _user_queued[uid] = _user_queued.get(uid, 0) + 1

        # Summary message — created once per batch
        if file_num == 1:
            _start_map[uid]   = time.time()
            _summary_map[uid] = await message.reply_text(
                "≡ <b>Rᴇɴᴀᴍᴇ Sᴛᴀʀᴛᴇᴅ...</b>\n"
                "◍ ᴛᴏᴛᴀʟ Fɪʟᴇs       : <code>« 1 »</code>\n"
                "◍ Pʀᴏᴄᴇssɪɴɢ Fɪʟᴇs  : <code>« 0 »</code>\n"
                "◍ Fɪʟᴇs Rᴇɴᴀᴍᴇᴅ    : <code>« 0 »</code>"
            )

        # Every file gets its own "added to queue" message immediately
        prog_msg = await message.reply_text(
            f"<blockquote>{file_num} ꜰɪʟᴇ ᴀᴅᴅᴇᴅ ᴛᴏ ǫᴜᴇᴜᴇ....</blockquote>"
        )

    # ── Push job to global queue — a worker will pick it up ───────────────
    await _GLOBAL_QUEUE.put((client, uid, message, prog_msg))
    await _edit_summary(uid)
