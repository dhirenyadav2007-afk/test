"""
helper/utils.py — Advanced extraction engine + progress + formatters.

Extraction priority chain for every field:
  Episode  : SxxExx → EP/Episode prefix → bracket E-tag → bare Exx →
             "N of M" → separator-bounded 2-3 digit → last-resort 2-digit
  Season   : SxxExx → Season word → bracket S-tag → bare Sxx →
             separator-bounded Sxx → Part/Cour/Arc mapping
  Quality  : numeric (4K/2160p/1080p…) → source (WEB-DL/BluRay…) → codec
  Audio    : Multi → Dual → Tri → language tokens → format tokens
  Title    : strip in layers → separators → edge junk → collapse

All extractors are safe against quality/year false positives.
"""

import re
import json
import math
import time
import asyncio
import shutil
import logging
from datetime import datetime

from config import Config

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────────────────────
#  PROGRESS BAR
# ─────────────────────────────────────────────────────────────────────────────
_prog_ts: dict[int, float] = {}   # msg_id → last edit time
_PROG_GAP = 3.0                   # minimum seconds between edits


async def progress_for_pyrogram(
    current: int, total: int,
    ud_type: str, message, start: float,
) -> None:
    if total == 0:
        return
    now  = time.time()
    mid  = getattr(message, "id", 0)
    last = _prog_ts.get(mid, 0)
    if current != total and now - last < _PROG_GAP:
        return
    _prog_ts[mid] = now

    elapsed  = max(now - start, 0.001)
    speed    = current / elapsed
    eta_s    = int((total - current) / speed) if speed > 0 else 0
    pct      = current * 100 / total
    filled   = int(pct / 5)
    bar      = "▰" * filled + "▱" * (20 - filled)

    text = (
        f"{ud_type}\n"
        f"<code>{bar}</code>\n"
        f"›› {humanbytes(current)} / {humanbytes(total)} • "
        f"{pct:.1f}% ›› {humanbytes(speed)}/s • {TimeFormatter(eta_s * 1000)}"
    )
    try:
        await message.edit(text)
    except Exception:
        pass


# ─────────────────────────────────────────────────────────────────────────────
#  FORMATTERS
# ─────────────────────────────────────────────────────────────────────────────
def humanbytes(size: float) -> str:
    if not size:
        return "0 B"
    labels = ["B", "KB", "MB", "GB", "TB"]
    n = 0
    while size >= 1024 and n < 4:
        size /= 1024
        n += 1
    return f"{size:.2f} {labels[n]}"


def TimeFormatter(ms: int) -> str:
    secs, _  = divmod(int(ms / 1000), 1)
    m, s     = divmod(secs, 60)
    h, m     = divmod(m, 60)
    if h:
        return f"{h}h {m}m {s}s"
    if m:
        return f"{m}m {s}s"
    return f"{s}s"


def convert(seconds: float) -> str:
    n = int(seconds) % 86400
    h = n // 3600; n %= 3600
    m = n // 60;   s = n % 60
    return f"{h}:{m:02d}:{s:02d}"


def get_readable_time(seconds: int) -> str:
    parts = []
    d, r = divmod(seconds, 86400)
    h, r = divmod(r, 3600)
    m, s = divmod(r, 60)
    if d: parts.append(f"{d}d")
    if h: parts.append(f"{h}h")
    if m: parts.append(f"{m}m")
    parts.append(f"{s}s")
    return " ".join(parts)


# ─────────────────────────────────────────────────────────────────────────────
#  QUALITY / YEAR GUARD  — values that look like episode nums but aren't
# ─────────────────────────────────────────────────────────────────────────────
_QUALITY_NUMS = {240, 360, 480, 576, 720, 1080, 1440, 2160, 4320}
_YEAR_RE      = re.compile(r'\b(19|20)\d{2}\b')

