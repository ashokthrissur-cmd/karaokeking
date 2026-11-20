"""FFmpeg/ffprobe media helpers: probe, audio extraction, and validation."""

from __future__ import annotations

import json
import os
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional

from .process import ProcessError, run

AUDIO_EXTENSIONS = {
    ".mp3", ".wav", ".flac", ".m4a", ".aac", ".ogg", ".opus", ".wma", ".aiff", ".aif",
}
VIDEO_EXTENSIONS = {
    ".mp4", ".mkv", ".mov", ".avi", ".webm", ".wmv", ".flv", ".m4v", ".mpg", ".mpeg", ".ts",
}
MEDIA_EXTENSIONS = AUDIO_EXTENSIONS | VIDEO_EXTENSIONS


@dataclass
class MediaInfo:
    path: str
    duration: float
    format_name: str
    has_audio: bool
    has_video: bool
    width: int = 0
    height: int = 0
    video_codec: str = ""
    audio_codec: str = ""
    sample_rate: int = 0
    channels: int = 0
    raw: Optional[Dict[str, Any]] = None


def probe(path: Path, ffprobe: str, timeout: float = 60.0) -> MediaInfo:
    path = Path(path)
    if not path.is_file():
        raise FileNotFoundError(f"Media not found: {path}")
    if path.stat().st_size == 0:
        raise ValueError(f"Media file is empty: {path}")

    result = run(
        [
            ffprobe, "-v", "error", "-print_format", "json",
            "-show_format", "-show_streams", str(path),
        ],
        timeout=timeout,
    )
    if not result.ok:
        raise ProcessError(f"ffprobe could not read {path.name}: {result.tail()}")

    try:
        data = json.loads(result.stdout or "{}")
    except json.JSONDecodeError as exc:
        raise ProcessError(f"ffprobe returned invalid JSON for {path.name}") from exc

    streams: List[Dict[str, Any]] = data.get("streams", [])
    audio = next((s for s in streams if s.get("codec_type") == "audio"), None)
    video = next((s for s in streams if s.get("codec_type") == "video"), None)
    duration = 0.0
    try:
        duration = float(data.get("format", {}).get("duration") or 0.0)
    except (TypeError, ValueError):
        duration = 0.0
    if duration <= 0 and audio:
        try:
            duration = float(audio.get("duration") or 0.0)
        except (TypeError, ValueError):
            duration = 0.0

    return MediaInfo(
        path=str(path),
        duration=duration,
        format_name=data.get("format", {}).get("format_name", ""),
        has_audio=audio is not None,
        has_video=video is not None,
        width=int(video.get("width") or 0) if video else 0,
        height=int(video.get("height") or 0) if video else 0,
        video_codec=video.get("codec_name", "") if video else "",
        audio_codec=audio.get("codec_name", "") if audio else "",
        sample_rate=int(audio.get("sample_rate") or 0) if audio else 0,
        channels=int(audio.get("channels") or 0) if audio else 0,
        raw=data,
    )


def extract_audio(
    source: Path,
    destination: Path,
    ffmpeg: str,
    *,
    cancel: Optional[threading.Event] = None,
    timeout: float = 1800.0,
) -> Path:
    """Decode any supported media to 44.1 kHz stereo signed-16-bit PCM WAV."""

    source = Path(source)
    destination = Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)

    result = run(
        [
            ffmpeg, "-hide_banner", "-nostdin", "-y",
            "-i", str(source),
            "-vn", "-map", "0:a:0",
            "-ac", "2", "-ar", "44100", "-c:a", "pcm_s16le",
            str(destination),
        ],
        timeout=timeout,
        cancel=cancel,
    )
    if not result.ok:
        reason = "cancelled" if result.cancelled else "timed out" if result.timed_out else f"exit {result.returncode}"
        raise ProcessError(f"Audio extraction failed ({reason}): {result.tail()}")
    if not destination.is_file() or destination.stat().st_size < 1024:
        raise ProcessError("Audio extraction produced no usable output.")
    return destination


def decode_test(path: Path, ffmpeg: str, timeout: float = 600.0) -> bool:
    """Decode the whole file to null; True only if FFmpeg reports no errors."""

    result = run(
        [ffmpeg, "-v", "error", "-nostdin", "-i", str(path), "-f", "null", "-"],
        timeout=timeout,
    )
    return result.ok and not result.stderr.strip()


def ffmpeg_filter_path(path: Path) -> str:
    """Escape a filesystem path for use inside an FFmpeg filter argument.

    Windows paths are the awkward case: ``C:\\x\\y.ass`` must become
    ``C\\:/x/y.ass`` inside the filter graph.
    """

    text = str(Path(path).resolve()).replace("\\", "/")
    if os.name == "nt" and len(text) > 1 and text[1] == ":":
        text = text[0] + "\\:" + text[2:]
    for char in ("'", "[", "]", ",", ";"):
        text = text.replace(char, "\\" + char)
    return text
