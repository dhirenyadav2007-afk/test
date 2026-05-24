"""
plugins/metadata.py — Full /metadata panel with Set All Wizard.

ROOT CAUSE FIXES:
─────────────────────────────────────────────────────────────────────────────
1. WIZARD NOT WORKING:
   Two handlers (handle_single_edit_reply + handle_wizard_reply) were both
   registered on group=1 with identical filters.  Pyrogram fires only ONE
   handler per group per message (first one loaded wins).  Fixed by merging
   them into ONE dispatcher function that checks state priority:
     wizard state first → single-edit state second → ignore.

2. WIZARD start_wizard FETCHING PANEL MSG:
   `client.get_messages()` fails silently if the message isn't in Pyrogram's
   internal cache (common on bot restart / long gaps).  The wizard now stores
   the panel Message OBJECT directly in state, not just its id+chat_id.

3. WIZARD SELECTION SCREEN was on the same message as the panel, so editing
   the panel back during wstart broke the wizard UX.  Now the selection screen
   replaces the edit-panel message in-place, and the wizard prompt is a NEW
   message — panel stays visible above, prompt is below.
─────────────────────────────────────────────────────────────────────────────
"""

import asyncio
import logging
from pyrogram import Client, filters
from pyrogram.types import (
    Message, CallbackQuery,
    InlineKeyboardMarkup, InlineKeyboardButton,
)
from config import Config
from helper.database import db
from plugins.start import check_ban, check_fsub, check_shutdown, btn, ik

logger = logging.getLogger(__name__)


# ══════════════════════════════════════════════════════════════════════════════
#  FIELD DEFINITIONS
# ══════════════════════════════════════════════════════════════════════════════
META_FIELDS: list[tuple[str, str]] = [
    ("title",      "Title"),
    ("author",     "Author"),
    ("artist",     "Artist"),
    ("audio",      "Audio"),
    ("subtitle",   "Subtitle"),
    ("video",      "Video"),
    ("encoded_by", "Encoded By"),
    ("custom_tag", "Custom Tag"),
    ("comment",    "Comment"),
]
_FIELD_KEYS   = [k for k, _ in META_FIELDS]
_FIELD_LABELS = {k: v for k, v in META_FIELDS}


# ══════════════════════════════════════════════════════════════════════════════
#  STATE
#
#  _single_edit[uid] = {
#    "field":     str,        # which field is being edited
#    "panel_msg": Message,    # the panel message object (to restore it after)
#  }
#
#  _wizard[uid] = {
#    "phase":      "select" | "input",
#    "selected":   set[str],  # fields selected in the pick-screen
#    "fields":     [str],     # ordered list once wizard starts
#    "idx":        int,       # current position in fields
#    "panel_msg":  Message,   # original panel message
#    "prompt_msg": Message | None,  # live wizard prompt message
#  }
# ══════════════════════════════════════════════════════════════════════════════
_single_edit: dict[int, dict] = {}
_wizard:      dict[int, dict] = {}


# ══════════════════════════════════════════════════════════════════════════════
#  KEYBOARD BUILDERS
# ══════════════════════════════════════════════════════════════════════════════
def _kb_main(mode_on: bool) -> InlineKeyboardMarkup:
    on_l  = "✓ ON Meta"  if mode_on     else "ON Meta"
    off_l = "✓ OFF Meta" if not mode_on else "OFF Meta"
    return ik(
        [btn(on_l, cd="meta_on"), btn(off_l, cd="meta_off")],
        [btn("⚙ Sᴇᴛ Mᴇᴛᴀ", cd="meta_edit")],
    )