# Broad quality label pattern used for stripping in title cleaner
_QUALITY_LABEL_RE = re.compile(
    r'\b('
    r'4K|2K|UHD|FHD|SD|'
    r'4320p?|2160p?|1440p?|1080p?|720p?|576p?|480p?|360p?|240p?|'
    r'WEB-?DL|WEB|WEBRip|WEB-Rip|'
    r'BluRay|Blu-Ray|BDRip|BRRip|'
    r'HDTV|HDRip|DVDRip|DVDScr|'
    r'HEVC|H\.?264|H\.?265|AVC|x264|x265|'
    r'AAC|EAC3|AC3|DTS(?:-HD)?|TrueHD|FLAC|MP3|Opus|'
    r'HDR(?:10\+?)?|SDR|HLG|DV|DoVi|'
    r'PROPER|REPACK|EXTENDED|THEATRICAL|UNRATED|DC'
    r')\b',
    re.IGNORECASE,
)

# Patterns that confirm a number IS a quality/year (not episode)
_QUALITY_CONFIRM_RE = re.compile(
    r'\b(?:4320|2160|1440|1080|720|576|480|360|240)[pP]\b|'
    r'\b4[kK]\b|\b2[kK]\b',
    re.IGNORECASE,
)


def _is_quality_or_year(n: int, raw: str) -> bool:
    """Return True if integer n should be excluded from episode/season detection."""
    if n in _QUALITY_NUMS:
        if re.search(rf'\b{n}\s*[pPkK]', raw):
            return True
    if 1900 <= n <= 2100:
        if re.search(rf'\b{n}\b', raw) and _YEAR_RE.search(raw):
            return True
    return False


# ─────────────────────────────────────────────────────────────────────────────
#  NORMALISE INPUT  — make extraction robust on badly formatted filenames
# ─────────────────────────────────────────────────────────────────────────────
def _normalise(text: str) -> str:
    """
    Convert underscores/dots used as word-separators to spaces,
    collapse runs of separators, but preserve hyphen-separated tokens.
    Does NOT strip extension — caller strips if needed.
    """
    # Replace _ and . that are word separators (between alphanumerics)
    t = re.sub(r'(?<=[A-Za-z0-9])[._](?=[A-Za-z0-9])', ' ', text)
    # Replace runs of whitespace
    t = re.sub(r'[ \t]{2,}', ' ', t)
    return t.strip()


# ─────────────────────────────────────────────────────────────────────────────
#  EPISODE EXTRACTION
# ─────────────────────────────────────────────────────────────────────────────
def extract_episode_number(filename: str) -> int | None:
    """
    7-tier priority extraction with quality/year exclusion.
    Works on filenames with dots, underscores, spaces, brackets, mixed case.
    """
    if not filename:
        return None

    raw  = filename
    norm = _normalise(filename)

    # Strip extension for cleaner matching
    base_raw  = re.sub(r'\.[a-zA-Z0-9]{2,5}$', '', raw)
    base_norm = re.sub(r'\.[a-zA-Z0-9]{2,5}$', '', norm)

    def _try(s: str) -> int | None:
        # ── Tier 1: SxxExx — most reliable ───────────────────────────────────
        m = re.search(r'[Ss]\d{1,2}[\s._-]?[Ee](\d{1,4})', s)
        if m:
            return int(m.group(1))

        # ── Tier 2: Explicit Episode / EP prefix ──────────────────────────────
        m = re.search(r'\b(?:Episode|Ep(?:isode)?)[.\s_-]*(\d{1,4})\b', s, re.IGNORECASE)
        if m:
            n = int(m.group(1))
            if not _is_quality_or_year(n, s):
                return n

        # ── Tier 3: [E05] or (E05) ────────────────────────────────────────────
        m = re.search(r'[\[\(]E(\d{1,4})[\]\)]', s, re.IGNORECASE)
        if m:
            return int(m.group(1))

        # ── Tier 4: standalone Exx NOT part of SxxExx ────────────────────────
        m = re.search(r'(?<![A-Za-z0-9])E(\d{2,4})(?!\d)', s, re.IGNORECASE)
        if m:
            n = int(m.group(1))
            if not _is_quality_or_year(n, s):
                return n

        # ── Tier 5: "5 of 12" ─────────────────────────────────────────────────
        m = re.search(r'\b(\d{1,3})\s*of\s*\d{1,3}\b', s, re.IGNORECASE)
        if m:
            n = int(m.group(1))
            if 1 <= n <= 999:
                return n

        # ── Tier 6: separator-bounded 2–3 digit number ────────────────────────
        # Strip known quality words first to avoid false positives
        stripped = _QUALITY_LABEL_RE.sub(' ', s)
        stripped = _YEAR_RE.sub(' ', stripped)
        m = re.search(
            r'(?:^|[\s.\-_\[\(])(\d{2,3})(?:v\d)?(?:[\s.\-_\]\)]|$)',
            stripped,
        )
        if m:
            n = int(m.group(1))
            if 1 <= n <= 999 and not _is_quality_or_year(n, raw):
                return n

        # ── Tier 7: any isolated 2-digit number as absolute last resort ───────
        nums = re.findall(r'(?<!\d)(\d{2})(?!\d)', stripped)
        for c in nums:
            n = int(c)
            if 1 <= n <= 99 and not _is_quality_or_year(n, raw):
                return n

        return None

    # Try normalised first (handles _ and . separators), then raw
    result = _try(base_norm)
    if result is None:
        result = _try(base_raw)
    return result


