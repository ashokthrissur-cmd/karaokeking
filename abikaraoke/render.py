"""FFmpeg karaoke renderer with post-render validation."""

from __future__ import annotations

import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, List, Optional

from .ass import KaraokeStyle, write_ass
from .config import AppConfig
from .media import decode_test, ffmpeg_filter_path, probe
from .models import Lyrics, RenderResult
from .process import ProcessError, run

Progress = Callable[[str], None]


class RenderError(RuntimeError):
    pass


@dataclass
class RenderSettings:
    width: int = 1920
    height: int = 1080
    fps: int = 30
    crf: int = 20
    preset: str = "veryfast"
    background: Optional[str] = None
    loudnorm: bool = True
    audio_bitrate: str = "192k"
    style: KaraokeStyle = field(default_factory=KaraokeStyle)

    def __post_init__(self) -> None:
        self.style.width = self.width
        self.style.height = self.height


def ffmpeg_has_filter(ffmpeg: str, name: str = "ass") -> bool:
    try:
        result = run([ffmpeg, "-hide_banner", "-filters"], timeout=30)
    except Exception:
        return False
    return result.ok and any(f" {name} " in line for line in result.stdout.splitlines())


def _background_args(settings: RenderSettings, duration: float) -> List[str]:
    background = settings.background
    if background and Path(background).is_file():
        suffix = Path(background).suffix.lower()
        if suffix in {".mp4", ".mkv", ".mov", ".webm", ".avi", ".m4v"}:
            return ["-stream_loop", "-1", "-i", str(background)]
        return ["-loop", "1", "-i", str(background)]
    return [
        "-f", "lavfi",
        "-i",
        f"gradients=s={settings.width}x{settings.height}:c0=0x0B1020:c1=0x2A1B4A:"
        f"x0=0:y0=0:x1={settings.width}:y1={settings.height}:d={max(1.0, duration):.3f}:r={settings.fps}",
    ]


def render_video(
    audio_path: Path,
    lyrics: Lyrics,
    output_path: Path,
    settings: RenderSettings,
    config: AppConfig,
    *,
    duration: float = 0.0,
    cancel: Optional[threading.Event] = None,
    progress: Progress = lambda _: None,
) -> RenderResult:
    ffmpeg = config.resolve_ffmpeg()
    ffprobe = config.resolve_ffprobe()
    if not ffmpeg or not ffprobe:
        raise RenderError("FFmpeg/ffprobe are required to render video.")
    if not ffmpeg_has_filter(ffmpeg, "ass"):
        raise RenderError(
            "This FFmpeg build has no 'ass' filter (libass). Install a full FFmpeg build "
            "(e.g. gyan.dev on Windows) and try again."
        )

    audio_path = Path(audio_path)
    output_path = Path(output_path)
    if not audio_path.is_file():
        raise RenderError(f"Audio not found: {audio_path}")

    try:
        audio_info = probe(audio_path, ffprobe)
    except Exception as exc:  # unreadable / non-audio input
        raise RenderError(f"Cannot read audio '{audio_path.name}': {exc}") from exc
    duration = duration or audio_info.duration
    if duration <= 0:
        raise RenderError("Could not determine audio duration.")

    output_path.parent.mkdir(parents=True, exist_ok=True)
    ass_path = output_path.with_suffix(".ass")
    write_ass(ass_path, lyrics, settings.style)
    progress(f"Wrote {ass_path.name} ({len(lyrics.lines)} lines).")

    background = _background_args(settings, duration)
    filter_chain = (
        f"[0:v]scale={settings.width}:{settings.height}:force_original_aspect_ratio=increase,"
        f"crop={settings.width}:{settings.height},setsar=1[bg];"
        f"[bg]ass='{ffmpeg_filter_path(ass_path)}'[v]"
    )

    command = [
        ffmpeg, "-hide_banner", "-nostdin", "-y",
        *background,
        "-i", str(audio_path),
        "-filter_complex", filter_chain,
        "-map", "[v]", "-map", "1:a:0",
        "-c:v", "libx264", "-preset", settings.preset, "-crf", str(settings.crf),
        "-pix_fmt", "yuv420p", "-r", str(settings.fps),
        "-c:a", "aac", "-b:a", settings.audio_bitrate,
        "-movflags", "+faststart",
        "-t", f"{duration:.3f}",
        "-shortest",
    ]
    if settings.loudnorm:
        command += ["-af", "loudnorm=I=-16:TP=-1.5:LRA=11"]
    command.append(str(output_path))

    progress(f"Rendering {settings.width}x{settings.height} MP4…")
    result = run(
        command,
        timeout=config.job_timeout,
        cancel=cancel,
        heartbeat_interval=10.0,
        on_heartbeat=lambda elapsed: progress(f"Rendering… {int(elapsed)}s"),
    )
    if result.cancelled:
        raise RenderError("Render cancelled.")
    if result.timed_out:
        raise RenderError("Render timed out.")
    if result.returncode != 0 or not output_path.is_file():
        raise RenderError(f"FFmpeg render failed (exit {result.returncode}): {result.tail(3000)}")

    # -- post-render QA ------------------------------------------------
    warnings: List[str] = []
    info = probe(output_path, ffprobe)
    if not info.has_video or info.video_codec != "h264":
        raise RenderError("Rendered file has no H.264 video stream.")
    if not info.has_audio or info.audio_codec != "aac":
        raise RenderError("Rendered file has no AAC audio stream.")
    if abs(info.duration - duration) > max(2.0, duration * 0.03):
        warnings.append(
            f"Output duration {info.duration:.1f}s differs from audio {duration:.1f}s."
        )
    if (info.width, info.height) != (settings.width, settings.height):
        warnings.append(f"Output resolution {info.width}x{info.height} differs from requested.")
    if not decode_test(output_path, ffmpeg):
        raise RenderError("Rendered file failed a full decode test (corrupt output).")

    progress("Render validated (streams, duration, decode).")
    return RenderResult(
        output_path=str(output_path),
        duration=info.duration,
        width=info.width,
        height=info.height,
        video_codec=info.video_codec,
        audio_codec=info.audio_codec,
        warnings=warnings,
    )
