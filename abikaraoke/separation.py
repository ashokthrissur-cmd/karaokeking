"""Vocal removal: Demucs AI separation with a real, validated fallback.

Why the original failed:
  * it probed generic Python names and silently degraded;
  * it searched a shared output tree for the newest ``no_vocals.wav``, which
    could belong to a different song;
  * it never checked that the separated file was complete or decodable;
  * manual and automatic "Demucs" modes disagreed about falling back.

Here Demucs writes into a per-job directory, the output is discovered by exact
path, validated against the source duration, and fallback behaviour is explicit.
"""

from __future__ import annotations

import shutil
import threading
from pathlib import Path
from typing import Callable, List, Optional

from .config import AppConfig
from .media import MediaInfo, probe
from .models import SeparationResult
from .process import ProcessError, run
from .workspace import JobWorkspace

Progress = Callable[[str], None]


class SeparationError(RuntimeError):
    pass


def _noop(_: str) -> None:
    pass


def demucs_available(config: AppConfig) -> bool:
    return config.resolve_demucs_python() is not None


def build_demucs_command(
    python: str,
    source: Path,
    out_dir: Path,
    *,
    model: str = "htdemucs",
    device: str = "cpu",
    segment: int = 7,
) -> List[str]:
    """Construct a Demucs 4 command that writes exactly where we expect."""

    command = [
        python, "-m", "demucs",
        "--two-stems=vocals",
        "-n", model,
        "-o", str(out_dir),
        "--device", device,
    ]
    if segment and segment > 0:
        command += ["--segment", str(segment)]
    command.append(str(source))
    return command


def find_demucs_outputs(out_dir: Path, track_stem: str) -> tuple[Optional[Path], Optional[Path]]:
    """Locate ``no_vocals.wav`` / ``vocals.wav`` produced under ``out_dir``.

    Demucs nests output as ``<out>/<model>/<track>/<stem>.wav``.  We prefer the
    exact track folder, then fall back to any match inside this job's own
    directory (never a shared tree).
    """

    out_dir = Path(out_dir)
    if not out_dir.is_dir():
        return None, None

    preferred_dirs = [p for p in out_dir.rglob(track_stem) if p.is_dir()]
    search_roots = preferred_dirs + [out_dir]

    for root in search_roots:
        instrumental = root / "no_vocals.wav"
        vocals = root / "vocals.wav"
        if instrumental.is_file():
            return instrumental, vocals if vocals.is_file() else None

    # No blind fallback.  The original app scanned for the newest
    # ``no_vocals.wav`` anywhere in a shared tree, so it could happily render
    # a different song's instrumental.  Returning None lets the caller raise
    # an honest error instead of producing a wrong video.
    return None, None


def extract_mid(
    source: Path,
    destination: Path,
    ffmpeg: str,
    *,
    cancel: Optional[threading.Event] = None,
    timeout: float = 1800.0,
) -> Path:
    """Extract the centre (mid) signal as a rough vocal stem for sync/energy."""

    destination.parent.mkdir(parents=True, exist_ok=True)
    result = run(
        [
            ffmpeg, "-hide_banner", "-nostdin", "-y",
            "-i", str(source),
            "-af", "pan=mono|c0=0.5*c0+0.5*c1",
            "-ac", "1", "-c:a", "pcm_s16le",
            str(destination),
        ],
        timeout=timeout,
        cancel=cancel,
    )
    if not result.ok or not destination.is_file():
        return destination if destination.is_file() else destination
    return destination


def center_cancel(
    source: Path,
    destination: Path,
    ffmpeg: str,
    *,
    cancel: Optional[threading.Event] = None,
    timeout: float = 1800.0,
) -> Path:
    """Remove centre-panned content with a mid/side subtraction.

    This is not source separation: it also thins bass, drums and lead
    instruments.  It is fast and dependency-free, and is always labelled as a
    lower-quality fallback.
    """

    destination.parent.mkdir(parents=True, exist_ok=True)
    result = run(
        [
            ffmpeg, "-hide_banner", "-nostdin", "-y",
            "-i", str(source),
            "-af", "pan=stereo|c0=0.5*c0-0.5*c1|c1=0.5*c1-0.5*c0",
            "-c:a", "pcm_s16le",
            str(destination),
        ],
        timeout=timeout,
        cancel=cancel,
    )
    if not result.ok:
        reason = "cancelled" if result.cancelled else "timed out" if result.timed_out else f"exit {result.returncode}"
        raise SeparationError(f"Center-cancel fallback failed ({reason}): {result.tail()}")
    if not destination.is_file() or destination.stat().st_size < 1024:
        raise SeparationError("Center-cancel fallback produced no usable audio.")
    return destination


def _center_with_vocals(
    workspace: JobWorkspace,
    source: Path,
    ffmpeg: str,
    cancel: Optional[threading.Event],
) -> tuple[Path, Optional[Path]]:
    instrumental = center_cancel(source, workspace.instrumental, ffmpeg, cancel=cancel)
    vocals = extract_mid(source, workspace.vocals, ffmpeg, cancel=cancel)
    return instrumental, vocals if vocals.is_file() else None


