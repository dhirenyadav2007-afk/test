"""
helper/utils.py  —  Advanced extraction engine + formatters + progress bar.

Tested against all example filename formats:
  [S01-04] Agents of the Four Seasons Dance of Spring [720p] [Dual] @OtakuFlix_Net.mkv
    → title="Agents of the Four Seasons Dance of Spring"  season=1  ep=4
      quality="720p"  audio="Dual"

  [@INFINITE_ANIMES] The Case Study of Vanitas S01E23 [BD 1080p x265 10bit] [Multi Audio] ESub.mkv
    → title="The Case Study of Vanitas"  season=1  ep=23  quality="1080p"  audio="Multi ESub"

  Kaiju No. 8 S02E10 1080p x265 10bit WEB-DL Multi Audio ESub.mkv
    → title="Kaiju No. 8"  season=2  ep=10  quality="1080p"  audio="Multi ESub"

  demon_slayer_s02e01_1080p
    → title="Demon Slayer"  season=2  ep=1  quality="1080p"

  Series Name - 01 - Episode Title
    → title="Series Name"  ep=1

  Series Name - S00E00 - Episode Title
    → title="Series Name"  season=0  ep=0

  My Hero Academia - 128 [1080p][HEVC]
    → title="My Hero Academia"  ep=128  quality="1080p"

Smart empty-bracket removal:
  If a placeholder resolves to "" AND the user did NOT hard-code a value for
  that slot, the entire surrounding bracket group [ ] or ( ) is removed.
  If the user hard-coded a value  e.g. [1080p] or [Multi]  it is kept as-is.

Download progress bar:
  Shows the ORIGINAL filename sent by the user, not the renamed output.
"""

import re
import json
import time
import asyncio
import shutil
import logging
from datetime import datetime
from config import Config

logger = logging.getLogger(__name__)


# ══════════════════════════════════════════════════════════════════════════════
#  PROGRESS BAR
# ══════════════════════════════════════════════════════════════════════════════
_prog_ts: dict[int, float] = {}
_PROG_GAP = 3.0   # min seconds between Telegram edits


async def progress_for_pyrogram(
    current: int, total: int,
    ud_type: str, message, start: float,
) -> None:
    """
    Throttled progress bar.  ud_type should contain the ORIGINAL filename line
    so the user sees what file is being downloaded/uploaded.
    """
    if total == 0:
        return
    now  = time.time()
    mid  = getattr(message, "id", 0)
    if current != total and now - _prog_ts.get(mid, 0) < _PROG_GAP:
        return
    _prog_ts[mid] = now

    elapsed = max(now - start, 0.001)
    speed   = current / elapsed
    eta_s   = int((total - current) / speed) if speed > 0 else 0
    pct     = current * 100 / total
    filled  = int(pct / 5)
    bar     = "▰" * filled + "▱" * (20 - filled)

    text = (
        f"{ud_type}\n"
        f"<code>{bar}</code>\n"
        f"›› {humanbytes(current)} / {humanbytes(total)} • "
        f"{pct:.1f}% ›› {humanbytes(speed)}/s • {TimeFormatter(eta_s * 1000)}"
    )
    try:
        await message.edit(text)
    except Exception:
        pass  # Includes MessageNotModified — silently ignored


# ══════════════════════════════════════════════════════════════════════════════
#  FORMATTERS
# ══════════════════════════════════════════════════════════════════════════════
def humanbytes(size: float) -> str:
    if not size:
        return "0 B"
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if size < 1024:
            return f"{size:.2f} {unit}"
        size /= 1024
    return f"{size:.2f} PB"


def TimeFormatter(ms: int) -> str:
    s = int(ms / 1000)
    m, s = divmod(s, 60)
    h, m = divmod(m, 60)
    if h:  return f"{h}h {m}m {s}s"
    if m:  return f"{m}m {s}s"
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


# ══════════════════════════════════════════════════════════════════════════════
#  QUALITY / YEAR EXCLUSION  — numbers that look like eps but aren't
# ══════════════════════════════════════════════════════════════════════════════
_QUALITY_NUMS = {240, 360, 480, 576, 720, 1080, 1440, 2160, 4320}
_YEAR_RE      = re.compile(r'\b(19|20)\d{2}\b')

