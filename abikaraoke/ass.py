"""ASS subtitle generation with safe escaping and karaoke fill tags."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional

from .models import LyricLine, Lyrics

MALAYALAM_RE = re.compile(r"[\u0D00-\u0D7F]")
_DEFAULT_FONT = "Arial"
_MALAYALAM_FONT = "Noto Sans Malayalam"


def ass_color(hex_rgb: str, alpha: int = 0) -> str:
    """Convert ``#RRGGBB`` to ASS ``&HAABBGGRR``."""

    value = (hex_rgb or "").strip().lstrip("#")
    if len(value) == 3:
        value = "".join(ch * 2 for ch in value)
    if len(value) != 6:
        value = "FFFFFF"
    try:
        red, green, blue = int(value[0:2], 16), int(value[2:4], 16), int(value[4:6], 16)
    except ValueError:
        red = green = blue = 255
    return f"&H{alpha:02X}{blue:02X}{green:02X}{red:02X}"


def escape_ass_text(text: str) -> str:
    """Escape user lyric text so it cannot inject ASS override blocks.

    ``{``/``}`` would open/close an override block and ``\\N`` would become a
    line break, so both are neutralised.  Displayed text is otherwise preserved.
    """

    text = (text or "").replace("\r\n", "\n").replace("\r", "\n")
    text = text.replace("\\", "\\\\")
    text = text.replace("{", "\\{").replace("}", "\\}")
    text = text.replace("\n", "\\N")
    return text


def ass_timestamp(seconds: float) -> str:
    seconds = max(0.0, float(seconds))
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    whole = int(seconds % 60)
    centis = int(round((seconds - int(seconds)) * 100))
    if centis == 100:
        centis = 0
        whole += 1
    if whole == 60:
        whole = 0
        minutes += 1
    return f"{hours}:{minutes:02d}:{whole:02d}.{centis:02d}"


@dataclass
class KaraokeStyle:
    width: int = 1920
    height: int = 1080
    font: str = _DEFAULT_FONT
    font_size: int = 64
    primary: str = "#FFFFFF"      # upcoming / base
    sung: str = "#FFD54A"         # karaoke fill colour
    outline: str = "#000000"
    back: str = "#000000"
    bold: bool = False
    boxed: bool = False
    position: str = "bottom"      # bottom | middle | top
    margin_v: int = 80
    fade_ms: int = 140
    next_line: bool = False
    next_line_scale: float = 0.62
    malayalam_font: str = _MALAYALAM_FONT

    @property
    def alignment(self) -> int:
        return {"bottom": 2, "middle": 5, "top": 8}.get(self.position, 2)


def _style_line(name: str, style: KaraokeStyle, *, font: Optional[str] = None, size: Optional[int] = None,
                primary: Optional[str] = None, alignment: Optional[int] = None) -> str:
    border = 3 if style.boxed else 1
    return (
        f"Style: {name},{font or style.font},{size or style.font_size},"
        f"{ass_color(primary or style.primary)},"
        f"{ass_color(style.sung)},"
        f"{ass_color(style.outline)},"
        f"{ass_color(style.back, 0x60 if style.boxed else 0x80)},"
        f"{-1 if style.bold else 0},0,0,0,100,100,0,0,{border},3,1,"
        f"{alignment or style.alignment},80,80,{style.margin_v},1"
    )


def _karaoke_body(line: LyricLine) -> str:
    """Build ``{\\kf<cs>}word`` runs for smooth per-word highlighting."""

    if not line.words:
        return escape_ass_text(line.text)

    parts: List[str] = []
    cursor = line.start
    for word in line.words:
        start = max(line.start, word.start)
        gap = max(0.0, start - cursor)
        if gap > 0.02:
            parts.append(f"{{\\kf{int(round(gap * 100))}}}")
        duration = max(0.05, word.end - start)
        parts.append(f"{{\\kf{int(round(duration * 100))}}}{escape_ass_text(word.text)} ")
        cursor = start + duration
    return "".join(parts).rstrip()


def build_ass(lyrics: Lyrics, style: KaraokeStyle) -> str:
    header = [
        "[Script Info]",
        "ScriptType: v4.00+",
        f"PlayResX: {style.width}",
        f"PlayResY: {style.height}",
        "WrapStyle: 0",
        "ScaledBorderAndShadow: yes",
        "YCbCr Matrix: TV.709",
        "",
        "[V4+ Styles]",
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, "
        "Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, "
        "Shadow, Alignment, MarginL, MarginR, MarginV, Encoding",
        _style_line("Karaoke", style),
        _style_line("KaraokeML", style, font=style.malayalam_font),
        _style_line(
            "NextLine", style,
            size=max(18, int(style.font_size * style.next_line_scale)),
            primary="#C8C8C8",
            alignment=2,
        ),
        "",
        "[Events]",
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text",
    ]

    events: List[str] = []
    lines = lyrics.sorted_lines()
    for index, line in enumerate(lines):
        if not line.text.strip() or line.end <= line.start:
            continue
        is_ml = bool(MALAYALAM_RE.search(line.text))
        style_name = "KaraokeML" if is_ml else "Karaoke"
        body = _karaoke_body(line)
        fade = f"{{\\fad({max(0, style.fade_ms // 2)},{max(0, style.fade_ms // 2)})}}" if style.fade_ms else ""
        events.append(
            f"Dialogue: 0,{ass_timestamp(line.start)},{ass_timestamp(line.end)},{style_name},,0,0,0,,"
            f"{fade}{body}"
        )

        if style.next_line and index + 1 < len(lines):
            following = lines[index + 1]
            if following.text.strip():
                events.append(
                    f"Dialogue: 1,{ass_timestamp(line.start)},{ass_timestamp(line.end)},NextLine,,0,0,0,,"
                    f"{escape_ass_text(following.text)}"
                )

    return "\n".join(header + events) + "\n"


def write_ass(path: Path, lyrics: Lyrics, style: KaraokeStyle) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(build_ass(lyrics, style), encoding="utf-8")
    return path