# ─────────────────────────────────────────────────────────────────────────────
#  SEASON EXTRACTION
# ─────────────────────────────────────────────────────────────────────────────

# Part/Cour/Arc/Season-equivalent word map
_PART_MAP: dict[str, int] = {
    "one": 1, "two": 2, "three": 3, "four": 4, "five": 5,
    "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10,
    "i": 1, "ii": 2, "iii": 3, "iv": 4, "v": 5,
    "vi": 6, "vii": 7, "viii": 8, "ix": 9, "x": 10,
}


def extract_season_number(filename: str) -> int | None:
    """
    6-tier priority with Part/Cour/Arc fallback.
    Works with S01E05, Season 02, [S3], .S2., Part II, Cour 1, etc.
    """
    if not filename:
        return None

    raw  = filename
    norm = _normalise(filename)
    base_raw  = re.sub(r'\.[a-zA-Z0-9]{2,5}$', '', raw)
    base_norm = re.sub(r'\.[a-zA-Z0-9]{2,5}$', '', norm)

    def _try(s: str) -> int | None:
        # ── Tier 1: SxxExx ────────────────────────────────────────────────────
        m = re.search(r'[Ss](\d{1,2})[\s._-]?[Ee]\d{1,4}', s)
        if m:
            return int(m.group(1))

        # ── Tier 2: Season word ────────────────────────────────────────────────
        m = re.search(r'\bSeason[.\s_-]*(\d{1,2})\b', s, re.IGNORECASE)
        if m:
            n = int(m.group(1))
            if 1 <= n <= 99:
                return n

        # ── Tier 3: [S02] or (S2) ─────────────────────────────────────────────
        m = re.search(r'[\[\(]S(\d{1,2})[\]\)]', s, re.IGNORECASE)
        if m:
            n = int(m.group(1))
            if 1 <= n <= 99:
                return n

        # ── Tier 4: bare Sxx — not followed by digit, quality, or E ──────────
        m = re.search(
            r'(?:^|[\s.\-_])S(\d{1,2})(?![\d_Ee]|[\s._-]?\d{2,4}[pPkK])',
            s, re.IGNORECASE
        )
        if m:
            n = int(m.group(1))
            if 1 <= n <= 99:
                return n

        # ── Tier 5: separator-bounded Sxx: _S2_ / .S02. / -S3- ───────────────
        m = re.search(r'[.\-_]S(\d{1,2})[.\-_]', s, re.IGNORECASE)
        if m:
            n = int(m.group(1))
            if 1 <= n <= 99:
                return n

        # ── Tier 6: Part / Cour / Arc — numeric or roman/word ─────────────────
        # Numeric: "Part 2", "Cour 3", "Arc 1"
        m = re.search(
            r'\b(?:Part|Cour|Arc|Chapter)[.\s_-]*(\d{1,2})\b',
            s, re.IGNORECASE
        )
        if m:
            n = int(m.group(1))
            if 1 <= n <= 20:
                return n

        # Word/Roman: "Part II", "Part Two"
        m = re.search(
            r'\b(?:Part|Cour|Arc)[.\s_-]+([IVXivx]+|one|two|three|four|five|six|seven|eight|nine|ten)\b',
            s, re.IGNORECASE
        )
        if m:
            token = m.group(1).lower()
            n = _PART_MAP.get(token)
            if n:
                return n

        return None

    result = _try(base_norm)
    if result is None:
        result = _try(base_raw)
    return result