def _kb_edit_panel() -> InlineKeyboardMarkup:
    rows = []
    for i in range(0, len(META_FIELDS), 3):
        row = [
            btn(_FIELD_LABELS[META_FIELDS[j][0]], cd=f"mset_{META_FIELDS[j][0]}")
            for j in range(i, min(i + 3, len(META_FIELDS)))
        ]
        rows.append(row)
    rows.append([btn("✦ Sᴇᴛ Aʟʟ Wɪᴢᴀʀᴅ", cd="mwiz_open"), btn("🗑 Cʟᴇᴀʀ", cd="meta_clear")])
    rows.append([btn("« Bᴀᴄᴋ", cd="meta_back"), btn("✕ Cʟᴏsᴇ", cd="close_msg")])
    return InlineKeyboardMarkup(rows)


def _kb_wizard_select(selected: set) -> InlineKeyboardMarkup:
    rows = []
    for i in range(0, len(META_FIELDS), 3):
        row = []
        for j in range(i, min(i + 3, len(META_FIELDS))):
            k, lbl = META_FIELDS[j]
            tick   = "✓ " if k in selected else ""
            row.append(btn(f"{tick}{lbl}", cd=f"wtog_{k}"))
        rows.append(row)
    rows.append([btn("▶ Sᴛᴀʀᴛ Wɪᴢᴀʀᴅ", cd="wstart"), btn("✕ Cᴀɴᴄᴇʟ", cd="wcancel")])
    return InlineKeyboardMarkup(rows)


def _kb_cancel_wizard() -> InlineKeyboardMarkup:
    return ik([btn("✕ Cᴀɴᴄᴇʟ Wɪᴢᴀʀᴅ", cd="wcancel")])


def _kb_cancel_edit() -> InlineKeyboardMarkup:
    return ik([btn("✕ Cᴀɴᴄᴇʟ", cd="mcancel")])


# ══════════════════════════════════════════════════════════════════════════════
#  TEXT BUILDERS
# ══════════════════════════════════════════════════════════════════════════════
def _text_main(meta: dict, mode_on: bool) -> str:
    mode  = "<b>On</b>" if mode_on else "<b>Off</b>"
    lines = [f"<blockquote>✦ <b>METADATA MODE</b> : {mode}</blockquote>\n"]
    for key, label in META_FIELDS:
        val = meta.get(key) or f"@{Config.BOT_USERNAME}"
        lines.append(f"◆ <b>{label}</b> ➤ <code>{val}</code>")
    return "\n".join(lines)


def _text_edit_panel() -> str:
    return (
        "<blockquote>✦ <b>METADATA EDIT PANEL</b></blockquote>\n"
        "<blockquote>≡ Sᴇʟᴇᴄᴛ ᴀ ꜰɪᴇʟᴅ ᴛᴏ ᴇᴅɪᴛ, ᴏʀ ᴜsᴇ ᴛʜᴇ Wɪᴢᴀʀᴅ / Cʟᴇᴀʀ ᴛᴏᴏʟs.</blockquote>"
    )


def _text_wizard_select() -> str:
    return (
        "<blockquote>✦ <b>SET ALL WIZARD</b></blockquote>\n"
        "<blockquote>≡ Tᴀᴘ ꜰɪᴇʟᴅs ᴛᴏ sᴇʟᴇᴄᴛ ᴛʜᴇᴍ, ᴛʜᴇɴ ᴄʟɪᴄᴋ ▶ Sᴛᴀʀᴛ Wɪᴢᴀʀᴅ.</blockquote>"
    )


def _text_field_prompt(label: str, context: str = "edit") -> str:
    prefix = "✦ <b>SET ALL WIZARD</b>" if context == "wizard" else "✦ <b>EDIT METADATA</b>"
    return (
        f"<blockquote>{prefix}</blockquote>\n"
        f"<blockquote>⓪ Sᴇɴᴅ ʏᴏᴜʀ ɴᴇᴡ ᴛᴇxᴛ ꜰᴏʀ : <b>{label}</b></blockquote>\n"
        "<blockquote>◆ Sᴜᴘᴘᴏʀᴛᴇᴅ ᴘʟᴀᴄᴇʜᴏʟᴅᴇʀ:\n"
        "<code>{filename}</code> → ʀᴇᴘʟᴀᴄᴇᴅ ᴡɪᴛʜ ᴛʜᴇ ʀᴇɴᴀᴍᴇᴅ ꜰɪʟᴇɴᴀᴍᴇ</blockquote>\n"
        "<blockquote>⧗ 60 sᴇᴄᴏɴᴅs ᴛᴏ ʀᴇᴘʟʏ.</blockquote>"
    )