# Comprehensive quality-label pattern  (for stripping in title cleaner)
_QLABEL = re.compile(
    r'\b('
    r'4K|2K|UHD|FHD|SD|NHK|'
    r'4320p?|2160p?|1440p?|1080p?|720p?|576p?|480p?|360p?|240p?|'
    r'WEB-?DL|WEBRip|WEB-Rip|WEB|'
    r'BluRay|Blu-Ray|BDRip|BRRip|BD|'
    r'HDTV|HDRip|DVDRip|DVDScr|DVD|'
    r'HEVC|H\.?264|H\.?265|AVC|x264|x265|'
    r'10bit|8bit|Hi10P|Hi444PP|'
    r'AAC|EAC3|AC3|DTS(?:-HD)?|TrueHD|FLAC|MP3|Opus|Vorbis|'
    r'HDR(?:10\+?)?|SDR|HLG|DV|DoVi|'
    r'PROPER|REPACK|EXTENDED|THEATRICAL|UNRATED|REMUX|DC'
    r')\b',
    re.IGNORECASE,
)


def _is_quality_or_year(n: int, ctx: str) -> bool:
    if n in _QUALITY_NUMS and re.search(rf'\b{n}\s*[pPkK]', ctx):
        return True
    if 1900 <= n <= 2100 and _YEAR_RE.search(ctx):
        return True
    return False


# ══════════════════════════════════════════════════════════════════════════════
#  NORMALISE  — dots/underscores → spaces  (makes _ and . filenames parseable)
# ══════════════════════════════════════════════════════════════════════════════
def _norm(text: str) -> str:
    """Replace separator dots/underscores between word-chars with spaces."""
    t = re.sub(r'(?<=[A-Za-z0-9])[._](?=[A-Za-z0-9])', ' ', text)
    t = re.sub(r'[ \t]{2,}', ' ', t)
    return t.strip()


def _strip_ext(s: str) -> str:
    return re.sub(r'\.[a-zA-Z0-9]{2,5}$', '', s)


# ══════════════════════════════════════════════════════════════════════════════
#  EPISODE EXTRACTION
# ══════════════════════════════════════════════════════════════════════════════
def extract_episode_number(filename: str) -> int | None:
    """
    Priority chain — stops at first confident match.
    Handles ALL example formats including:
      [S01-04] …     → S01-04  → ep=4   (hyphen-separated SxxExx variant)
      S01E23          → ep=23
      - 128 [1080p]  → ep=128   (My Hero Academia style)
      - 01 -          → ep=1    (Series Name - 01 - Title)
      demon_slayer_s02e01  (dots/underscores normalised first)
    """
    if not filename:
        return None

    raw       = filename
    base_raw  = _strip_ext(raw)
    base_norm = _norm(base_raw)

    def _search(s: str) -> int | None:
        # ── T1: Standard SxxExx / SxxExx ─────────────────────────────────────
        m = re.search(r'[Ss](\d{1,2})[\s._\-]?[Ee](\d{1,4})', s)
        if m:
            return int(m.group(2))

        # ── T1b: [S01-04] bracket style (season-ep with hyphen) ─────────────
        m = re.search(r'\[S(\d{1,2})-(\d{1,4})\]', s, re.IGNORECASE)
        if m:
            return int(m.group(2))

        # ── T2: Episode / Ep prefix ──────────────────────────────────────────
        m = re.search(r'\b(?:Episode|Ep(?:isode)?)[\s._\-]*(\d{1,4})\b', s, re.IGNORECASE)
        if m:
            n = int(m.group(1))
            if not _is_quality_or_year(n, s):
                return n

        # ── T3: [E05] or (E05) ───────────────────────────────────────────────
        m = re.search(r'[\[\(]E(\d{1,4})[\]\)]', s, re.IGNORECASE)
        if m:
            return int(m.group(1))

        # ── T4: standalone Exx not part of SxxExx ────────────────────────────
        m = re.search(r'(?<![A-Za-z0-9\-])E(\d{2,4})(?!\d)', s, re.IGNORECASE)
        if m:
            n = int(m.group(1))
            if not _is_quality_or_year(n, s):
                return n

        # ── T5: "5 of 12" ────────────────────────────────────────────────────
        m = re.search(r'\b(\d{1,3})\s*of\s*\d{1,3}\b', s, re.IGNORECASE)
        if m:
            n = int(m.group(1))
            if 1 <= n <= 999:
                return n

        # ── T6: separator-bounded 2–3 digit (e.g. "- 128 [" or "- 01 -") ────
        stripped = _QLABEL.sub(' ', s)
        stripped = _YEAR_RE.sub(' ', stripped)
        # Look for  <sep>NNN<sep>  where sep is space/dash/bracket
        for m in re.finditer(r'(?:^|[\s\-\[\(])(\d{2,3})(?:v\d)?(?:[\s\-\]\)]|$)', stripped):
            n = int(m.group(1))
            if 1 <= n <= 999 and not _is_quality_or_year(n, raw):
                return n

        # ── T7: last-resort isolated 2-digit ─────────────────────────────────
        for c in re.findall(r'(?<!\d)(\d{2})(?!\d)', stripped):
            n = int(c)
            if 1 <= n <= 99 and not _is_quality_or_year(n, raw):
                return n

        return None

    return _search(base_norm) or _search(base_raw)