# ─────────────────────────────────────────────────────────────────────────────
#  AUDIO EXTRACTION
# ─────────────────────────────────────────────────────────────────────────────
_AUDIO_PRIORITY = [
    # (label, compiled pattern) — checked in order; first match of each wins
    ("Multi",    re.compile(r'\bMulti(?:[-\s]?audio)?\b',         re.IGNORECASE)),
    ("Dual",     re.compile(r'\bDual(?:[-\s]?audio)?\b',           re.IGNORECASE)),
    ("Tri",      re.compile(r'\bTri(?:[-\s]?audio)?\b',            re.IGNORECASE)),
    ("Hindi",    re.compile(r'\bHindi\b',                           re.IGNORECASE)),
    ("Tamil",    re.compile(r'\bTamil\b',                           re.IGNORECASE)),
    ("Telugu",   re.compile(r'\bTelugu\b',                          re.IGNORECASE)),
    ("Malayalam",re.compile(r'\bMalayalam\b',                       re.IGNORECASE)),
    ("Bengali",  re.compile(r'\bBengali\b',                         re.IGNORECASE)),
    ("English",  re.compile(r'\bEnglish\b',                         re.IGNORECASE)),
    ("Eng",      re.compile(r'\bEng\b',                             re.IGNORECASE)),
    ("Japanese", re.compile(r'\bJap(?:anese)?\b',                   re.IGNORECASE)),
    ("Korean",   re.compile(r'\bKor(?:ean)?\b',                     re.IGNORECASE)),
    ("Chinese",  re.compile(r'\bChi(?:nese)?\b',                    re.IGNORECASE)),
    ("Subs",     re.compile(r'\bSubs?(?:titled|s)?\b',              re.IGNORECASE)),
    ("Dub",      re.compile(r'\bDubbed?\b',                         re.IGNORECASE)),
    ("ESub",     re.compile(r'\bE[-\s]?Sub\b',                      re.IGNORECASE)),
]

# Secondary format tokens (only added if not already covered above)
_AUDIO_FORMAT = [
    ("AAC",  re.compile(r'\bAAC\d?(?:\.\d)?\b',  re.IGNORECASE)),
    ("AC3",  re.compile(r'\bAC[-\s]?3\b',         re.IGNORECASE)),
    ("EAC3", re.compile(r'\bEAC[-\s]?3\b',        re.IGNORECASE)),
    ("DTS",  re.compile(r'\bDTS(?:-HD)?\b',        re.IGNORECASE)),
    ("FLAC", re.compile(r'\bFLAC\b',               re.IGNORECASE)),
    ("5.1",  re.compile(r'\b5\.1\b')),
    ("7.1",  re.compile(r'\b7\.1\b')),
    ("2.0",  re.compile(r'\b2\.0\b')),
    ("Atmos",re.compile(r'\bAtmos\b',              re.IGNORECASE)),
]


