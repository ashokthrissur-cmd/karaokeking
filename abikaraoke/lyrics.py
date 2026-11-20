"""LRCLIB lyric lookup with retries, caching, and honest error reporting.

The original app treated any failed lookup as a silent no-op, so the button
appeared to "do nothing".  This client distinguishes not-found, network
failure, and malformed responses, and returns actionable messages.
"""

from __future__ import annotations

import difflib
import hashlib
import json
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional

from . import __version__
from .lrc import parse_lrc, parse_plain
from .models import Lyrics

BASE_URL = "https://lrclib.net/api"
USER_AGENT = f"ABIKaraoke/{__version__} (https://github.com/ashokthrissur-cmd/karaokeking)"


class LyricsError(RuntimeError):
    """Lyric lookup failed for a reportable reason."""


class LyricsNotFound(LyricsError):
    """LRCLIB has no matching record."""


@dataclass
class LyricCandidate:
    title: str
    artist: str
    duration: float
    synced: Optional[str]
    plain: Optional[str]
    instrumental: bool = False

    @property
    def has_synced(self) -> bool:
        return bool(self.synced and self.synced.strip())


def _similarity(a: str, b: str) -> float:
    return difflib.SequenceMatcher(None, a.casefold().strip(), b.casefold().strip()).ratio()


def _request_json(url: str, timeout: float, retries: int) -> Any:
    last_error: Optional[Exception] = None
    for attempt in range(retries + 1):
        request = urllib.request.Request(
            url,
            headers={
                "User-Agent": USER_AGENT,
                "Accept": "application/json",
                "Lrclib-Client": USER_AGENT,
            },
        )
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                body = response.read().decode("utf-8", "replace")
                return json.loads(body)
        except urllib.error.HTTPError as exc:
            if exc.code == 404:
                raise LyricsNotFound("LRCLIB has no record for this song.") from exc
            last_error = exc
            if exc.code in (429, 500, 502, 503, 504) and attempt < retries:
                time.sleep(1.5 * (attempt + 1))
                continue
            raise LyricsError(f"LRCLIB returned HTTP {exc.code}.") from exc
        except urllib.error.URLError as exc:
            last_error = exc
            if attempt < retries:
                time.sleep(1.5 * (attempt + 1))
                continue
            raise LyricsError(
                f"Cannot reach LRCLIB ({exc.reason}). Check your internet connection."
            ) from exc
        except (TimeoutError, json.JSONDecodeError) as exc:
            last_error = exc
            if attempt < retries:
                time.sleep(1.5 * (attempt + 1))
                continue
            raise LyricsError("LRCLIB returned an unreadable response.") from exc
    raise LyricsError(f"LRCLIB lookup failed: {last_error}")


def _candidate_from(data: Dict[str, Any]) -> LyricCandidate:
    return LyricCandidate(
        title=str(data.get("trackName") or data.get("name") or ""),
        artist=str(data.get("artistName") or ""),
        duration=float(data.get("duration") or 0.0),
        synced=data.get("syncedLyrics"),
        plain=data.get("plainLyrics"),
        instrumental=bool(data.get("instrumental")),
    )


def _score(candidate: LyricCandidate, artist: str, title: str, duration: Optional[float]) -> float:
    score = 0.0
    score += 3.0 * _similarity(candidate.title, title)
    score += 2.0 * _similarity(candidate.artist, artist)
    if candidate.has_synced:
        score += 2.0
    if duration and candidate.duration:
        delta = abs(candidate.duration - duration)
        score += 2.0 if delta <= 2 else 1.0 if delta <= 6 else -1.0
    return score


def _cache_path(cache_dir: Optional[Path], artist: str, title: str, duration: Optional[float]) -> Optional[Path]:
    if cache_dir is None:
        return None
    key = hashlib.sha256(f"{artist}|{title}|{duration}".casefold().encode("utf-8")).hexdigest()[:24]
    return Path(cache_dir) / f"lrclib-{key}.json"


def _read_cache(path: Optional[Path]) -> Optional[Dict[str, Any]]:
    if path and path.is_file():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return None
    return None


def _write_cache(path: Optional[Path], payload: Dict[str, Any]) -> None:
    if not path:
        return
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    except OSError:
        pass


