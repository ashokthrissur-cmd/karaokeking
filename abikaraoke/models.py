"""Shared data models.

Every timestamp is in seconds (float) unless a field name says otherwise.
"""

from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Any, Dict, List, Optional


@dataclass
class Word:
    text: str
    start: float
    end: float
    confidence: float = 1.0
    synthetic: bool = False  # True when timing was interpolated, not measured

    @property
    def duration(self) -> float:
        return max(0.0, self.end - self.start)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Word":
        return cls(
            text=data["text"],
            start=float(data["start"]),
            end=float(data["end"]),
            confidence=float(data.get("confidence", 1.0)),
            synthetic=bool(data.get("synthetic", False)),
        )


@dataclass
class LyricLine:
    start: float
    end: float
    text: str
    words: List[Word] = field(default_factory=list)
    confidence: float = 1.0
    synthetic: bool = False
    source: str = "manual"

    @property
    def duration(self) -> float:
        return max(0.0, self.end - self.start)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "start": self.start,
            "end": self.end,
            "text": self.text,
            "words": [w.to_dict() for w in self.words],
            "confidence": self.confidence,
            "synthetic": self.synthetic,
            "source": self.source,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "LyricLine":
        return cls(
            start=float(data["start"]),
            end=float(data["end"]),
            text=data["text"],
            words=[Word.from_dict(w) for w in data.get("words", [])],
            confidence=float(data.get("confidence", 1.0)),
            synthetic=bool(data.get("synthetic", False)),
            source=data.get("source", "manual"),
        )


@dataclass
class Lyrics:
    lines: List[LyricLine] = field(default_factory=list)
    source: str = "manual"
    synced: bool = False
    language: Optional[str] = None
    title: Optional[str] = None
    artist: Optional[str] = None
    raw_lrc: Optional[str] = None
    warnings: List[str] = field(default_factory=list)

    def sorted_lines(self) -> List[LyricLine]:
        return sorted(self.lines, key=lambda ln: (ln.start, ln.end))

    def to_dict(self) -> Dict[str, Any]:
        return {
            "lines": [ln.to_dict() for ln in self.lines],
            "source": self.source,
            "synced": self.synced,
            "language": self.language,
            "title": self.title,
            "artist": self.artist,
            "raw_lrc": self.raw_lrc,
            "warnings": self.warnings,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Lyrics":
        return cls(
            lines=[LyricLine.from_dict(ln) for ln in data.get("lines", [])],
            source=data.get("source", "manual"),
            synced=bool(data.get("synced", False)),
            language=data.get("language"),
            title=data.get("title"),
            artist=data.get("artist"),
            raw_lrc=data.get("raw_lrc"),
            warnings=list(data.get("warnings", [])),
        )


@dataclass
class TranscriptWord:
    text: str
    start: float
    end: float
    confidence: float = 1.0


@dataclass
class Transcript:
    words: List[TranscriptWord] = field(default_factory=list)
    text: str = ""
    language: Optional[str] = None
    backend: str = "none"
    warnings: List[str] = field(default_factory=list)


@dataclass
class SeparationResult:
    instrumental_path: str
    method: str  # "demucs" | "center-cancel" | "none"
    vocals_path: Optional[str] = None
    duration: float = 0.0
    warnings: List[str] = field(default_factory=list)
    elapsed: float = 0.0


@dataclass
class AlignmentReport:
    lines: List[LyricLine] = field(default_factory=list)
    method: str = "none"  # "whisper-words" | "whisper-segments" | "energy" | "even"
    matched_ratio: float = 0.0
    low_confidence_lines: List[int] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)


@dataclass
class RenderResult:
    output_path: str
    duration: float
    width: int
    height: int
    video_codec: str
    audio_codec: str
    warnings: List[str] = field(default_factory=list)