def _text_wizard_step(label: str, idx: int, total: int) -> str:
    return (
        "<blockquote>✦ <b>SET ALL WIZARD</b></blockquote>\n"
        f"<blockquote>⓪ Sᴇɴᴅ ᴛᴇxᴛ ꜰᴏʀ : <b>{label}</b>  ({idx + 1}/{total})</blockquote>\n"
        "<blockquote>◆ Sᴜᴘᴘᴏʀᴛᴇᴅ ᴘʟᴀᴄᴇʜᴏʟᴅᴇʀ: <code>{filename}</code></blockquote>\n"
        "<blockquote>⧗ 60 sᴇᴄᴏɴᴅs ᴛᴏ ʀᴇᴘʟʏ ᴏʀ ᴄʟɪᴄᴋ Cᴀɴᴄᴇʟ.</blockquote>"
    )


# ══════════════════════════════════════════════════════════════════════════════
#  SAFE EDIT HELPER
# ══════════════════════════════════════════════════════════════════════════════
async def _safe_edit(msg: Message, text: str, kb: InlineKeyboardMarkup) -> None:
    try:
        if msg.caption is not None:
            await msg.edit_caption(text, reply_markup=kb)
        else:
            await msg.edit_text(text, reply_markup=kb)
    except Exception as e:
        logger.debug(f"_safe_edit failed: {e}")


# ══════════════════════════════════════════════════════════════════════════════
#  /metadata — entry point
# ══════════════════════════════════════════════════════════════════════════════
@Client.on_message(filters.command("metadata") & filters.private)
@check_shutdown
@check_ban
@check_fsub
async def metadata_cmd(client: Client, message: Message):
    uid     = message.from_user.id
    mode_on = await db.get_metadata_mode(uid)
    meta    = await db.get_all_metadata(uid)
    pic     = Config.rand_pic("METADATA")
    text    = _text_main(meta, mode_on)
    kb      = _kb_main(mode_on)
    if pic:
        await message.reply_photo(pic, caption=text, reply_markup=kb)
    else:
        await message.reply_text(text, reply_markup=kb)


# ══════════════════════════════════════════════════════════════════════════════
#  MODE TOGGLE
# ══════════════════════════════════════════════════════════════════════════════
@Client.on_callback_query(filters.regex(r"^meta_(on|off)$"))
@check_ban
async def cb_meta_mode(client: Client, cq: CallbackQuery):
    uid     = cq.from_user.id
    new_val = cq.data == "meta_on"
    await db.set_metadata_mode(uid, new_val)
    meta    = await db.get_all_metadata(uid)
    await _safe_edit(cq.message, _text_main(meta, new_val), _kb_main(new_val))
    await cq.answer("Mᴏᴅᴇ ᴜᴘᴅᴀᴛᴇᴅ!")


# ══════════════════════════════════════════════════════════════════════════════
#  OPEN EDIT PANEL
# ══════════════════════════════════════════════════════════════════════════════
@Client.on_callback_query(filters.regex(r"^meta_edit$"))
@check_ban
async def cb_meta_edit(client: Client, cq: CallbackQuery):
    await _safe_edit(cq.message, _text_edit_panel(), _kb_edit_panel())
    await cq.answer()


# ══════════════════════════════════════════════════════════════════════════════
#  BACK TO MAIN PANEL
# ══════════════════════════════════════════════════════════════════════════════
@Client.on_callback_query(filters.regex(r"^meta_back$"))
@check_ban
async def cb_meta_back(client: Client, cq: CallbackQuery):
    uid     = cq.from_user.id
    # Clean up any pending state
    _single_edit.pop(uid, None)
    _wizard.pop(uid, None)
    mode_on = await db.get_metadata_mode(uid)
    meta    = await db.get_all_metadata(uid)
    await _safe_edit(cq.message, _text_main(meta, mode_on), _kb_main(mode_on))
    await cq.answer()


