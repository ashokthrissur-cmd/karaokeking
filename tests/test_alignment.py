"""AI-sync alignment tests: monotonic DP, token→word mapping, honesty flags."""

from __future__ import annotations

from abikaraoke.alignment import align_lyrics, fuzzy_align, normalize_token, tokenize
from abikaraoke.lrc import parse_plain
from abikaraoke.models import Transcript, TranscriptWord


def _transcript(words):
    return Transcript(
        words=[TranscriptWord(text=t, start=s, end=e, confidence=c) for t, s, e, c in words],
        text=" ".join(w[0] for w in words),
        backend="test",
    )


def test_normalize_token_strips_case_and_punctuation():
    assert normalize_token("Kaadhal,") == "kaadhal"
    assert normalize_token("  ENNUM! ") == "ennum"


def test_tokenize_splits_on_whitespace():
    assert tokenize("Aadiyile sedhi kettadha") == ["Aadiyile", "sedhi", "kettadha"]


def test_fuzzy_align_is_monotonic():
    lyrics = ["aadiyile", "sedhi", "kettadha", "en", "aasai"]
    heard = ["aadiyile", "sedhi", "kettadha", "en", "aasai"]
    matches = fuzzy_align(lyrics, heard)
    assert [m[0] for m in matches] == sorted(m[0] for m in matches)
    assert [m[1] for m in matches] == sorted(m[1] for m in matches)
    assert len(matches) == 5


def test_fuzzy_align_skips_noise_and_tolerates_mishearing():
    lyrics = ["kadhal", "ennum", "kadhal", "dhaan"]
    heard = ["um", "kathal", "ennum", "kathal", "than"]
    matches = fuzzy_align(lyrics, heard)
    assert len(matches) >= 3
    # every match must point at a plausible token
    for lyric_index, word_index, score in matches:
        assert score >= 0.55
        assert lyrics[lyric_index] and heard[word_index]


def test_fuzzy_align_empty_inputs():
    assert fuzzy_align([], ["a"]) == []
    assert fuzzy_align(["a"], []) == []


def test_align_lyrics_maps_words_to_measured_times():
    lyrics = parse_plain("Aadiyile sedhi kettadha\nKadhal ennum dhaan\n")
    transcript = _transcript(
        [
            ("aadiyile", 1.0, 1.4, 0.95),
            ("sedhi", 1.4, 1.8, 0.9),
            ("kettadha", 1.8, 2.4, 0.9),
            ("kadhal", 6.0, 6.4, 0.9),
            ("ennum", 6.4, 6.8, 0.9),
            ("dhaan", 6.8, 7.2, 0.9),
        ]
    )
    report = align_lyrics(lyrics, transcript, duration=10.0)
    assert report.method in ("ai", "whisper-words")
    assert report.matched_ratio == 1.0
    first = report.lines[0]
    assert first.start == 1.0
    assert [w.text for w in first.words] == ["Aadiyile", "sedhi", "kettadha"]
    assert all(not w.synthetic for w in first.words)
    assert all(w.confidence > 0 for w in first.words)


def test_align_lyrics_flags_interpolated_words_as_synthetic():
    lyrics = parse_plain("one two three four five\n")
    transcript = _transcript(
        [("one", 1.0, 1.3, 1.0), ("five", 4.0, 4.3, 1.0)]
    )
    report = align_lyrics(lyrics, transcript, duration=6.0)
    words = report.lines[0].words
    assert words[0].text == "one" and not words[0].synthetic
    assert words[-1].text == "five" and not words[-1].synthetic
    middle = [w for w in words[1:-1]]
    assert middle and all(w.synthetic for w in middle)
    assert all(w.confidence <= 0.3 for w in middle)


def test_align_lyrics_without_transcript_spreads_evenly_and_warns():
    lyrics = parse_plain("one\ntwo\nthree\n")
    report = align_lyrics(lyrics, Transcript(words=[]), duration=12.0)
    assert report.method == "even"
    assert report.matched_ratio == 0.0
    assert report.warnings
    assert len(report.lines) == 3


def test_low_confidence_lines_are_reported():
    lyrics = parse_plain("alpha beta gamma\ncompletely unrelated words here\n")
    transcript = _transcript(
        [("alpha", 1.0, 1.3, 1.0), ("beta", 1.3, 1.6, 1.0), ("gamma", 1.6, 1.9, 1.0)]
    )
    report = align_lyrics(lyrics, transcript, duration=8.0)
    assert 1 in report.low_confidence_lines
