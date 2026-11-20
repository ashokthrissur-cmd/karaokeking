"""End-to-end karaoke pipeline: ingest → separate → lyrics → sync → render."""

from __future__ import annotations

import json
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, List, Optional

from .alignment import align_lyrics
from .config import AppConfig
from .energy_sync import energy_sync, spread_evenly
from .lrc import parse_lrc, parse_plain, to_lrc
from .lyrics import LyricsError, fetch_lyrics
from .media import extract_audio, probe
from .models import AlignmentReport, Lyrics, RenderResult, SeparationResult
from .render import RenderError, RenderSettings, render_video
from .separation import SeparationError, separate
from .transcription import TranscriptionError, transcribe
from .workspace import JobWorkspace, cleanup_old_jobs

Progress = Callable[[str], None]


class PipelineError(RuntimeError):
    pass


@dataclass
class PipelineOptions:
    artist: str = ""
    title: str = ""
    lyrics_file: Optional[str] = None
    fetch_lyrics: bool = True
    sync_mode: str = "auto"  # auto | ai | energy | none
    language: str = "auto"
    separator: str = "auto"  # auto | demucs | center | none
    render: RenderSettings = field(default_factory=RenderSettings)
    output_path: Optional[str] = None
    preview_seconds: Optional[float] = None
    keep_intermediates: bool = False


@dataclass
class PipelineResult:
    workspace: JobWorkspace
    lyrics: Lyrics
    separation: SeparationResult
    alignment: AlignmentReport
    render: RenderResult
    warnings: List[str] = field(default_factory=list)


def _noop(_: str) -> None:
    pass


def load_lyrics_file(path: Path) -> Lyrics:
    path = Path(path)
    if not path.is_file():
        raise PipelineError(f"Lyrics file not found: {path}")
    text = path.read_text(encoding="utf-8-sig", errors="replace")
    if "[" in text and any(ch.isdigit() for ch in text):
        parsed = parse_lrc(text, source="file")
        if parsed.lines:
            return parsed
    return parse_plain(text, source="file")


def _pick_sync_audio(workspace: JobWorkspace, separation: SeparationResult) -> Path:
    if separation.vocals_path and Path(separation.vocals_path).is_file():
        return Path(separation.vocals_path)
    return Path(separation.instrumental_path)