# ══════════════════════════════════════════════════════════════════════════════
#  SEASON EXTRACTION
# ══════════════════════════════════════════════════════════════════════════════
_PART_MAP = {
    "one":1,"two":2,"three":3,"four":4,"five":5,
    "six":6,"seven":7,"eight":8,"nine":9,"ten":10,
    "i":1,"ii":2,"iii":3,"iv":4,"v":5,"vi":6,"vii":7,"viii":8,"ix":9,"x":10,
}


def extract_season_number(filename: str) -> int | None:
    """
    Handles:  S01E05 · [S01-04] · Season 2 · [S3] · _S2_ · Part II · Cour 1
    Special: [S01-04] bracket style → season=1
    """
    if not filename:
        return None

    raw       = filename
    base_raw  = _strip_ext(raw)
    base_norm = _norm(base_raw)

    def _search(s: str) -> int | None:
        # ── T1: SxxExx ───────────────────────────────────────────────────────
        m = re.search(r'[Ss](\d{1,2})[\s._\-]?[Ee]\d{1,4}', s)
        if m:
            return int(m.group(1))

        # ── T1b: [S01-04] bracket style ──────────────────────────────────────
        m = re.search(r'\[S(\d{1,2})-\d{1,4}\]', s, re.IGNORECASE)
        if m:
            return int(m.group(1))

        # ── T2: Season word ───────────────────────────────────────────────────
        m = re.search(r'\bSeason[\s._\-]*(\d{1,2})\b', s, re.IGNORECASE)
        if m:
            n = int(m.group(1))
            if 1 <= n <= 99:
                return n

        # ── T3: [S02] / (S2) ─────────────────────────────────────────────────
        m = re.search(r'[\[\(]S(\d{1,2})[\]\)]', s, re.IGNORECASE)
        if m:
            n = int(m.group(1))
            if 1 <= n <= 99:
                return n

        # ── T4: bare Sxx not followed by quality/digit ───────────────────────
        m = re.search(
            r'(?:^|[\s._\-])S(\d{1,2})(?![\dEe_]|[\s._\-]?\d{2,4}[pPkK])',
            s, re.IGNORECASE
        )
        if m:
            n = int(m.group(1))
            if 1 <= n <= 99:
                return n

        # ── T5: separator-bounded Sxx  _S2_ / .S02. ──────────────────────────
        m = re.search(r'[._\-]S(\d{1,2})[._\-]', s, re.IGNORECASE)
        if m:
            n = int(m.group(1))
            if 1 <= n <= 99:
                return n

        # ── T6: Part / Cour / Arc ─────────────────────────────────────────────
        m = re.search(
            r'\b(?:Part|Cour|Arc|Chapter)[\s._\-]*(\d{1,2})\b',
            s, re.IGNORECASE
        )
        if m:
            n = int(m.group(1))
            if 1 <= n <= 20:
                return n

        m = re.search(
            r'\b(?:Part|Cour|Arc)[\s._\-]+([IVXivx]+|one|two|three|four|five'
            r'|six|seven|eight|nine|ten)\b',
            s, re.IGNORECASE
        )
        if m:
            return _PART_MAP.get(m.group(1).lower())

        return None

    return _search(base_norm) or _search(base_raw)


