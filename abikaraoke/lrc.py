"""LRC parsing and writing, including enhanced (word-timed) LRC."""

from __future__ import annotations

import re
from typing import Dict, List, Optional, Tuple

from .models import LyricLine, Lyrics, Word

_META_RE = re.compile(r"^\[(ar|ti|al|by|offset|re|ve|length):(.*)\]$", re.IGNORECASE)
_TIME_RE = re.compile(r"\[(\d{1,3}):(\d{1,2})(?:[.:](\d{1,3}))?\]")
_WORD_RE = re.compile(r"<(\d{1,3}):(\d{1,2})(?:[.:](\d{1,3}))?>")


def _to_seconds(minutes: str, seconds: str, fraction: Optional[str]) -> float:
    value = int(minutes) * 60 + int(seconds)
    if fraction:
        # LRC fractions are positional: ".5" = 0.5 s, ".50" = 0.50 s,
        # ".500" = 0.500 s.  Treating ".5" as 0.05 s silently shifted lyrics.
        value += int(fraction) / (10.0 ** len(fraction))
    return value


def parse_timestamp(text: str) -> Optional[float]:
    match = _TIME_RE.search(text)
    if not match:
        return None
    return _to_seconds(match.group(1), match.group(2), match.group(3))


def format_timestamp(seconds: float, brackets: bool = True) -> str:
    seconds = max(0.0, float(seconds))
    minutes, remainder = divmod(seconds, 60.0)
    whole = int(remainder)
    centis = int(round((remainder - whole) * 100))
    if centis == 100:
        centis = 0
        whole += 1
    if whole == 60:
        whole = 0
        minutes += 1
    body = f"{int(minutes):02d}:{whole:02d}.{centis:02d}"
    return f"[{body}]" if brackets else body


def _parse_word_tags(content: str, line_start: float, line_end: float) -> List[Word]:
    """Parse ``<mm:ss.xx>word`` enhanced-LRC tags."""

    matches = list(_WORD_RE.finditer(content))
    if not matches:
        return []

    words: List[Word] = []
    for index, match in enumerate(matches):
        start = _to_seconds(match.group(1), match.group(2), match.group(3))
        text_start = match.end()
        text_end = matches[index + 1].start() if index + 1 < len(matches) else len(content)
        text = content[text_start:text_end].strip()
        if not text:
            continue
        end = (
            _to_seconds(matches[index + 1].group(1), matches[index + 1].group(2), matches[index + 1].group(3))
            if index + 1 < len(matches)
            else max(line_end, start + 0.25)
        )
        words.append(Word(text=text, start=start, end=max(start + 0.05, end), synthetic=False))
    return words


def parse_lrc(text: str, *, source: str = "lrclib") -> Lyrics:
    """Parse standard and enhanced LRC.

    Multiple timestamps on one line (``[00:10.00][00:40.00]chorus``) are
    expanded into separate lines.  Word tags produce per-word timings.
    """

    text = (text or "").replace("\r\n", "\n").replace("\r", "\n")
    meta: Dict[str, str] = {}
    raw_entries: List[Tuple[List[float], str]] = []
    offset = 0.0

    for raw_line in text.split("\n"):
        line = raw_line.strip()
        if not line:
            continue
        meta_match = _META_RE.match(line)
        if meta_match:
            key = meta_match.group(1).lower()
            value = meta_match.group(2).strip()
            meta[key] = value
            if key == "offset":
                try:
                    offset = float(value) / 1000.0
                except ValueError:
                    offset = 0.0
            continue

        times = [m for m in _TIME_RE.finditer(line)]
        if not times:
            continue
        content = line[times[-1].end():].strip()
        stamps = [_to_seconds(m.group(1), m.group(2), m.group(3)) for m in times]
        raw_entries.append((stamps, content))

    # Sort by first timestamp so end times can be derived.
    raw_entries.sort(key=lambda item: item[0][0])
    flat: List[Tuple[float, str]] = []
    for stamps, content in raw_entries:
        for stamp in stamps:
            flat.append((stamp, content))
    flat.sort(key=lambda item: item[0])

    lines: List[LyricLine] = []
    for index, (start, content) in enumerate(flat):
        next_start = flat[index + 1][0] if index + 1 < len(flat) else start + 4.0
        end = max(start + 0.3, next_start - 0.05)
        words = _parse_word_tags(content, start, end)
        plain = _WORD_RE.sub("", content).strip()
        if words:
            start = min(start, words[0].start)
            end = max(end, words[-1].end)
        if not plain and not words:
            continue
        lines.append(
            LyricLine(
                start=max(0.0, start - offset),
                end=max(0.0, end - offset),
                text=plain,
                words=[
                    Word(text=w.text, start=max(0.0, w.start - offset), end=max(0.0, w.end - offset))
                    for w in words
                ],
                confidence=1.0 if words else 0.9,
                synthetic=False,
                source=source,
            )
        )

    return Lyrics(
        lines=lines,
        source=source,
        synced=bool(lines),
        language=meta.get("language"),
        title=meta.get("ti"),
        artist=meta.get("ar"),
        raw_lrc=text,
        warnings=[] if lines else ["LRC contained no timed lyric lines."],
    )