def extract_audio_info(filename: str) -> str | None:
    if not filename:
        return None
    norm = _normalise(filename)
    found: list[str] = []

    for label, pat in _AUDIO_PRIORITY:
        if pat.search(norm) or pat.search(filename):
            if label not in found:
                found.append(label)

    for label, pat in _AUDIO_FORMAT:
        if pat.search(norm) or pat.search(filename):
            if label not in found:
                found.append(label)

    return " ".join(found) if found else None


# ─────────────────────────────────────────────────────────────────────────────
#  QUALITY EXTRACTION
# ─────────────────────────────────────────────────────────────────────────────
_QUALITY_PATS = [
    re.compile(r'\b(4320p?|2160p?|1440p?|1080p?|720p?|576p?|480p?|360p?|240p?)\b', re.IGNORECASE),
    re.compile(r'\b(4[kK]|2[kK]|UHD|FHD)\b',                                        re.IGNORECASE),
    re.compile(r'\b(WEB-?DL|WEBRip|WEB-Rip|BluRay|Blu-Ray|BDRip|BRRip|HDRip|HDTV|DVDRip)\b', re.IGNORECASE),
    re.compile(r'\b(HEVC|x265|x264|H\.?265|H\.?264|AVC)\b',                         re.IGNORECASE),
]

# Canonical display mapping
_QUALITY_CANONICAL = {
    "4320p": "4320p", "2160p": "2160p", "1440p": "1440p", "1080p": "1080p",
    "720p":  "720p",  "576p":  "576p",  "480p":  "480p",  "360p":  "360p",
    "240p":  "240p",
    "4k":    "4K",    "2k":    "2K",
    "4320":  "4320p", "2160":  "2160p", "1440":  "1440p", "1080":  "1080p",
    "720":   "720p",  "576":   "576p",  "480":   "480p",  "360":   "360p",
    "240":   "240p",
    "uhd":   "UHD",   "fhd":   "FHD",
    "web-dl": "WEB-DL", "webdl": "WEB-DL", "webrip": "WEBRip", "web-rip": "WEBRip",
    "bluray": "BluRay", "blu-ray": "BluRay",
    "bdrip":  "BDRip", "brrip": "BRRip", "hdrip": "HDRip",
    "dvdrip": "DVDRip", "hdtv": "HDTV",
}


def extract_quality(filename: str) -> str | None:
    if not filename:
        return None
    norm = _normalise(filename)
    for pat in _QUALITY_PATS:
        m = pat.search(norm) or pat.search(filename)
        if m:
            raw = m.group(1)
            return _QUALITY_CANONICAL.get(raw.lower(), raw)
    return None


