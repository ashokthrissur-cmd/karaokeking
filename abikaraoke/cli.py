"""Command-line interface for ABI Karaoke."""

from __future__ import annotations

import argparse
import json
import sys
import threading
from pathlib import Path
from typing import List, Optional

from . import APP_NAME, __version__
from .alignment import align_lyrics
from .ass import KaraokeStyle
from .config import AppConfig
from .energy_sync import energy_sync
from .lrc import parse_lrc, parse_plain, to_lrc
from .lyrics import LyricsError, fetch_lyrics
from .media import probe
from .pipeline import PipelineOptions, load_lyrics_file, run_pipeline
from .render import RenderSettings, render_video
from .separation import separate
from .transcription import transcribe
from .workspace import JobWorkspace


def _progress(message: str) -> None:
    print(f"  · {message}", file=sys.stderr, flush=True)


def _resolution(value: str) -> tuple[int, int]:
    try:
        width, height = value.lower().split("x", 1)
        return int(width), int(height)
    except Exception as exc:
        raise argparse.ArgumentTypeError("Resolution must look like 1920x1080") from exc


def _style(args: argparse.Namespace) -> KaraokeStyle:
    width, height = args.resolution
    return KaraokeStyle(
        width=width,
        height=height,
        font=args.font,
        font_size=args.font_size,
        position=args.position,
        boxed=args.boxed,
        next_line=args.next_line,
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="abikaraoke", description=f"{APP_NAME} {__version__}")
    parser.add_argument("--version", action="version", version=f"{APP_NAME} {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("doctor", help="Check FFmpeg, Demucs, ASR and GUI availability")
    sub.add_parser("gui", help="Launch the desktop UI")

    setup_p = sub.add_parser("setup", help="Download the AI model so sync works offline")
    setup_p.add_argument("--model", default="base", choices=["tiny", "base", "small"])
    setup_p.add_argument("--install-extras", action="store_true",
                         help="Also pip install faster-whisper and demucs (large download)")

    separate_p = sub.add_parser("separate", help="Remove vocals from a song")
    separate_p.add_argument("source")
    separate_p.add_argument("--method", default="auto", choices=["auto", "demucs", "center", "none"])
    separate_p.add_argument("--out", default="instrumental.wav")

    lyrics_p = sub.add_parser("lyrics", help="Fetch lyrics from LRCLIB")
    lyrics_p.add_argument("--artist", default="")
    lyrics_p.add_argument("--track", required=True)
    lyrics_p.add_argument("--duration", type=float, default=0.0)
    lyrics_p.add_argument("--out", default="lyrics.lrc")

    sync_p = sub.add_parser("sync", help="Time lyrics against audio")
    sync_p.add_argument("--lyrics", required=True)
    sync_p.add_argument("--audio", required=True)
    sync_p.add_argument("--mode", default="auto", choices=["auto", "ai", "energy", "none"])
    sync_p.add_argument("--language", default="auto")
    sync_p.add_argument("--out", default="lyrics-synced.lrc")

    render_p = sub.add_parser("render", help="Render a karaoke MP4 from audio + LRC")
    render_p.add_argument("--audio", required=True)
    render_p.add_argument("--lyrics", required=True)
    render_p.add_argument("--out", default="karaoke.mp4")
    render_p.add_argument("--background", default=None)
    render_p.add_argument("--resolution", type=_resolution, default=(1920, 1080))
    render_p.add_argument("--font", default="Arial")
    render_p.add_argument("--font-size", type=int, default=64)
    render_p.add_argument("--position", default="bottom", choices=["bottom", "middle", "top"])
    render_p.add_argument("--boxed", action="store_true")
    render_p.add_argument("--next-line", action="store_true")
    render_p.add_argument("--no-loudnorm", action="store_true")

    run_p = sub.add_parser("run", help="Full pipeline: separate, lyrics, sync, render")
    run_p.add_argument("source")
    run_p.add_argument("--artist", default="")
    run_p.add_argument("--title", "--track", dest="track", default="")
    run_p.add_argument("--lyrics", "--lyrics-file", dest="lyrics_file", default=None)
    run_p.add_argument("--no-fetch", action="store_true")
    run_p.add_argument("--separator", default="auto", choices=["auto", "demucs", "center", "none"])
    run_p.add_argument("--sync", default="auto", choices=["auto", "ai", "energy", "none"])
    run_p.add_argument("--language", default="auto")
    run_p.add_argument("--out", default=None)
    run_p.add_argument("--background", default=None)
    run_p.add_argument("--resolution", type=_resolution, default=(1920, 1080))
    run_p.add_argument("--font", default="Arial")
    run_p.add_argument("--font-size", type=int, default=64)
    run_p.add_argument("--position", default="bottom", choices=["bottom", "middle", "top"])
    run_p.add_argument("--boxed", action="store_true")
    run_p.add_argument("--next-line", action="store_true")
    run_p.add_argument("--no-loudnorm", action="store_true")
    run_p.add_argument("--preview", type=float, default=None, help="Render only N seconds")
    run_p.add_argument("--keep-intermediates", action="store_true")
    return parser


def main(argv: Optional[List[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    config = AppConfig.load()

    try:
        if args.command == "doctor":
            print(f"{APP_NAME} {__version__} — capability check\n")
            for item in config.doctor():
                mark = "OK  " if item["status"] == "ok" else "MISS"
                print(f"[{mark}] {item['name']}: {item['detail']}")
            return 0

        if args.command == "setup":
            from .provision import (
                MODEL_SIZES_MB,
                ensure_whisper_cli,
                ensure_whisper_model,
            )

            size = args.model
            print(f"Downloading whisper.cpp model '{size}' "
                  f"(~{MODEL_SIZES_MB[size]} MB) into {config.data_dir} ...")

            def report(done: int, total: int) -> None:
                if total:
                    print(f"  {done * 100 // total:3d}%  ({done // 1048576} MB)", end="\r", flush=True)

            path = ensure_whisper_model(config.data_dir, size, progress=report)
            print(f"\nModel ready: {path}")

            print("Fetching whisper.cpp (the speech engine, ~20 MB) ...")
            cli_path = ensure_whisper_cli(config.data_dir, progress=report)
            print(f"\nSpeech engine ready: {cli_path}")
            if args.install_extras:
                import subprocess
                import sys as _sys
                print("Installing faster-whisper and demucs (this can take a while)...")
                subprocess.run([_sys.executable, "-m", "pip", "install",
                                "faster-whisper", "demucs"], check=False)
            print("\nRun 'abikaraoke doctor' to confirm.")
            return 0

        if args.command == "gui":
            from .gui import launch

            return launch(config)

        if args.command == "separate":
            source = Path(args.source)
            workspace = JobWorkspace.create(source)
            from .media import extract_audio

            ffmpeg = config.resolve_ffmpeg()
            if not ffmpeg:
                raise RuntimeError("FFmpeg not found.")
            _progress("Extracting audio…")
            extract_audio(source, workspace.source_audio, ffmpeg)
            result = separate(workspace, config, method=args.method, progress=_progress)
            destination = Path(args.out)
            if Path(result.instrumental_path) != destination:
                destination.write_bytes(Path(result.instrumental_path).read_bytes())
            print(json.dumps(
                {"output": str(destination), "method": result.method, "warnings": result.warnings},
                indent=2,
            ))
            return 0

        if args.command == "lyrics":
            lyrics = fetch_lyrics(
                args.artist, args.track, duration=args.duration or None, cache_dir=Path(".cache")
            )
            Path(args.out).write_text(to_lrc(lyrics), encoding="utf-8")
            print(f"Fetched {len(lyrics.lines)} lines from {lyrics.source} → {args.out}")
            for warning in lyrics.warnings:
                print(f"warning: {warning}", file=sys.stderr)
            return 0

        if args.command == "sync":
            lyrics = load_lyrics_file(Path(args.lyrics))
            info = probe(Path(args.audio), config.resolve_ffprobe() or "ffprobe")
            if args.mode in ("ai", "auto"):
                try:
                    transcript = transcribe(Path(args.audio), config, progress=_progress)
                    report = align_lyrics(lyrics, transcript, duration=info.duration)
                except Exception as exc:
                    if args.mode == "ai":
                        raise
                    _progress(f"AI unavailable ({exc}); using energy sync.")
                    report = energy_sync(lyrics, Path(args.audio), info.duration)
            elif args.mode == "energy":
                report = energy_sync(lyrics, Path(args.audio), info.duration)
            else:
                from .models import AlignmentReport

                report = AlignmentReport(lines=lyrics.sorted_lines(), method="existing")
            timed = lyrics
            timed.lines = report.lines
            Path(args.out).write_text(to_lrc(timed), encoding="utf-8")
            print(f"Synced {len(report.lines)} lines via {report.method} → {args.out}")
            print(f"matched: {report.matched_ratio:.0%}")
            for warning in report.warnings:
                print(f"warning: {warning}", file=sys.stderr)
            return 0

        if args.command == "render":
            lyrics = load_lyrics_file(Path(args.lyrics))
            settings = RenderSettings(
                width=args.resolution[0],
                height=args.resolution[1],
                background=args.background,
                loudnorm=not args.no_loudnorm,
                style=_style(args),
            )
            result = render_video(
                Path(args.audio), lyrics, Path(args.out), settings, config, progress=_progress
            )
            print(json.dumps(result.__dict__, indent=2, default=str))
            return 0

        if args.command == "run":
            width, height = args.resolution
            settings = RenderSettings(
                width=width,
                height=height,
                background=args.background,
                loudnorm=not args.no_loudnorm,
                style=_style(args),
            )
            options = PipelineOptions(
                artist=args.artist,
                title=args.track,
                lyrics_file=args.lyrics_file,
                fetch_lyrics=not args.no_fetch,
                sync_mode=args.sync,
                language=args.language,
                separator=args.separator,
                render=settings,
                output_path=args.out,
                preview_seconds=args.preview,
                keep_intermediates=args.keep_intermediates,
            )
            result = run_pipeline(Path(args.source), options, config, progress=_progress)
            print("\nDone.")
            print(f"  output:  {result.render.output_path}")
            print(f"  method:  separation={result.separation.method}, sync={result.alignment.method}")
            print(f"  lyrics:  {len(result.lyrics.lines)} lines")
            print(f"  job:     {result.workspace.root}")
            for warning in result.warnings:
                print(f"  warning: {warning}")
            return 0

        parser.print_help()
        return 2
    except KeyboardInterrupt:
        print("\nCancelled.", file=sys.stderr)
        return 130
    except Exception as exc:
        print(f"\nError: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