# ══════════════════════════════════════════════════════════════════════════════
#  CLEAR ALL METADATA
# ══════════════════════════════════════════════════════════════════════════════
@Client.on_callback_query(filters.regex(r"^meta_clear$"))
@check_ban
async def cb_meta_clear(client: Client, cq: CallbackQuery):
    uid = cq.from_user.id
    await db.clear_all_metadata(uid)
    await cq.answer("✓ Aʟʟ ᴍᴇᴛᴀᴅᴀᴛᴀ ᴄʟᴇᴀʀᴇᴅ!", show_alert=True)
    await _safe_edit(cq.message, _text_edit_panel(), _kb_edit_panel())


# ══════════════════════════════════════════════════════════════════════════════
#  SINGLE FIELD EDIT — user clicked one field button
# ══════════════════════════════════════════════════════════════════════════════
@Client.on_callback_query(filters.regex(r"^mset_(.+)$"))
@check_ban
async def cb_mset_field(client: Client, cq: CallbackQuery):
    uid   = cq.from_user.id
    field = cq.data[5:]   # strip "mset_"
    if field not in _FIELD_KEYS:
        await cq.answer("Unknown field.", show_alert=True)
        return

    label = _FIELD_LABELS[field]

    # Clear any old wizard state so the unified reply handler goes to single-edit
    _wizard.pop(uid, None)

    _single_edit[uid] = {
        "field":     field,
        "panel_msg": cq.message,  # store the Message object directly
    }

    await _safe_edit(cq.message, _text_field_prompt(label, "edit"), _kb_cancel_edit())
    await cq.answer()

    # Auto-expire after 60 s
    async def _expire(u: int, f: str):
        await asyncio.sleep(60)
        st = _single_edit.get(u)
        if st and st.get("field") == f:
            _single_edit.pop(u, None)
    asyncio.create_task(_expire(uid, field))


# ══════════════════════════════════════════════════════════════════════════════
#  CANCEL SINGLE EDIT
# ══════════════════════════════════════════════════════════════════════════════
@Client.on_callback_query(filters.regex(r"^mcancel$"))
@check_ban
async def cb_mcancel(client: Client, cq: CallbackQuery):
    uid = cq.from_user.id
    _single_edit.pop(uid, None)
    await _safe_edit(cq.message, _text_edit_panel(), _kb_edit_panel())
    await cq.answer("Cᴀɴᴄᴇʟʟᴇᴅ.")


# ══════════════════════════════════════════════════════════════════════════════
#  WIZARD — OPEN SELECTION SCREEN
# ══════════════════════════════════════════════════════════════════════════════
@Client.on_callback_query(filters.regex(r"^mwiz_open$"))
@check_ban
async def cb_mwiz_open(client: Client, cq: CallbackQuery):
    uid = cq.from_user.id
    # Clear single-edit state if any
    _single_edit.pop(uid, None)

    _wizard[uid] = {
        "phase":      "select",
        "selected":   set(),
        "fields":     [],
        "idx":        0,
        "panel_msg":  cq.message,   # store Message object directly
        "prompt_msg": None,
    }
    await _safe_edit(cq.message, _text_wizard_select(), _kb_wizard_select(set()))
    await cq.answer()


# ══════════════════════════════════════════════════════════════════════════════
#  WIZARD — TOGGLE FIELD SELECTION
# ══════════════════════════════════════════════════════════════════════════════
@Client.on_callback_query(filters.regex(r"^wtog_(.+)$"))
@check_ban
async def cb_wtog(client: Client, cq: CallbackQuery):
    uid   = cq.from_user.id
    field = cq.data[5:]   # strip "wtog_"
    if field not in _FIELD_KEYS:
        await cq.answer()
        return

    # Initialise wizard state if user somehow got here without mwiz_open
    state = _wizard.setdefault(uid, {
        "phase": "select", "selected": set(), "fields": [], "idx": 0,
        "panel_msg": cq.message, "prompt_msg": None,
    })
    sel = state["selected"]
    sel.discard(field) if field in sel else sel.add(field)

    await _safe_edit(cq.message, _text_wizard_select(), _kb_wizard_select(sel))
    await cq.answer()