def run_pipeline(
    source: Path,
    options: PipelineOptions,
    config: AppConfig,
    *,
    cancel: Optional[threading.Event] = None,
    progress: Progress = _noop,
) -> PipelineResult:
    source = Path(source)
    if not source.is_file():
        raise PipelineError(f"Song file not found: {source}")

    workspace = JobWorkspace.create(source)
    warnings: List[str] = []
    workspace.stage("ingest", "running")

    try:
        ffprobe = config.resolve_ffprobe()
        ffmpeg = config.resolve_ffmpeg()
        if not ffprobe or not ffmpeg:
            raise PipelineError("FFmpeg and ffprobe are required. Install them and restart.")

        info = probe(source, ffprobe)
        if not info.has_audio:
            raise PipelineError("The selected file has no audio stream.")
        duration = info.duration
        workspace.stage("ingest", "done", duration=duration, format=info.format_name)
        progress(f"Loaded {source.name} ({duration:.1f}s).")

        # 1. Audio extraction -------------------------------------------------
        progress("Extracting audio (44.1 kHz stereo WAV)…")
        extract_audio(source, workspace.source_audio, ffmpeg, cancel=cancel, timeout=config.job_timeout)
        workspace.artifact("source_audio", workspace.source_audio)
        workspace.stage("extract", "done")
        if cancel is not None and cancel.is_set():
            raise PipelineError("Cancelled.")

        # 2. Vocal removal ----------------------------------------------------
        progress("Starting vocal removal…")
        separation = separate(
            workspace, config, method=options.separator, cancel=cancel, progress=progress
        )
        warnings.extend(separation.warnings)
        workspace.artifact("instrumental", Path(separation.instrumental_path), method=separation.method)
        if separation.vocals_path:
            workspace.artifact("vocals", Path(separation.vocals_path))
        workspace.stage("separate", "done", method=separation.method, elapsed=separation.elapsed)
        if cancel is not None and cancel.is_set():
            raise PipelineError("Cancelled.")

        # 3. Lyrics -----------------------------------------------------------
        progress("Loading lyrics…")
        if options.lyrics_file:
            lyrics = load_lyrics_file(Path(options.lyrics_file))
        elif options.fetch_lyrics:
            try:
                lyrics = fetch_lyrics(
                    options.artist,
                    options.title or source.stem,
                    duration=duration,
                    timeout=config.lyrics_timeout,
                    retries=config.lyrics_retries,
                    cache_dir=workspace.path("cache"),
                )
            except LyricsError as exc:
                raise PipelineError(str(exc)) from exc
        else:
            raise PipelineError("No lyrics: choose a lyrics file or enable LRCLIB lookup.")
        if not lyrics.lines:
            raise PipelineError("Lyrics are empty.")
        workspace.stage("lyrics", "done", source=lyrics.source, lines=len(lyrics.lines), synced=lyrics.synced)

        # 4. Timing -----------------------------------------------------------
        sync_mode = (options.sync_mode or "auto").lower()
        if sync_mode == "none" and lyrics.synced:
            alignment = AlignmentReport(
                lines=lyrics.sorted_lines(),
                method="existing",
                matched_ratio=1.0,
                warnings=[],
            )
            progress("Keeping existing LRC timing.")
        elif sync_mode == "energy":
            progress("Smart Sync: analysing vocal energy…")
            alignment = energy_sync(lyrics, _pick_sync_audio(workspace, separation), duration)
        elif sync_mode in ("ai", "auto"):
            audio_for_asr = _pick_sync_audio(workspace, separation)
            try:
                progress("AI Sync: transcribing vocals…")
                transcript = transcribe(audio_for_asr, config, cancel=cancel, progress=progress)
                progress(f"Aligning {len(lyrics.lines)} lyric lines to {len(transcript.words)} words…")
                alignment = align_lyrics(lyrics, transcript, duration=duration)
            except TranscriptionError as exc:
                if sync_mode == "ai":
                    raise PipelineError(str(exc)) from exc
                warnings.append(f"AI sync unavailable ({exc}); used energy sync instead.")
                progress("AI backend unavailable — using Smart Sync (energy).")
                alignment = energy_sync(lyrics, _pick_sync_audio(workspace, separation), duration)
        elif sync_mode == "none":
            if lyrics.synced:
                alignment = AlignmentReport(lines=lyrics.sorted_lines(), method="existing", matched_ratio=1.0)
            else:
                spread = spread_evenly(lyrics, duration)
                alignment = AlignmentReport(
                    lines=spread.lines,
                    method="even",
                    matched_ratio=0.0,
                    low_confidence_lines=list(range(len(spread.lines))),
                    warnings=["Lyrics had no timing; spread evenly (synthetic)."],
                )
        else:
            raise PipelineError(f"Unknown sync mode: {sync_mode}")

        warnings.extend(alignment.warnings)
        timed = Lyrics(
            lines=alignment.lines,
            source=lyrics.source,
            synced=alignment.method not in ("even", "none"),
            language=options.language if options.language != "auto" else lyrics.language,
            title=lyrics.title or options.title,
            artist=lyrics.artist or options.artist,
            raw_lrc=lyrics.raw_lrc,
            warnings=list(lyrics.warnings),
        )
        workspace.lrc.write_text(to_lrc(timed), encoding="utf-8")
        workspace.lyrics_json.write_text(
            json.dumps(timed.to_dict(), indent=2, ensure_ascii=False), encoding="utf-8"
        )
        workspace.artifact("lrc", workspace.lrc)
        workspace.artifact("lyrics_json", workspace.lyrics_json)
        workspace.stage(
            "sync", "done", method=alignment.method,
            matched_ratio=round(alignment.matched_ratio, 3),
            low_confidence=len(alignment.low_confidence_lines),
        )
        if cancel is not None and cancel.is_set():
            raise PipelineError("Cancelled.")

        # 5. Render -----------------------------------------------------------
        output = Path(options.output_path) if options.output_path else workspace.output
        render_duration = duration
        if options.preview_seconds:
            render_duration = min(duration, float(options.preview_seconds))
            output = output.with_name(output.stem + "-preview" + output.suffix)

        progress("Rendering karaoke video…")
        render_result = render_video(
            Path(separation.instrumental_path),
            timed,
            output,
            options.render,
            config,
            duration=render_duration,
            cancel=cancel,
            progress=progress,
        )
        warnings.extend(render_result.warnings)
        workspace.artifact("output", Path(render_result.output_path))
        workspace.stage("render", "done", output=render_result.output_path, duration=render_result.duration)

        for warning in warnings:
            workspace.warn(warning)
        workspace.cleanup(keep_intermediates=options.keep_intermediates or config.keep_intermediates)
        cleanup_old_jobs(workspace.root.parent, keep=config.max_jobs)

        return PipelineResult(
            workspace=workspace,
            lyrics=timed,
            separation=separation,
            alignment=alignment,
            render=render_result,
            warnings=warnings,
        )
    except Exception as exc:
        workspace.stage("pipeline", "failed", error=str(exc))
        raise