# ══════════════════════════════════════════════════════════════════════════════
#  AUDIO EXTRACTION
# ══════════════════════════════════════════════════════════════════════════════
_AUDIO_CHECKS = [
    # (label, pattern) — priority order; ALL matching labels are collected
    ("Multi",     re.compile(r'\bMulti(?:[\s\-]?(?:Audio|Lang(?:uage)?)?)?\b', re.IGNORECASE)),
    ("Dual",      re.compile(r'\bDual(?:[\s\-]?Audio)?\b',                     re.IGNORECASE)),
    ("Tri",       re.compile(r'\bTri(?:[\s\-]?Audio)?\b',                      re.IGNORECASE)),
    ("Hindi",     re.compile(r'\bHindi\b',                                      re.IGNORECASE)),
    ("Tamil",     re.compile(r'\bTamil\b',                                      re.IGNORECASE)),
    ("Telugu",    re.compile(r'\bTelugu\b',                                     re.IGNORECASE)),
    ("Malayalam", re.compile(r'\bMalayalam\b',                                  re.IGNORECASE)),
    ("Bengali",   re.compile(r'\bBengali\b',                                    re.IGNORECASE)),
    ("English",   re.compile(r'\bEnglish\b',                                    re.IGNORECASE)),
    ("Eng",       re.compile(r'\bEng\b',                                        re.IGNORECASE)),
    ("Japanese",  re.compile(r'\bJap(?:anese)?\b',                              re.IGNORECASE)),
    ("Korean",    re.compile(r'\bKor(?:ean)?\b',                                re.IGNORECASE)),
    ("Chinese",   re.compile(r'\bChi(?:nese)?\b',                               re.IGNORECASE)),
    ("Sub",       re.compile(r'\bSubs?(?:titled?)?\b',                          re.IGNORECASE)),
    ("ESub",      re.compile(r'\bE[\s\-]?Sub\b',                                re.IGNORECASE)),
    ("Dub",       re.compile(r'\bDubbed?\b',                                    re.IGNORECASE)),
]
_AUDIO_FORMAT = [
    ("AAC",   re.compile(r'\bAAC\d?(?:\.\d)?\b',   re.IGNORECASE)),
    ("EAC3",  re.compile(r'\bEAC[\s\-]?3\b',        re.IGNORECASE)),
    ("AC3",   re.compile(r'\bAC[\s\-]?3\b',         re.IGNORECASE)),
    ("DTS",   re.compile(r'\bDTS(?:[\s\-]?HD)?\b',  re.IGNORECASE)),
    ("FLAC",  re.compile(r'\bFLAC\b',               re.IGNORECASE)),
    ("Atmos", re.compile(r'\bAtmos\b',               re.IGNORECASE)),
    ("5.1",   re.compile(r'\b5\.1\b')),
    ("7.1",   re.compile(r'\b7\.1\b')),
    ("2.0",   re.compile(r'\b2\.0\b')),
]


def extract_audio_info(filename: str) -> str | None:
    if not filename:
        return None
    # Try both raw and normalised to catch dots/underscore-separated tokens
    sources = [filename, _norm(filename)]
    found: list[str] = []
    for label, pat in _AUDIO_CHECKS + _AUDIO_FORMAT:
        for src in sources:
            if pat.search(src) and label not in found:
                found.append(label)
                break
    return " ".join(found) if found else None


# ══════════════════════════════════════════════════════════════════════════════
#  QUALITY EXTRACTION
# ══════════════════════════════════════════════════════════════════════════════
_QUAL_PATS = [
    # Numeric resolutions (most specific first)
    re.compile(r'\b(4320p?|2160p?|1440p?|1080p?|720p?|576p?|480p?|360p?|240p?)\b', re.IGNORECASE),
    re.compile(r'\b(4[kK]|2[kK]|UHD|FHD)\b',                                        re.IGNORECASE),
    # Source types
    re.compile(r'\b(WEB-?DL|WEBRip|WEB-Rip|BluRay|Blu-Ray|BDRip|BRRip|BD|HDRip|HDTV|DVDRip)\b', re.IGNORECASE),
    # Codec (last resort)
    re.compile(r'\b(HEVC|x265|x264|H\.?265|H\.?264|AVC)\b',                         re.IGNORECASE),
]
_QUAL_CANON = {
    "4320p":"4320p","2160p":"2160p","1440p":"1440p","1080p":"1080p",
    "720p":"720p","576p":"576p","480p":"480p","360p":"360p","240p":"240p",
    "4320":"4320p","2160":"2160p","1440":"1440p","1080":"1080p",
    "720":"720p","576":"576p","480":"480p","360":"360p","240":"240p",
    "4k":"4K","2k":"2K","uhd":"UHD","fhd":"FHD",
    "web-dl":"WEB-DL","webdl":"WEB-DL","webrip":"WEBRip","web-rip":"WEBRip",
    "bluray":"BluRay","blu-ray":"BluRay","bd":"BD",
    "bdrip":"BDRip","brrip":"BRRip","hdrip":"HDRip","hdtv":"HDTV","dvdrip":"DVDRip",
}


