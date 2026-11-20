"""Turn messy media file names into usable artist/title metadata.

The original app split the file name on the first ``" - "`` and trusted both
halves.  Real downloads look like::

    Aaja Re Pardesi - HD video song - en atte - fecio Sar aaa aren - 12.mp4

which yields ``artist="Aaja Re Pardesi"`` and a track name made of noise, so
every lyric lookup misses.  This module strips the noise first, then decides
which fragment is the title and which is the artist, and reports how confident
it is so the UI can ask the user instead of guessing silently.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional, Tuple

# Words that carry no identifying information in a file name.  Matched
# case-insensitively as whole tokens, never as substrings, so a song genuinely
# called "Live and Let Die" keeps its "Live".
_NOISE_TOKENS = {
    "hd", "hq", "uhd", "4k", "8k", "1080p", "720p", "480p", "360p",
    "video", "videos", "song", "songs", "full", "fullsong", "audio",
    "lyrical", "lyrics", "lyric", "with", "w", "official", "officially",
    "music", "album", "movie", "film", "soundtrack", "ost", "bgm",
    "remastered", "remaster", "remasterd", "version", "original",
    "new", "latest", "best", "hit", "hits", "superhit", "evergreen",
    "whatsapp", "status", "edit", "edits", "remix", "dj", "mashup",
    "cover", "karaoke", "instrumental", "acoustic", "unplugged",
    "live", "concert", "performance", "stage", "show",
    "feat", "ft", "featuring", "prod", "prodby",
    "mp3", "mp4", "m4a", "wav", "flac", "aac", "webm", "mkv",
    "download", "downloaded", "yt", "youtube", "vevo", "topic",
    "1080", "720", "480", "320kbps", "128kbps", "320", "128",
}

# Language/genre words are only removed when they stand alone in a fragment,
# because they are frequently part of a real title.
_LANGUAGE_TOKENS = {
    "hindi", "malayalam", "tamil", "telugu", "kannada", "punjabi", "marathi",
    "bengali", "urdu", "gujarati", "sinhala", "english", "bollywood",
    "kollywood", "tollywood", "mollywood", "sandalwood",
}

_BRACKETED = re.compile(r"[\(\[\{]([^\)\]\}]*)[\)\]\}]")
_TRACK_NUMBER = re.compile(r"^\s*(?:track\s*)?\d{1,3}\s*[-–—._)]\s*", re.IGNORECASE)
_YEAR_PREFIX = re.compile(r"^\s*(?:19|20)\d{2}\s*[-–—._)]?\s*")
_DECADE_PREFIX = re.compile(r"^\s*(?:19|20)\d0s?\s*[-–—._)]?\s*", re.IGNORECASE)
_SEPARATORS = re.compile(r"\s+[-–—|]\s+|\s*[|/]\s*")
_MULTISPACE = re.compile(r"\s{2,}")
_EDGE_PUNCT = re.compile(r"^[\s\-–—_.,;:!?\"'`~*#]+|[\s\-–—_.,;:!?\"'`~*#]+$")
_TOKEN_SPLIT = re.compile(r"[\s._\-–—]+")


@dataclass
class SongGuess:
    """What we think the file is, plus how sure we are."""

    artist: str = ""
    title: str = ""
    confidence: float = 0.0
    notes: List[str] = field(default_factory=list)
    cleaned: str = ""

    @property
    def is_usable(self) -> bool:
        return bool(self.title)

    def search_queries(self) -> List[str]:
        """Queries to try, most specific first."""
        queries: List[str] = []
        if self.artist and self.title:
            queries.append(f"{self.artist} {self.title}")
        if self.title:
            queries.append(self.title)
        if self.artist:
            queries.append(self.artist)
        seen = set()
        unique = []
        for q in queries:
            key = q.casefold()
            if key not in seen:
                seen.add(key)
                unique.append(q)
        return unique


def _strip_brackets(text: str) -> Tuple[str, List[str]]:
    """Remove bracketed groups that are pure noise; keep meaningful ones."""

    removed: List[str] = []

    def replace(match: "re.Match[str]") -> str:
        inner = match.group(1).strip()
        if not inner:
            return " "
        tokens = [t for t in _TOKEN_SPLIT.split(inner.casefold()) if t]
        if tokens and all(t in _NOISE_TOKENS or t in _LANGUAGE_TOKENS for t in tokens):
            removed.append(inner)
            return " "
        if re.fullmatch(r"[\d\s.,x×:]+", inner):
            removed.append(inner)
            return " "
        return f" {inner} "

    return _BRACKETED.sub(replace, text), removed


def _drop_noise_tokens(text: str) -> Tuple[str, int]:
    """Remove noise words from a fragment, returning (text, removed_count).

    Only fragments that are *mostly* noise are rewritten.  A title such as
    "Live and Let Die" contains the noise word "live" but is 25% noise, so it
    is kept intact; "HD video song" is 100% noise and disappears.
    """

    tokens = [t for t in _TOKEN_SPLIT.split(text) if t]
    if not tokens:
        return "", 0

    kept: List[str] = []
    removed = 0
    for index, token in enumerate(tokens):
        folded = token.casefold().strip(".,;:!?\"'")
        if folded in _NOISE_TOKENS:
            removed += 1
            continue
        if index == len(tokens) - 1 and re.fullmatch(r"\d{1,4}", folded):
            removed += 1
            continue
        kept.append(token)

    if removed == 0:
        return text, 0
    if removed == len(tokens):
        # Every token was noise ("HD video song", "320kbps", "12").
        return "", removed
    # Partly meaningful: keep the fragment as written.  Dropping "Song" from
    # "Song feat. Other" would destroy a real title.
    return text, 0


_VOWELS = set("aeiouyAEIOUY")


def _token_has_vowel(token: str) -> bool:
    """True for Latin tokens with a vowel, and for non-Latin scripts."""

    letters = [c for c in token if c.isalpha()]
    if not letters:
        return False
    if not any(c.isascii() for c in letters):
        # Malayalam, Tamil, Devanagari...: vowel detection is meaningless.
        return True
    return any(c in _VOWELS for c in letters)


def _quality(fragment: str) -> float:
    """How much a fragment looks like a real song/artist name (0..1)."""

    words = [w for w in fragment.split() if w]
    if not words:
        return 0.0
    latin = any(c.isascii() and c.isalpha() for c in fragment)
    if latin:
        capitalised = sum(1 for w in words if w[:1].isupper())
        cap_ratio = capitalised / len(words)
    else:
        # Malayalam/Tamil/Devanagari have no case; assume well-formed.
        cap_ratio = 1.0
    vowel_ratio = sum(1 for w in words if _token_has_vowel(w)) / len(words)
    length_bonus = min(len(words), 5) / 5.0
    score = 0.5 * cap_ratio + 0.3 * vowel_ratio + 0.2 * length_bonus

    # Transliteration garbage: short lowercase tokens, or vowel-less ASCII
    # runs such as "aaa".  Single-letter initials ("A R Rahman") are fine.
    junk = 0.0
    for word in words:
        folded = word.casefold().strip(".,;:!?'\"")
        if not folded.isascii() or not folded.isalpha():
            continue
        if len(folded) <= 2 and folded.islower():
            junk += 0.1
        elif len(folded) >= 3 and folded.islower() and not _token_has_vowel(folded):
            junk += 0.3
    return max(0.0, min(1.0, score - junk))


def _tidy(text: str) -> str:
    text = _MULTISPACE.sub(" ", text.replace("_", " "))
    text = _EDGE_PUNCT.sub("", text.strip())
    return _MULTISPACE.sub(" ", text).strip()


def _looks_like_title(text: str) -> float:
    """Heuristic 0..1 score for 'this fragment is the song title'."""

    if not text:
        return 0.0
    words = [w for w in text.split() if w]
    if not words:
        return 0.0
    score = min(len(words), 6) / 6.0
    if re.search(r"\b(feat|ft|prod)\b", text, re.IGNORECASE):
        score -= 0.15
    return max(0.0, min(1.0, score))


def parse_song_name(
    filename: str | Path,
    *,
    folder: Optional[str | Path] = None,
) -> SongGuess:
    """Best-effort artist/title extraction from a file name.

    ``folder`` is used only as a weak hint (e.g. ``"1990 hindi"``) and never
    becomes the title.
    """

    raw = Path(str(filename)).name
    stem = Path(raw).stem if "." in raw else raw
    notes: List[str] = []

    text = unicodedata.normalize("NFC", stem)
    text, bracket_noise = _strip_brackets(text)
    if bracket_noise:
        notes.append("removed bracketed noise: " + ", ".join(bracket_noise[:3]))

    text = _tidy(text)
    text = _TRACK_NUMBER.sub("", text)
    text = _DECADE_PREFIX.sub("", text)
    text = _YEAR_PREFIX.sub("", text)
    text = _tidy(text)

    fragments = [f for f in (_tidy(p) for p in _SEPARATORS.split(text)) if f]

    meaningful: List[str] = []
    for fragment in fragments:
        cleaned, removed = _drop_noise_tokens(fragment)
        cleaned = _tidy(cleaned)
        if cleaned:
            meaningful.append(cleaned)
        elif removed:
            notes.append(f"dropped noise fragment: {fragment!r}")

    if not meaningful:
        fallback = _tidy(stem)
        return SongGuess(
            artist="",
            title=fallback,
            confidence=0.2 if fallback else 0.0,
            notes=notes + ["file name was mostly noise; using it verbatim"],
            cleaned=fallback,
        )

    if len(meaningful) == 1:
        artist, title = "", meaningful[0]
        confidence = 0.45
        notes.append("single fragment; artist unknown")
    else:
        scored = sorted(
            ((_quality(f), index, f) for index, f in enumerate(meaningful)),
            key=lambda item: (-item[0], item[1]),
        )
        best_quality, best_index, best = scored[0]
        others = [item for item in scored[1:]]

        if best_quality < 0.35:
            # Nothing looks like a real name; keep positional convention.
            artist, title = meaningful[0], meaningful[1]
            confidence = 0.35
            notes.append("low-quality fragments; using positional split")
        else:
            title = best
            artist = ""
            if others:
                second_quality, second_index, second = others[0]
                # Only promote a second fragment to "artist" when it is
                # credible and roughly as strong as the title.
                if second_quality >= 0.6 and best_quality - second_quality < 0.15:
                    if second_index < best_index:
                        artist, title = second, best
                    else:
                        artist, title = best, second
                        title = second
                    confidence = 0.8
                elif second_quality >= 0.6 and second_index < best_index:
                    artist = second
                    confidence = 0.7
                else:
                    confidence = 0.6
                    notes.append("only one credible fragment; artist unknown")
            else:
                confidence = 0.5
        if len(meaningful) > 2:
            notes.append(f"ignored {len(meaningful) - 2} extra fragment(s)")

    if artist.casefold() in _LANGUAGE_TOKENS:
        notes.append(f"ignored language word as artist: {artist!r}")
        artist = ""

    artist, title = _tidy(artist), _tidy(title)

    if re.search(r"\b(feat|ft)\b", title, re.IGNORECASE):
        confidence = min(confidence, 0.5)

    if folder:
        folder_name = _tidy(Path(str(folder)).name)
        if folder_name and folder_name.casefold() not in {artist.casefold(), title.casefold()}:
            notes.append(f"folder hint: {folder_name!r}")

    return SongGuess(
        artist=artist,
        title=title,
        confidence=round(confidence, 2),
        notes=notes,
        cleaned=_tidy(f"{artist} - {title}" if artist else title),
    )


def guess_from_path(path: str | Path) -> SongGuess:
    """Parse a path that may use either Windows or POSIX separators."""

    text = str(path).replace("\\", "/").rstrip("/")
    name = text.rsplit("/", 1)[-1] if "/" in text else text
    parent = text.rsplit("/", 2)[-2] if text.count("/") >= 1 else ""
    return parse_song_name(name, folder=parent or None)
