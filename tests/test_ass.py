"""ASS subtitle generation tests: escaping, karaoke timing, fonts."""

from __future__ import annotations

from abikaraoke.ass import (
    KaraokeStyle,
    ass_color,
    ass_timestamp,
    build_ass,
    escape_ass_text,
    write_ass,
)
from abikaraoke.lrc import parse_lrc, parse_plain


def test_escape_ass_text_handles_override_braces_and_backslashes():
    assert escape_ass_text(r"a\b") == r"a\\b"
    assert escape_ass_text("{evil}") == r"\{evil\}"
    assert escape_ass_text("two\nlines") == r"two\Nlines"


def test_escape_keeps_unicode_intact():
    assert escape_ass_text("കാതൽ") == "കാതൽ"


def test_ass_color_is_bgr_with_alpha():
    assert ass_color("#FFD54A") == "&H004AD5FF"
    assert ass_color("#000000", 0x80) == "&H80000000"


def test_ass_timestamp_format():
    assert ass_timestamp(0) == "0:00:00.00"
    assert ass_timestamp(62.5) == "0:01:02.50"
    assert ass_timestamp(3725.25) == "1:02:05.25"


def test_build_ass_emits_karaoke_runs_in_centiseconds():
    lyrics = parse_lrc(
        "[00:01.00]<00:01.00>Aadiyile <00:01.50>sedhi <00:02.00>kettadha\n"
    )
    ass = build_ass(lyrics, KaraokeStyle())
    assert "[Script Info]" in ass
    assert "PlayResX: 1920" in ass
    assert "Dialogue: 0,0:00:01.00" in ass
    assert r"{\kf50}Aadiyile" in ass
    assert r"{\kf50}sedhi" in ass


def test_build_ass_uses_malayalam_style_for_malayalam_lines():
    lyrics = parse_plain("കാതൽ എന്നും കാതൽ\n")
    lyrics.lines[0].start, lyrics.lines[0].end = 1.0, 4.0
    ass = build_ass(lyrics, KaraokeStyle())
    assert "Style: KaraokeML,Noto Sans Malayalam" in ass
    assert ",KaraokeML," in ass


def test_build_ass_skips_zero_length_lines():
    lyrics = parse_plain("untimed line\n")
    ass = build_ass(lyrics, KaraokeStyle())
    assert "Dialogue:" not in ass


def test_next_line_style_is_emitted_when_enabled():
    lyrics = parse_lrc("[00:01.00]first\n[00:05.00]second\n")
    ass = build_ass(lyrics, KaraokeStyle(next_line=True))
    assert "Style: NextLine" in ass
    assert "Dialogue: 1," in ass


def test_write_ass_roundtrip(tmp_path):
    lyrics = parse_lrc("[00:01.00]hello\n")
    target = write_ass(tmp_path / "out.ass", lyrics, KaraokeStyle())
    text = target.read_text(encoding="utf-8")
    assert "Dialogue: 0" in text
    assert "hello" in text
