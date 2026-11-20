"""LRCLIB client tests using a fake transport (no network needed)."""

from __future__ import annotations

import pytest

from abikaraoke import lyrics as lyrics_module
from abikaraoke.lyrics import LyricsError, LyricsNotFound, fetch_lyrics

SYNCED = "[00:01.00]line one\n[00:05.00]line two\n"


def _fake(payloads):
    """Return a _request_json replacement that serves canned payloads."""

    calls = []

    def _request(url, timeout, retries):
        calls.append(url)
        if "/get?" in url:
            value = payloads["get"]
        else:
            value = payloads["search"]
        if isinstance(value, Exception):
            raise value
        return value

    _request.calls = calls
    return _request


def test_fetch_prefers_synced_result(monkeypatch, tmp_path):
    monkeypatch.setattr(
        lyrics_module,
        "_request_json",
        _fake(
            {
                "get": {
                    "trackName": "Song",
                    "artistName": "Singer",
                    "duration": 200,
                    "syncedLyrics": SYNCED,
                    "plainLyrics": "line one\nline two",
                },
                "search": [],
            }
        ),
    )
    result = fetch_lyrics("Singer", "Song", duration=200, cache_dir=tmp_path)
    assert result.synced
    assert len(result.lines) == 2
    assert result.lines[0].start == 1.0
    assert result.title == "Song"
    assert result.artist == "Singer"


def test_fetch_falls_back_to_search_when_exact_missing(monkeypatch, tmp_path):
    monkeypatch.setattr(
        lyrics_module,
        "_request_json",
        _fake(
            {
                "get": LyricsNotFound("nope"),
                "search": [
                    {
                        "trackName": "Song",
                        "artistName": "Singer",
                        "duration": 201,
                        "syncedLyrics": SYNCED,
                        "plainLyrics": None,
                    }
                ],
            }
        ),
    )
    result = fetch_lyrics("Singer", "Song", duration=200, cache_dir=tmp_path)
    assert result.synced
    assert len(result.lines) == 2


def test_fetch_raises_not_found_with_actionable_message(monkeypatch, tmp_path):
    monkeypatch.setattr(
        lyrics_module,
        "_request_json",
        _fake({"get": LyricsNotFound("nope"), "search": []}),
    )
    with pytest.raises(LyricsNotFound) as excinfo:
        fetch_lyrics("Singer", "Song", cache_dir=tmp_path)
    assert "Song" in str(excinfo.value)


def test_fetch_raises_on_network_failure(monkeypatch, tmp_path):
    monkeypatch.setattr(
        lyrics_module,
        "_request_json",
        _fake(
            {
                "get": LyricsError("network down"),
                "search": LyricsError("network down"),
            }
        ),
    )
    with pytest.raises(LyricsError):
        fetch_lyrics("Singer", "Song", cache_dir=tmp_path)


def test_fetch_requires_title(tmp_path):
    with pytest.raises(LyricsError):
        fetch_lyrics("", "", cache_dir=tmp_path)


def test_fetch_writes_and_reads_cache(monkeypatch, tmp_path):
    transport = _fake(
        {
            "get": {
                "trackName": "Song",
                "artistName": "Singer",
                "duration": 200,
                "syncedLyrics": SYNCED,
                "plainLyrics": None,
            },
            "search": [],
        }
    )
    monkeypatch.setattr(lyrics_module, "_request_json", transport)
    fetch_lyrics("Singer", "Song", duration=200, cache_dir=tmp_path)
    first_calls = len(transport.calls)
    assert first_calls > 0

    # Second call must be served from disk without touching the network.
    cached = fetch_lyrics("Singer", "Song", duration=200, cache_dir=tmp_path)
    assert len(transport.calls) == first_calls
    assert cached.source == "lrclib-cache"
    assert len(cached.lines) == 2


def test_offline_mode_without_cache_errors(tmp_path):
    with pytest.raises(LyricsError):
        fetch_lyrics("Singer", "Song", cache_dir=tmp_path, offline=True)