# ══════════════════════════════════════════════════════════════════════════════
#  WIZARD — START INPUT PHASE
# ══════════════════════════════════════════════════════════════════════════════
@Client.on_callback_query(filters.regex(r"^wstart$"))
@check_ban
async def cb_wstart(client: Client, cq: CallbackQuery):
    uid   = cq.from_user.id
    state = _wizard.get(uid)

    if not state or not state.get("selected"):
        await cq.answer("Sᴇʟᴇᴄᴛ ᴀᴛ ʟᴇᴀsᴛ ᴏɴᴇ ꜰɪᴇʟᴅ ꜰɪʀsᴛ!", show_alert=True)
        return

    # Build ordered field list preserving META_FIELDS order
    ordered = [k for k, _ in META_FIELDS if k in state["selected"]]
    state["fields"] = ordered
    state["idx"]    = 0
    state["phase"]  = "input"

    # Restore the panel message to edit-panel view  (no fetch needed — we have the object)
    panel_msg = state.get("panel_msg")
    if panel_msg:
        try:
            await _safe_edit(panel_msg, _text_edit_panel(), _kb_edit_panel())
        except Exception as e:
            logger.debug(f"Wizard panel restore failed: {e}")

    # Send the first wizard prompt as a NEW message
    first_label = _FIELD_LABELS[ordered[0]]
    prompt = await cq.message.reply_text(
        _text_wizard_step(first_label, 0, len(ordered)),
        reply_markup=_kb_cancel_wizard(),
    )
    state["prompt_msg"] = prompt
    await cq.answer()

    # Auto-expire wizard after 5 minutes of total inactivity
    async def _expire(u: int):
        await asyncio.sleep(300)
        st = _wizard.get(u)
        if st and st.get("phase") == "input":
            _wizard.pop(u, None)
    asyncio.create_task(_expire(uid))


# ══════════════════════════════════════════════════════════════════════════════
#  WIZARD — CANCEL
# ══════════════════════════════════════════════════════════════════════════════
@Client.on_callback_query(filters.regex(r"^wcancel$"))
@check_ban
async def cb_wcancel(client: Client, cq: CallbackQuery):
    uid   = cq.from_user.id
    state = _wizard.pop(uid, None)

    # Delete the prompt message
    if state and state.get("prompt_msg"):
        try:
            await state["prompt_msg"].delete()
        except Exception:
            pass

    # Restore panel if we have it
    panel_msg = state.get("panel_msg") if state else None
    if panel_msg:
        try:
            await _safe_edit(panel_msg, _text_edit_panel(), _kb_edit_panel())
        except Exception:
            pass

    await cq.answer("Wɪᴢᴀʀᴅ ᴄᴀɴᴄᴇʟʟᴇᴅ.")
    # cq.message is the prompt message — delete it too
    try:
        await cq.message.delete()
    except Exception:
        pass


# ══════════════════════════════════════════════════════════════════════════════
#  UNIFIED TEXT REPLY HANDLER  (group=1)
#
#  KEY FIX: ONE handler for ALL text input states — wizard takes priority,
#  then single-edit, then ignore.  Previously two separate handlers on group=1
#  meant only the first one loaded would ever fire (Pyrogram: 1 handler/group/msg).
# ══════════════════════════════════════════════════════════════════════════════
_CMD_LIST = [
    "start", "help", "format", "delformat", "vformat",
    "setsource", "setmedia", "sthumb", "del_thumb", "vthumb",
    "setcap", "viewcap", "delcap", "metadata",
    "queue", "cancel", "info", "leaderboard",
    "ban", "unban", "addadmin", "deladmin",
    "status", "users", "shutdown", "fsub", "broadcast",
]