def fetch_lyrics(
    artist: str,
    title: str,
    *,
    duration: Optional[float] = None,
    timeout: float = 12.0,
    retries: int = 2,
    cache_dir: Optional[Path] = None,
    allow_plain: bool = True,
    offline: bool = False,
) -> Lyrics:
    """Look up lyrics on LRCLIB, preferring word/line-synced results.

    Raises :class:`LyricsNotFound` when nothing matches and
    :class:`LyricsError` for network/server problems.
    """

    artist = (artist or "").strip()
    title = (title or "").strip()
    if not title:
        raise LyricsError("Enter a track title before fetching lyrics.")

    cache = _cache_path(cache_dir, artist, title, duration)
    cached = _read_cache(cache)
    if cached:
        return _lyrics_from_payload(cached, artist, title, source="lrclib-cache")

    if offline:
        raise LyricsError("Offline mode is enabled; enter lyrics manually.")

    query = {"track_name": title}
    if artist:
        query["artist_name"] = artist
    if duration and duration > 0:
        query["duration"] = str(int(round(duration)))

    candidates: List[LyricCandidate] = []
    exact: Optional[Dict[str, Any]] = None
    try:
        exact = _request_json(f"{BASE_URL}/get?{urllib.parse.urlencode(query)}", timeout, retries)
    except LyricsNotFound:
        exact = None
    except LyricsError:
        # A failed exact lookup should not prevent trying search, but keep the
        # error if search also fails.
        exact = None

    if isinstance(exact, dict) and (exact.get("syncedLyrics") or exact.get("plainLyrics")):
        candidates.append(_candidate_from(exact))

    if not candidates or not any(c.has_synced for c in candidates):
        search_query = {"track_name": title}
        if artist:
            search_query["artist_name"] = artist
        try:
            results = _request_json(
                f"{BASE_URL}/search?{urllib.parse.urlencode(search_query)}", timeout, retries
            )
            if isinstance(results, list):
                candidates.extend(_candidate_from(item) for item in results if isinstance(item, dict))
        except LyricsNotFound:
            pass
        except LyricsError:
            if not candidates:
                raise

    usable = [c for c in candidates if (c.has_synced or (allow_plain and c.plain)) and not c.instrumental]
    if not usable:
        raise LyricsNotFound(
            f"No lyrics found for '{title}'" + (f" by {artist}" if artist else "") + " on LRCLIB."
        )

    best = max(usable, key=lambda c: _score(c, artist, title, duration))
    payload = {
        "trackName": best.title,
        "artistName": best.artist,
        "duration": best.duration,
        "syncedLyrics": best.synced,
        "plainLyrics": best.plain,
        "instrumental": best.instrumental,
    }
    _write_cache(cache, payload)
    return _lyrics_from_payload(payload, artist, title, source="lrclib")


def _lyrics_from_payload(payload: Dict[str, Any], artist: str, title: str, source: str) -> Lyrics:
    synced = payload.get("syncedLyrics")
    plain = payload.get("plainLyrics")
    if synced and synced.strip():
        lyrics = parse_lrc(synced, source=source)
        lyrics.title = payload.get("trackName") or title
        lyrics.artist = payload.get("artistName") or artist
        if lyrics.lines:
            return lyrics
    if plain and plain.strip():
        lyrics = parse_plain(plain, source=source)
        lyrics.title = payload.get("trackName") or title
        lyrics.artist = payload.get("artistName") or artist
        lyrics.warnings.append("LRCLIB returned plain lyrics without timestamps.")
        return lyrics
    raise LyricsNotFound("LRCLIB record contains no usable lyric text.")


def search_lyrics(
    query: str,
    *,
    timeout: float = 12.0,
    retries: int = 2,
    limit: int = 25,
) -> List[LyricCandidate]:
    """Free-text LRCLIB search, newest-relevance first.

    Used by the UI when automatic matching fails, so the user can pick the
    right record instead of being told "no lyrics found".
    """

    query = (query or "").strip()
    if not query:
        raise LyricsError("Type something to search for.")

    url = f"{BASE_URL}/search?{urllib.parse.urlencode({'q': query})}"
    results = _request_json(url, timeout, retries)
    if not isinstance(results, list):
        raise LyricsError("LRCLIB returned an unexpected search response.")

    candidates = [_candidate_from(item) for item in results if isinstance(item, dict)]
    candidates = [c for c in candidates if (c.has_synced or c.plain) and not c.instrumental]
    # Synced records first, then by how well the text matches the query.
    candidates.sort(key=lambda c: (not c.has_synced, -_similarity(f"{c.artist} {c.title}", query)))
    return candidates[:limit]


def lyrics_from_candidate(candidate: LyricCandidate) -> Lyrics:
    """Convert a user-picked search result into a :class:`Lyrics` object."""

    payload = {
        "trackName": candidate.title,
        "artistName": candidate.artist,
        "duration": candidate.duration,
        "syncedLyrics": candidate.synced,
        "plainLyrics": candidate.plain,
        "instrumental": candidate.instrumental,
    }
    return _lyrics_from_payload(payload, candidate.artist, candidate.title, source="lrclib")


def fetch_lyrics_multi(
    queries: List[str],
    *,
    duration: Optional[float] = None,
    timeout: float = 12.0,
    retries: int = 2,
    cache_dir: Optional[Path] = None,
    allow_plain: bool = True,
) -> Lyrics:
    """Try several query spellings before giving up.

    A file name like "Aaja Re Pardesi - HD video song" yields several plausible
    queries; LRCLIB often matches one of them even when the first misses.
    """

    cleaned = [q.strip() for q in queries if q and q.strip()]
    if not cleaned:
        raise LyricsError("Enter a track title before fetching lyrics.")

    errors: List[str] = []
    for query in cleaned:
        # Split "Artist Title" back into the two fields LRCLIB prefers.
        artist, title = "", query
        if " - " in query:
            artist, title = (part.strip() for part in query.split(" - ", 1))
        try:
            return fetch_lyrics(
                artist,
                title,
                duration=duration,
                timeout=timeout,
                retries=retries,
                cache_dir=cache_dir,
                allow_plain=allow_plain,
            )
        except LyricsNotFound as exc:
            errors.append(str(exc))
        except LyricsError as exc:
            # Network trouble will not be fixed by another spelling.
            raise

    raise LyricsNotFound(
        "No LRCLIB match for: " + ", ".join(repr(q) for q in cleaned)
        + ". Use 'Search lyrics' to pick a record manually."
    )
