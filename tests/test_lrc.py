"""LRC parsing / writing tests (standard + enhanced word timing)."""

from __future__ import annotations

from abikaraoke.lrc import (
    format_timestamp,
    parse_lrc,
    parse_plain,
    parse_timestamp,
    spread_plain_lyrics,
    to_lrc,
    to_plain_text,
)


def test_parse_timestamp_variants():
    assert parse_timestamp("[00:12.34]") == 12.34
    assert parse_timestamp("[01:02.5]") == 62.5
    assert parse_timestamp("[01:02:50]") == 62.5
    assert parse_timestamp("not a stamp") is None


def test_format_timestamp_roundtrip():
    assert format_timestamp(62.5) == "[01:02.50]"
    assert format_timestamp(62.5, brackets=False) == "01:02.50"


def test_parse_standard_lrc_derives_end_times():
    text = "[ar:Someone]\n[ti:Song]\n[00:01.00]first line\n[00:05.00]second line\n"
    lyrics = parse_lrc(text)
    assert lyrics.artist == "Someone"
    assert lyrics.title == "Song"
    assert lyrics.synced
    assert len(lyrics.lines) == 2
    assert lyrics.lines[0].start == 1.0
    # end is just before the next line, never overlapping
    assert 4.0 < lyrics.lines[0].end < 5.0
    assert lyrics.lines[1].start == 5.0


def test_parse_enhanced_lrc_word_tags():
    text = "[00:10.00]<00:10.00>Aadiyile <00:10.50>sedhi <00:11.00>kettadha\n"
    lyrics = parse_lrc(text)
    line = lyrics.lines[0]
    assert line.text == "Aadiyile sedhi kettadha"
    assert [w.text for w in line.words] == ["Aadiyile", "sedhi", "kettadha"]
    assert line.words[0].start == 10.0
    assert line.words[1].start == 10.5
    assert line.words[2].start == 11.0
    assert not any(w.synthetic for w in line.words)


def test_multiple_timestamps_on_one_line_are_expanded():
    text = "[00:10.00][00:40.00]chorus\n"
    lyrics = parse_lrc(text)
    assert len(lyrics.lines) == 2
    assert [ln.start for ln in lyrics.lines] == [10.0, 40.0]


def test_offset_is_applied():
    text = "[offset:+500]\n[00:10.00]shifted\n"
    lyrics = parse_lrc(text)
    assert lyrics.lines[0].start == 9.5


def test_untimed_text_is_not_marked_synced():
    lyrics = parse_plain("line one\n\nline two\n")
    assert not lyrics.synced
    assert len(lyrics.lines) == 2
    assert lyrics.lines[0].synthetic


def test_spread_plain_lyrics_is_monotonic_and_bounded():
    lyrics = parse_plain("a\nb\nc\nd\n")
    spread = spread_plain_lyrics(lyrics, duration=20.0, lead_in=2.0, tail=3.0)
    starts = [ln.start for ln in spread.lines]
    assert starts == sorted(starts)
    assert starts[0] >= 2.0
    assert spread.lines[-1].end <= 20.0
    assert all(ln.words for ln in spread.lines)
    assert all(w.synthetic for ln in spread.lines for w in ln.words)


def test_to_lrc_roundtrip_preserves_words():
    text = "[00:10.00]<00:10.00>Aadiyile <00:10.50>sedhi\n[00:12.00]next\n"
    lyrics = parse_lrc(text)
    rendered = to_lrc(lyrics)
    assert "<00:10.00>Aadiyile" in rendered
    reparsed = parse_lrc(rendered)
    assert reparsed.lines[0].text == "Aadiyile sedhi"
    assert len(reparsed.lines) == 2


def test_to_plain_text():
    lyrics = parse_lrc("[00:01.00]one\n[00:02.00]two\n")
    assert to_plain_text(lyrics) == "one\ntwo"