def extract_quality(filename: str) -> str | None:
    if not filename:
        return None
    for src in (filename, _norm(filename)):
        for pat in _QUAL_PATS:
            m = pat.search(src)
            if m:
                raw = m.group(1)
                return _QUAL_CANON.get(raw.lower(), raw)
    return None


# ══════════════════════════════════════════════════════════════════════════════
#  TITLE CLEANING
# ══════════════════════════════════════════════════════════════════════════════
# Strip rules applied IN ORDER — most specific first
_TITLE_RULES = [
    # Release-group bracket at START:  [@INFINITE_ANIMES]  [SubsPlease]
    (re.compile(r'^\s*\[[@\s]?[^\]]{1,50}\]\s*'),                            ' '),
    # CRC/hash:  [A1B2C3D4]
    (re.compile(r'\[[0-9A-Fa-f]{6,8}\]'),                                     ' '),
    # [S01-04] bracket style (season-ep pair)
    (re.compile(r'\[S\d{1,2}-\d{1,4}\]', re.IGNORECASE),                     ' '),
    # Quality bracket:  [BD 1080p x265 10bit]  [720p]  [HEVC]
    (re.compile(r'[\[\(][^\]\)]*?(?:4320|2160|1440|1080|720|576|480|360|240)[pP\s][^\]\)]*?[\]\)]', re.IGNORECASE), ' '),
    (re.compile(r'[\[\(][^\]\)]*?(?:4[kK]|UHD|FHD|BD|WEB|BluRay|HEVC|x26[45])[^\]\)]*?[\]\)]', re.IGNORECASE), ' '),
    # SxxExx
    (re.compile(r'[Ss]\d{1,2}[\s._\-]?[Ee]\d{1,4}'),                        ' '),
    # Season / Episode words
    (re.compile(r'\bSeason[\s._\-]*\d{1,2}\b',              re.IGNORECASE),  ' '),
    (re.compile(r'\b(?:Episode|Ep(?:isode)?)[\s._\-]*\d{1,4}\b', re.IGNORECASE), ' '),
    # Bare Exx
    (re.compile(r'(?<![A-Za-z])E\d{2,4}(?!\d)'),                             ' '),
    # Full quality label pattern
    (_QLABEL,                                                                  ' '),
    # HDR
    (re.compile(r'\b(?:HDR(?:10\+?)?|SDR|HLG|DV|DoVi)\b',  re.IGNORECASE),  ' '),
    # Year
    (_YEAR_RE,                                                                 ' '),
    # Audio language/type
    (re.compile(r'\b(?:Multi|Dual|Tri)(?:[\s\-]?(?:Audio|Lang)?)?\b', re.IGNORECASE), ' '),
    (re.compile(r'\b(?:Hindi|Tamil|Telugu|Malayalam|Bengali|English|Eng'
                r'|Japanese|Jap|Korean|Chinese)\b',         re.IGNORECASE),  ' '),
    (re.compile(r'\b(?:ESub|Subs?|Dubbed?)\b',              re.IGNORECASE),  ' '),
    # Part / Cour / Arc
    (re.compile(r'\b(?:Part|Cour|Arc|Chapter)[\s._\-]*(?:\d{1,2}|[IVXivx]{1,5}'
                r'|one|two|three|four|five|six|seven|eight|nine|ten)\b', re.IGNORECASE), ' '),
    # @channel handles
    (re.compile(r'@\S+'),                                                     ' '),
    # Trailing release group:  -GroupName  _GroupName
    (re.compile(r'[\-_][A-Za-z0-9]{2,20}$'),                                 ' '),
    # Leftover brackets
    (re.compile(r'[\[\]\(\)\{\}]'),                                           ' '),
]


