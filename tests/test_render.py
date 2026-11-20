"""Renderer tests: real FFmpeg encode plus post-render QA."""

from __future__ import annotations

import pytest

from abikaraoke.ass import KaraokeStyle
from abikaraoke.config import AppConfig
from abikaraoke.lrc import parse_lrc
from abikaraoke.media import probe
from abikaraoke.render import RenderError, RenderSettings, render_video
from tests.conftest import requires_ffmpeg


def _lyrics():
    return parse_lrc(
        "[00:00.50]Aadiyile sedhi kettadha\n"
        "[00:02.00]Kadhal ennum kadhal dhaan\n"
    )


@requires_ffmpeg
def test_render_produces_valid_h264_aac(song_wav, tmp_path):
    config = AppConfig(data_dir=str(tmp_path / "data"))
    settings = RenderSettings(
        width=640,
        height=360,
        fps=15,
        preset="ultrafast",
        loudnorm=False,
        style=KaraokeStyle(width=640, height=360, font_size=28),
    )
    output = tmp_path / "karaoke.mp4"
    result = render_video(
        song_wav, _lyrics(), output, settings, config, duration=3.0
    )

    assert output.is_file()
    assert result.video_codec == "h264"
    assert result.audio_codec == "aac"
    assert (result.width, result.height) == (640, 360)
    assert abs(result.duration - 3.0) < 1.0
    # The ASS sidecar is written next to the video.
    assert output.with_suffix(".ass").is_file()

    info = probe(output, config.resolve_ffprobe())
    assert info.has_video and info.has_audio


@requires_ffmpeg
def test_render_rejects_missing_audio(tmp_path):
    config = AppConfig(data_dir=str(tmp_path / "data"))
    with pytest.raises(RenderError):
        render_video(
            tmp_path / "missing.wav",
            _lyrics(),
            tmp_path / "out.mp4",
            RenderSettings(width=320, height=180),
            config,
            duration=1.0,
        )


@requires_ffmpeg
def test_render_rejects_unreadable_audio(tmp_path):
    config = AppConfig(data_dir=str(tmp_path / "data"))
    with pytest.raises(RenderError):
        render_video(
            __file__,
            _lyrics(),
            tmp_path / "out.mp4",
            RenderSettings(width=320, height=180),
            config,
            duration=0.0,
        )