def parse_plain(text: str, *, source: str = "lrclib") -> Lyrics:
    """Turn untimed lyrics into lines with no timing (start=end=0)."""

    lines: List[LyricLine] = []
    for raw in (text or "").replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        stripped = raw.strip()
        if not stripped:
            continue
        lines.append(
            LyricLine(start=0.0, end=0.0, text=stripped, words=[], confidence=0.0, synthetic=True, source=source)
        )
    return Lyrics(lines=lines, source=source, synced=False, raw_lrc=text)


def spread_plain_lyrics(lyrics: Lyrics, duration: float, *, lead_in: float = 2.0, tail: float = 3.0) -> Lyrics:
    """Give untimed lyrics evenly spaced placeholder timings.

    These are explicitly marked ``synthetic`` so the UI and renderer never
    present them as measured sync.
    """

    if duration <= 0:
        raise ValueError("duration must be positive")
    lines = [ln for ln in lyrics.lines if ln.text.strip()]
    if not lines:
        return lyrics

    usable = max(1.0, duration - lead_in - tail)
    weights = [max(1, len(ln.text.split())) for ln in lines]
    total = sum(weights)
    cursor = min(lead_in, duration * 0.1)
    result: List[LyricLine] = []
    for line, weight in zip(lines, weights):
        span = usable * (weight / total)
        end = min(duration, cursor + span)
        words = _split_words_evenly(line.text, cursor, end)
        result.append(
            LyricLine(
                start=cursor,
                end=end,
                text=line.text,
                words=words,
                confidence=0.0,
                synthetic=True,
                source=line.source,
            )
        )
        cursor = end
    return Lyrics(
        lines=result,
        source=lyrics.source,
        synced=False,
        language=lyrics.language,
        title=lyrics.title,
        artist=lyrics.artist,
        raw_lrc=lyrics.raw_lrc,
        warnings=list(lyrics.warnings) + ["Timing is evenly spread (synthetic), not measured."],
    )


def _split_words_evenly(text: str, start: float, end: float) -> List[Word]:
    tokens = text.split()
    if not tokens:
        return []
    step = max(0.01, (end - start) / len(tokens))
    words: List[Word] = []
    cursor = start
    for token in tokens:
        words.append(Word(text=token, start=cursor, end=min(end, cursor + step), synthetic=True))
        cursor += step
    return words


def to_lrc(lyrics: Lyrics, *, enhanced: bool = True, include_metadata: bool = True) -> str:
    out: List[str] = []
    if include_metadata:
        if lyrics.artist:
            out.append(f"[ar:{lyrics.artist}]")
        if lyrics.title:
            out.append(f"[ti:{lyrics.title}]")
        if lyrics.language:
            out.append(f"[language:{lyrics.language}]")
        out.append("[by:ABI Karaoke]")
        out.append("")

    for line in lyrics.sorted_lines():
        stamp = format_timestamp(line.start)
        if enhanced and line.words:
            body = "".join(
                f"<{format_timestamp(word.start, brackets=False)}>{word.text} " for word in line.words
            ).rstrip()
        else:
            body = line.text
        out.append(f"{stamp}{body}")
    return "\n".join(out) + "\n"


def to_plain_text(lyrics: Lyrics) -> str:
    return "\n".join(line.text for line in lyrics.sorted_lines() if line.text.strip())