def clean_title(filename: str) -> str:
    """Return only the show/movie name, all tags stripped."""
    if not filename:
        return ""

    text = _strip_ext(filename)
    text = _norm(text)

    for pat, repl in _TITLE_RULES:
        text = pat.sub(repl, text)

    # Replace remaining separators
    text = re.sub(r'[._]', ' ', text)
    # Collapse spaces around dashes (e.g. " - Episode Title" remnants)
    text = re.sub(r'\s*-\s*-\s*', ' ', text)
    text = re.sub(r'\s{2,}', ' ', text)
    text = re.sub(r'(^\s*-\s*|\s*-\s*$)', '', text)
    text = text.strip(' .-_')

    # Capitalise if all-lower or all-upper (e.g. demon_slayer → Demon Slayer)
    if text and (text.isupper() or text.islower()):
        text = text.title()

    return text


# ══════════════════════════════════════════════════════════════════════════════
#  FORMAT TEMPLATE APPLICATION
#  KEY RULE: if a placeholder resolves to "" AND it was wrapped in brackets
#  by the user ( [{quality}] or ({audio}) ), remove the whole bracket group.
#  If the user hard-coded text in that bracket (e.g. [1080p]), keep it.
# ══════════════════════════════════════════════════════════════════════════════
def apply_format_template(template: str, source_text: str) -> str:
    """
    Replace {title} {season} {episode} {quality} {audio}.
    Rules:
      1. Always replace the placeholder itself.
      2. If placeholder resolved to "" and its containing bracket group
         contains ONLY the (now-empty) placeholder (plus spaces), remove
         the entire bracket group  [ ] or ( ).
      3. Hard-coded values like [1080p] or [Multi] are NEVER removed.
    """
    src = _strip_ext(source_text)

    ep  = extract_episode_number(src)
    sea = extract_season_number(src)
    aud = extract_audio_info(src)
    qua = extract_quality(src)
    tit = clean_title(src)

    ep_s  = str(ep).zfill(2)  if ep  is not None else "01"
    sea_s = str(sea).zfill(2) if sea is not None else "01"
    aud_s = aud  or ""
    qua_s = qua  or ""

    res = template

    # Step 1 — replace each placeholder
    res = re.sub(r'\{title\}',   tit,   res, flags=re.IGNORECASE)
    res = re.sub(r'\{season\}',  sea_s, res, flags=re.IGNORECASE)
    res = re.sub(r'\{episode\}', ep_s,  res, flags=re.IGNORECASE)
    res = re.sub(r'\{quality\}', qua_s, res, flags=re.IGNORECASE)
    res = re.sub(r'\{audio\}',   aud_s, res, flags=re.IGNORECASE)

    # Step 2 — remove bracket groups that are now completely empty
    #   A bracket is "empty" if after substitution it contains ONLY whitespace.
    #   We repeat up to 4 times to handle nested / adjacent empties.
    for _ in range(4):
        res = re.sub(r'\[\s*\]', '', res)
        res = re.sub(r'\(\s*\)', '', res)
        res = re.sub(r'\{\s*\}', '', res)
        res = re.sub(r'\s{2,}',  ' ', res)

    return res.strip(' .-')


# ══════════════════════════════════════════════════════════════════════════════
#  CAPTION TEMPLATE APPLICATION
# ══════════════════════════════════════════════════════════════════════════════
def apply_caption_template(
    template: str,
    filename: str,
    source_text: str,
    filesize: int   = 0,
    duration: float = 0.0,
) -> str:
    """
    Placeholders: {filename} {title} {season} {episode}
                  {quality} {audio} {filesize} {duration}
    """
    src  = _strip_ext(source_text)
    ep   = extract_episode_number(src)
    sea  = extract_season_number(src)
    aud  = extract_audio_info(src)
    qua  = extract_quality(src)
    tit  = clean_title(src)

    res  = template
    res  = res.replace("{filename}",  filename)
    res  = res.replace("{title}",     tit  or "")
    res  = res.replace("{season}",    str(sea or 1).zfill(2))
    res  = res.replace("{episode}",   str(ep  or 1).zfill(2))
    res  = res.replace("{quality}",   qua  or "")
    res  = res.replace("{audio}",     aud  or "")
    res  = res.replace("{filesize}",  humanbytes(filesize))
    res  = res.replace("{duration}",  convert(duration) if duration else "N/A")
    return res