# ─────────────────────────────────────────────────────────────────────────────
#  TITLE CLEANING
# ─────────────────────────────────────────────────────────────────────────────
# Applied in ORDER — each pass builds on the previous result
_TITLE_STRIP_RULES: list[tuple[re.Pattern, str]] = [
    # ── Release group at very START: [SubsPlease] / [Erai-raws] / etc. ────────
    (re.compile(r'^\s*\[[^\]]{1,40}\]\s*'),                   ' '),
    # ── CRC32 / hash tags: [A1B2C3D4] ─────────────────────────────────────────
    (re.compile(r'\[[0-9A-Fa-f]{6,8}\]'),                      ' '),
    # ── Quality + extra info in brackets ──────────────────────────────────────
    (re.compile(r'[\[\(][^\]\)]*?(?:4320|2160|1440|1080|720|576|480|360|240)[pP][^\]\)]*?[\]\)]', re.IGNORECASE), ' '),
    (re.compile(r'[\[\(][^\]\)]*?(?:4[kK]|UHD|FHD|WEB|BluRay|HEVC)[^\]\)]*?[\]\)]', re.IGNORECASE), ' '),
    # ── SxxExx patterns ────────────────────────────────────────────────────────
    (re.compile(r'[Ss]\d{1,2}[\s._-]?[Ee]\d{1,4}'),           ' '),
    # ── Season word ────────────────────────────────────────────────────────────
    (re.compile(r'\bSeason[\s._-]*\d{1,2}\b', re.IGNORECASE),  ' '),
    # ── Episode / EP word ──────────────────────────────────────────────────────
    (re.compile(r'\b(?:Episode|Ep(?:isode)?)[.\s_-]*\d{1,4}\b', re.IGNORECASE), ' '),
    # ── Bare Exx ───────────────────────────────────────────────────────────────
    (re.compile(r'(?<![A-Za-z])E\d{2,4}(?!\d)'),               ' '),
    # ── Broad quality label ────────────────────────────────────────────────────
    (_QUALITY_LABEL_RE,                                          ' '),
    # ── HDR / colour metadata ─────────────────────────────────────────────────
    (re.compile(r'\b(?:HDR(?:10\+?)?|SDR|HLG|DV|DoVi)\b', re.IGNORECASE), ' '),
    # ── Year ───────────────────────────────────────────────────────────────────
    (_YEAR_RE,                                                   ' '),
    # ── Audio info ─────────────────────────────────────────────────────────────
    (re.compile(r'\b(?:Multi|Dual|Tri)(?:[-\s]?audio)?\b', re.IGNORECASE), ' '),
    (re.compile(r'\b(?:Hindi|Tamil|Telugu|Malayalam|Bengali|English|Eng|Japanese|Jap|Korean|Chinese)\b', re.IGNORECASE), ' '),
    (re.compile(r'\b(?:Subs?|Dubbed?|ESub)\b', re.IGNORECASE),  ' '),
    # ── Release tags at END: -GroupName ────────────────────────────────────────
    (re.compile(r'[-_][A-Za-z0-9]{2,20}$'),                     ' '),
    # ── @ channel handles ──────────────────────────────────────────────────────
    (re.compile(r'@\S+'),                                        ' '),
    # ── Part / Cour / Arc numbers ──────────────────────────────────────────────
    (re.compile(r'\b(?:Part|Cour|Arc|Chapter)[.\s_-]*(?:\d{1,2}|[IVXivx]{1,5}|one|two|three|four|five)\b', re.IGNORECASE), ' '),
    # ── Leftover brackets ──────────────────────────────────────────────────────
    (re.compile(r'[\[\]\(\)\{\}]'),                              ' '),
]


def clean_title(filename: str) -> str:
    """
    Strip all non-title content and return a clean show/movie name.
    Input: raw filename (with or without extension).
    """
    if not filename:
        return ""

    # Remove extension
    text = re.sub(r'\.[a-zA-Z0-9]{2,5}$', '', filename)

    # Replace separators used as spaces first
    text = _normalise(text)

    # Apply all strip rules in order
    for pat, repl in _TITLE_STRIP_RULES:
        text = pat.sub(repl, text)

    # Replace underscores / dots still in the string
    text = re.sub(r'[._]', ' ', text)

    # Collapse spaces and dashes
    text = re.sub(r'\s{2,}', ' ', text)
    text = re.sub(r'\s*-\s*$', '', text)
    text = re.sub(r'^\s*-\s*', '', text)

    # Strip edge junk
    text = text.strip(' .-_')

    # Fix capitalisation if title looks like ALL CAPS or all lower
    if text and (text.isupper() or text.islower()):
        text = text.title()

    return text


