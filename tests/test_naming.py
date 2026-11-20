"""File-name parsing must survive real-world download junk."""

from __future__ import annotations

import pytest

from abikaraoke.naming import SongGuess, guess_from_path, parse_song_name


def test_screenshot_case_extracts_clean_title():
    """The exact file name from the user's screenshot."""
    name = (
        "Aaja Re Pardesi - HD video song - en atte - fecio Sar aaa aren - 12.mp4"
    )
    guess = parse_song_name(name)
    assert guess.title == "Aaja Re Pardesi"
    assert guess.artist == ""
    assert guess.confidence >= 0.4


def test_artist_dash_title():
    guess = parse_song_name("Ed Sheeran - Perfect.mp3")
    assert guess.artist == "Ed Sheeran"
    assert guess.title == "Perfect"
    assert guess.confidence >= 0.8


def test_bracketed_noise_is_removed():
    guess = parse_song_name("Adele - Hello (Official Music Video) [HD].mp4")
    assert guess.artist == "Adele"
    assert guess.title == "Hello"


def test_track_number_and_year_prefix():
    guess = parse_song_name("01 - A R Rahman - Kun Faya Kun.mp3")
    assert guess.artist == "A R Rahman"
    assert guess.title == "Kun Faya Kun"


def test_underscores_become_spaces():
    guess = parse_song_name("KJ_Yesudas_-_Harivarasanam.mp3")
    assert "Harivarasanam" in guess.title


def test_language_word_is_not_an_artist():
    guess = parse_song_name("Hindi - Tum Hi Ho.mp3")
    assert guess.artist == ""
    assert guess.title == "Tum Hi Ho"


def test_language_word_kept_inside_title():
    guess = parse_song_name("Malayalam - Kerala Song.mp3")
    assert "Kerala" in guess.title


def test_live_kept_when_part_of_title():
    guess = parse_song_name("Wings - Live and Let Die.mp3")
    assert guess.artist == "Wings"
    assert "Live and Let Die" in guess.title


def test_pure_noise_falls_back_to_stem():
    guess = parse_song_name("HD 1080p official video.mp4")
    assert guess.title  # never empty
    assert guess.confidence <= 0.3


def test_search_queries_order_and_dedup():
    guess = SongGuess(artist="Adele", title="Hello")
    assert guess.search_queries() == ["Adele Hello", "Hello", "Adele"]


def test_search_queries_without_artist():
    guess = SongGuess(artist="", title="Hello")
    assert guess.search_queries() == ["Hello"]


def test_guess_from_path_uses_parent_folder():
    guess = guess_from_path("/music/1990 hindi/Aaja Re Pardesi - HD song.mp4")
    assert guess.title == "Aaja Re Pardesi"
    assert any("folder hint" in note for note in guess.notes)


def test_unicode_name_survives():
    guess = parse_song_name("കെ ജെ യേശുദാസ് - ഹരിവരാസനം.mp3")
    assert guess.title
    assert "ഹരിവരാസനം" in guess.title or "യേശുദാസ്" in guess.artist


def test_featuring_credit_lowers_confidence():
    guess = parse_song_name("Artist - Song feat. Other.mp3")
    assert guess.confidence <= 0.5


@pytest.mark.parametrize(
    "name,title_word",
    [
        ("Song (Lyrical Video).mp3", "Song"),
        ("Song [4K].mp3", "Song"),
        ("Song - 320kbps.mp3", "Song"),
    ],
)
def test_noise_variants(name, title_word):
    assert title_word in parse_song_name(name).title