@Client.on_message(
    filters.private & filters.text & ~filters.command(_CMD_LIST),
    group=1,
)
async def handle_meta_text_reply(client: Client, message: Message):
    """
    Unified handler for:
      • Set All Wizard input  (wizard state present and phase == "input")
      • Single field edit     (single_edit state present)
      • /cancel confirmation codes are handled in queue_cancel.py group=1
        but registered AFTER this one — Pyrogram checks both because group=1
        allows propagation (continue_propagation / stop_propagation not used).
    """
    uid = message.from_user.id

    # ── WIZARD (highest priority) ─────────────────────────────────────────────
    wiz = _wizard.get(uid)
    if wiz and wiz.get("phase") == "input" and wiz.get("fields"):
        fields = wiz["fields"]
        idx    = wiz["idx"]
        if idx >= len(fields):
            _wizard.pop(uid, None)
            return

        field = fields[idx]
        value = message.text.strip()
        label = _FIELD_LABELS[field]

        await db.set_metadata_field(uid, field, value)
        await message.reply_text(f"✓ <b>{label}</b> → <code>{value}</code>")

        next_idx = idx + 1
        if next_idx < len(fields):
            wiz["idx"]  = next_idx
            next_label  = _FIELD_LABELS[fields[next_idx]]
            prompt      = wiz.get("prompt_msg")
            kb          = _kb_cancel_wizard()
            new_text    = _text_wizard_step(next_label, next_idx, len(fields))
            if prompt:
                try:
                    await prompt.edit_text(new_text, reply_markup=kb)
                except Exception:
                    # Edit failed (message too old, etc.) — send fresh prompt
                    new_p = await message.reply_text(new_text, reply_markup=kb)
                    wiz["prompt_msg"] = new_p
            else:
                new_p = await message.reply_text(new_text, reply_markup=kb)
                wiz["prompt_msg"] = new_p
        else:
            # Wizard complete
            _wizard.pop(uid, None)
            prompt = wiz.get("prompt_msg")
            if prompt:
                try:
                    await prompt.delete()
                except Exception:
                    pass

            await message.reply_text(
                "✓ <b>𝗪𝗜𝗭𝗔𝗥𝗗 𝗖𝗢𝗠𝗣𝗟𝗘𝗧𝗘</b>\n"
                "<blockquote>◍ Aʟʟ sᴇʟᴇᴄᴛᴇᴅ ᴍᴇᴛᴀᴅᴀᴛᴀ ꜰɪᴇʟᴅs ᴜᴘᴅᴀᴛᴇᴅ.</blockquote>"
            )
            # Show fresh metadata panel
            mode_on = await db.get_metadata_mode(uid)
            meta    = await db.get_all_metadata(uid)
            pic     = Config.rand_pic("METADATA")
            text    = _text_main(meta, mode_on)
            kb2     = _kb_main(mode_on)
            if pic:
                await message.reply_photo(pic, caption=text, reply_markup=kb2)
            else:
                await message.reply_text(text, reply_markup=kb2)
        return  # consumed by wizard — stop here

    # ── SINGLE FIELD EDIT ────────────────────────────────────────────────────
    se = _single_edit.get(uid)
    if se:
        field  = se["field"]
        value  = message.text.strip()
        label  = _FIELD_LABELS.get(field, field)

        await db.set_metadata_field(uid, field, value)
        _single_edit.pop(uid, None)

        await message.reply_text(
            f"✓ <b>{label}</b> ᴜᴘᴅᴀᴛᴇᴅ ᴛᴏ:\n<code>{value}</code>"
        )

        # Restore the edit panel on the stored panel message
        panel_msg = se.get("panel_msg")
        if panel_msg:
            try:
                await _safe_edit(panel_msg, _text_edit_panel(), _kb_edit_panel())
            except Exception as e:
                logger.debug(f"Panel restore failed: {e}")
        return  # consumed
    # else: neither state active — message is for /cancel code handler or ignored