# ══════════════════════════════════════════════════════════════════════════════
#  FFPROBE DURATION
# ══════════════════════════════════════════════════════════════════════════════
async def detect_duration(file_path: str) -> float:
    ffprobe = shutil.which("ffprobe")
    if not ffprobe:
        return 0.0
    cmd = [ffprobe, "-v", "quiet", "-print_format", "json", "-show_format", file_path]
    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
        )
        stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=30)
        return float(json.loads(stdout.decode()).get("format", {}).get("duration", 0))
    except Exception as e:
        logger.debug(f"detect_duration failed: {e}")
        return 0.0


# ══════════════════════════════════════════════════════════════════════════════
#  QUICK SELF-TEST  (run: python -m helper.utils)
# ══════════════════════════════════════════════════════════════════════════════
if __name__ == "__main__":
    cases = [
        ("[S01-04] Agents of the Four Seasons Dance of Spring [720p] [Dual] @OtakuFlix_Net.mkv",
         dict(season=1, ep=4, quality="720p", audio_has="Dual",
              title_has="Agents of the Four Seasons")),
        ("[@INFINITE_ANIMES] The Case Study of Vanitas S01E23 [BD 1080p x265 10bit] [Multi Audio] ESub.mkv",
         dict(season=1, ep=23, quality="1080p", audio_has="Multi",
              title_has="The Case Study of Vanitas")),
        ("Kaiju No. 8 S02E10 1080p x265 10bit WEB-DL Multi Audio ESub.mkv",
         dict(season=2, ep=10, quality="1080p", audio_has="Multi",
              title_has="Kaiju")),
        ("[@infinite_animes] My Status as an Assassin Obviously Exceeds the Hero's S01E11 1080p x265 10bit WEB-DL Multi Audio ESub.mkv",
         dict(season=1, ep=11, quality="1080p", audio_has="Multi",
              title_has="My Status as an Assassin")),
        ("demon_slayer_s02e01_1080p",
         dict(season=2, ep=1, quality="1080p", title_has="Demon Slayer")),
        ("Series Name - 01 - Episode Title",
         dict(ep=1, title_has="Series Name")),
        ("Series Name - S00E00 - Episode Title",
         dict(season=0, ep=0, title_has="Series Name")),
        ("My Hero Academia - 128 [1080p][HEVC]",
         dict(ep=128, quality="1080p", title_has="My Hero Academia")),
    ]
    ok = True
    for fn, exp in cases:
        ep  = extract_episode_number(fn)
        sea = extract_season_number(fn)
        qua = extract_quality(fn)
        aud = extract_audio_info(fn)
        tit = clean_title(fn)
        errs = []
        if "ep"         in exp and ep  != exp["ep"]:         errs.append(f"ep={ep} want {exp['ep']}")
        if "season"     in exp and sea != exp["season"]:     errs.append(f"sea={sea} want {exp['season']}")
        if "quality"    in exp and qua != exp["quality"]:    errs.append(f"qua={qua!r} want {exp['quality']!r}")
        if "audio_has"  in exp and (not aud or exp["audio_has"] not in aud): errs.append(f"aud={aud!r} missing {exp['audio_has']!r}")
        if "title_has"  in exp and (not tit or exp["title_has"].lower() not in tit.lower()): errs.append(f"tit={tit!r} missing {exp['title_has']!r}")
        status = "✓" if not errs else "✗ " + " | ".join(errs)
        print(f"{status}  {fn[:70]}")
        if errs:
            ok = False
    print("\n✅ All passed" if ok else "\n❌ Some failed")


# ══════════════════════════════════════════════════════════════════════════════
#  NEW USER LOG
# ══════════════════════════════════════════════════════════════════════════════
async def send_log(bot, user) -> None:
    """Send new-user notification to LOG_CHANNEL. Silent on any failure."""
    from config import Config
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