def _validate_output(path: Path, ffprobe: str, expected_duration: float, label: str) -> MediaInfo:
    info = probe(path, ffprobe)
    if not info.has_audio:
        raise SeparationError(f"{label} output has no audio stream.")
    if expected_duration > 0 and info.duration > 0:
        tolerance = max(2.0, expected_duration * 0.02)
        if abs(info.duration - expected_duration) > tolerance:
            raise SeparationError(
                f"{label} output duration {info.duration:.1f}s does not match source "
                f"{expected_duration:.1f}s; refusing to use a stale/incomplete file."
            )
    return info


def separate(
    workspace: JobWorkspace,
    config: AppConfig,
    *,
    source_audio: Optional[Path] = None,
    method: str = "auto",
    cancel: Optional[threading.Event] = None,
    progress: Progress = _noop,
) -> SeparationResult:
    """Produce an instrumental track for ``workspace``.

    ``method``:
      * ``auto``   – Demucs if installed, otherwise center-cancel;
      * ``demucs`` – require Demucs (raises with an install hint if missing);
      * ``center`` – force the fast fallback;
      * ``none``   – keep the original mix.
    """

    source = Path(source_audio or workspace.source_audio)
    if not source.is_file():
        raise SeparationError(f"Source audio not found: {source}")

    ffmpeg = config.resolve_ffmpeg()
    ffprobe = config.resolve_ffprobe()
    if not ffmpeg or not ffprobe:
        raise SeparationError("FFmpeg/ffprobe are required. Install FFmpeg and restart.")

    source_info = probe(source, ffprobe)
    expected = source_info.duration
    method = (method or "auto").lower()

    if method == "none":
        destination = workspace.instrumental
        shutil.copy2(source, destination)
        progress("Keeping the original mix (no vocal removal).")
        return SeparationResult(
            instrumental_path=str(destination),
            method="none",
            duration=expected,
            warnings=["Original mix kept; vocals were not removed."],
        )

    if method == "center":
        progress("Removing vocals with centre-cancel (fast, lower quality)…")
        destination, vocals = _center_with_vocals(workspace, source, ffmpeg, cancel)
        _validate_output(destination, ffprobe, expected, "Center-cancel")
        return SeparationResult(
            instrumental_path=str(destination),
            method="center-cancel",
            vocals_path=str(vocals) if vocals else None,
            duration=expected,
            warnings=[
                "Centre-cancel removes centre-panned vocals but also thins bass/drums. "
                "Install Demucs for true AI separation."
            ],
        )

    if method not in ("auto", "demucs"):
        raise ValueError(f"Unknown separation method: {method}")

    python = config.resolve_demucs_python()
    if python is None:
        message = (
            "Demucs is not installed for this Python interpreter. Run: "
            f'"{config.python}" -m pip install demucs'
        )
        if method == "demucs":
            raise SeparationError(message)
        progress("Demucs not found — using centre-cancel fallback.")
        destination, vocals = _center_with_vocals(workspace, source, ffmpeg, cancel)
        _validate_output(destination, ffprobe, expected, "Center-cancel")
        return SeparationResult(
            instrumental_path=str(destination),
            method="center-cancel",
            vocals_path=str(vocals) if vocals else None,
            duration=expected,
            warnings=[message, "Fell back to centre-cancel (lower quality)."],
        )

    out_dir = workspace.path("demucs")
    if out_dir.exists():
        shutil.rmtree(out_dir, ignore_errors=True)
    out_dir.mkdir(parents=True, exist_ok=True)

    command = build_demucs_command(
        python,
        source,
        out_dir,
        model=config.demucs_model,
        device=config.demucs_device,
        segment=config.demucs_segment,
    )
    progress(f"Running Demucs ({config.demucs_model}, {config.demucs_device}) — this can take a while…")

    result = run(
        command,
        timeout=config.job_timeout,
        cancel=cancel,
        heartbeat_interval=10.0,
        on_heartbeat=lambda elapsed: progress(f"Demucs still running… {int(elapsed)}s"),
    )

    if result.cancelled:
        raise SeparationError("Vocal removal cancelled.")
    if result.timed_out:
        raise SeparationError(
            f"Demucs timed out after {int(config.job_timeout)}s. Try a smaller model or shorter clip."
        )

    instrumental, vocals = find_demucs_outputs(out_dir, source.stem)
    if result.returncode != 0 or instrumental is None:
        tail = result.tail(2500)
        message = f"Demucs failed (exit {result.returncode}). {tail}".strip()
        if method == "demucs":
            raise SeparationError(message)
        progress("Demucs failed — using centre-cancel fallback.")
        destination, vocals = _center_with_vocals(workspace, source, ffmpeg, cancel)
        _validate_output(destination, ffprobe, expected, "Center-cancel")
        return SeparationResult(
            instrumental_path=str(destination),
            method="center-cancel",
            vocals_path=str(vocals) if vocals else None,
            duration=expected,
            warnings=[message, "Fell back to centre-cancel (lower quality)."],
        )

    _validate_output(instrumental, ffprobe, expected, "Demucs")

    destination = workspace.instrumental
    if Path(instrumental) != destination:
        shutil.copy2(instrumental, destination)

    vocals_destination: Optional[Path] = None
    if vocals and Path(vocals).is_file():
        vocals_destination = workspace.vocals
        shutil.copy2(vocals, vocals_destination)

    progress("Vocal removal complete (Demucs).")
    return SeparationResult(
        instrumental_path=str(destination),
        method="demucs",
        vocals_path=str(vocals_destination) if vocals_destination else None,
        duration=expected,
        elapsed=result.duration,
    )
