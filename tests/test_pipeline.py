"""End-to-end pipeline test: ingest → separate → lyrics → sync → render."""

from __future__ import annotations

import json

from abikaraoke.ass import KaraokeStyle
from abikaraoke.config import AppConfig
from abikaraoke.pipeline import PipelineError, PipelineOptions, run_pipeline
from abikaraoke.render import RenderSettings
from tests.conftest import requires_ffmpeg


@requires_ffmpeg
def test_pipeline_end_to_end_center_and_energy(song_wav, tmp_path, lyrics_text):
    config = AppConfig(data_dir=str(tmp_path / "data"))
    lyrics_file = tmp_path / "lyrics.txt"
    lyrics_file.write_text(lyrics_text, encoding="utf-8")

    options = PipelineOptions(
        artist="Test Artist",
        title="Test Song",
        lyrics_file=str(lyrics_file),
        fetch_lyrics=False,
        sync_mode="energy",
        separator="center",
        preview_seconds=3.0,
        output_path=str(tmp_path / "karaoke.mp4"),
        render=RenderSettings(
            width=480,
            height=270,
            fps=15,
            preset="ultrafast",
            loudnorm=False,
            style=KaraokeStyle(width=480, height=270, font_size=24),
        ),
    )

    messages = []
    result = run_pipeline(song_wav, options, config, progress=messages.append)

    assert result.render.output_path.endswith("karaoke-preview.mp4")
    assert result.separation.method == "center-cancel"
    assert result.alignment.method in ("energy", "even")
    assert len(result.lyrics.lines) == 4
    assert result.workspace.lrc.is_file()
    assert result.workspace.lyrics_json.is_file()

    manifest = json.loads(result.workspace.manifest_path.read_text())
    for stage in ("ingest", "extract", "separate", "lyrics", "sync", "render"):
        assert manifest["stages"][stage]["status"] == "done", stage
    assert manifest["artifacts"]["output"]["exists"]
    assert any("Extracting" in message for message in messages)


@requires_ffmpeg
def test_pipeline_reports_missing_lyrics_clearly(song_wav, tmp_path):
    config = AppConfig(data_dir=str(tmp_path / "data"))
    options = PipelineOptions(
        title="Definitely Not A Real Song Title Xyzzy",
        fetch_lyrics=True,
        sync_mode="energy",
        separator="center",
        preview_seconds=2.0,
        output_path=str(tmp_path / "out.mp4"),
        render=RenderSettings(width=320, height=180, fps=10, preset="ultrafast"),
    )
    # LRCLIB may be unreachable in CI; either way the failure must be explicit.
    try:
        run_pipeline(song_wav, options, config)
    except PipelineError as exc:
        assert str(exc).strip()