# ─────────────────────────────────────────────────────────────────────────────
#  FORMAT TEMPLATE APPLICATION
# ─────────────────────────────────────────────────────────────────────────────
def apply_format_template(template: str, source_text: str) -> str:
    """
    Replace {title} {season} {episode} {quality} {audio} in template.
    Non-placeholder text is preserved verbatim.
    Empty brackets and extra spaces are cleaned up after substitution.
    """
    src  = re.sub(r'\.[a-zA-Z0-9]{2,5}$', '', source_text)

    ep   = extract_episode_number(src)
    sea  = extract_season_number(src)
    aud  = extract_audio_info(src)
    qua  = extract_quality(src)
    tit  = clean_title(src)

    ep_s  = str(ep).zfill(2)  if ep  is not None else "01"
    sea_s = str(sea).zfill(2) if sea is not None else "01"
    aud_s = aud or ""
    qua_s = qua or ""

    res = template
    res = re.sub(r'\{title\}',   tit,   res, flags=re.IGNORECASE)
    res = re.sub(r'\{season\}',  sea_s, res, flags=re.IGNORECASE)
    res = re.sub(r'\{episode\}', ep_s,  res, flags=re.IGNORECASE)
    res = re.sub(r'\{quality\}', qua_s, res, flags=re.IGNORECASE)
    res = re.sub(r'\{audio\}',   aud_s, res, flags=re.IGNORECASE)

    # Clean empty bracket pairs that result from empty substitutions
    for _ in range(3):                      # repeat to handle nested empties
        res = re.sub(r'\[\s*\]', '', res)
        res = re.sub(r'\(\s*\)', '', res)
        res = re.sub(r'\{\s*\}', '', res)
        res = re.sub(r'\s{2,}',  ' ', res)

    return res.strip(' .-')


# ─────────────────────────────────────────────────────────────────────────────
#  CAPTION TEMPLATE APPLICATION
# ─────────────────────────────────────────────────────────────────────────────
def apply_caption_template(
    template: str,
    filename: str,
    source_text: str,
    filesize: int = 0,
    duration: float = 0.0,
) -> str:
    """
    Supported placeholders:
      {filename} {title} {season} {episode} {quality} {audio}
      {filesize} {duration}
    """
    src   = re.sub(r'\.[a-zA-Z0-9]{2,5}$', '', source_text)

    ep    = extract_episode_number(src)
    sea   = extract_season_number(src)
    aud   = extract_audio_info(src)
    qua   = extract_quality(src)
    tit   = clean_title(src)

    res   = template
    res   = res.replace("{filename}",  filename)
    res   = res.replace("{title}",     tit or "")
    res   = res.replace("{season}",    str(sea or 1).zfill(2))
    res   = res.replace("{episode}",   str(ep  or 1).zfill(2))
    res   = res.replace("{quality}",   qua or "")
    res   = res.replace("{audio}",     aud or "")
    res   = res.replace("{filesize}",  humanbytes(filesize))
    res   = res.replace("{duration}",  convert(duration) if duration else "N/A")

    return res


# ─────────────────────────────────────────────────────────────────────────────
#  FFPROBE DURATION
# ─────────────────────────────────────────────────────────────────────────────
async def detect_duration(file_path: str) -> float:
    ffprobe = shutil.which("ffprobe")
    if not ffprobe:
        return 0.0
    cmd = [
        ffprobe, "-v", "quiet",
        "-print_format", "json",
        "-show_format",
        file_path,
    ]
    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=30)
        info = json.loads(stdout.decode())
        return float(info.get("format", {}).get("duration", 0))
    except Exception as e:
        logger.debug(f"detect_duration failed for {file_path}: {e}")
        return 0.0


# ─────────────────────────────────────────────────────────────────────────────
#  NEW USER LOG
# ─────────────────────────────────────────────────────────────────────────────
async def send_log(bot, user) -> None:
    if not Config.LOG_CHANNEL:
        return
    now = datetime.utcnow().strftime("%d %B %Y • %H:%M UTC")
    try:
        await bot.send_message(
            Config.LOG_CHANNEL,
            f"<b>── New User ──</b>\n"
            f"User : {user.mention}\n"
            f"ID   : <code>{user.id}</code>\n"
            f"Nick : @{user.username or 'N/A'}\n"
            f"Time : {now}",
        )
    except Exception:
        pass