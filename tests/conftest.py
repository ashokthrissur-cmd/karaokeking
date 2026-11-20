"""Shared pytest fixtures for the ABI Karaoke rebuild.

The audio fixture is deliberately *physically meaningful*: a 440 Hz tone is
panned centre and in phase (the "vocal"), while a 220 Hz tone is phase-inverted
between channels (the "music").  A correct centre-cancel therefore removes the
440 Hz component and preserves the 220 Hz component, which lets the tests prove
vocal removal with a Goertzel amplitude measurement instead of eyeballing it.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

from abikaraoke.config import AppConfig

FFMPEG = shutil.which("ffmpeg")
FFPROBE = shutil.which("ffprobe")

requires_ffmpeg = pytest.mark.skipif(
    not (FFMPEG and FFPROBE), reason="FFmpeg/ffprobe not installed"
)


@pytest.fixture()
def config(tmp_path: Path) -> AppConfig:
    return AppConfig(data_dir=str(tmp_path / "data"))


@pytest.fixture(scope="session")
def song_wav(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """12 s stereo fixture: 440 Hz centre vocal + 220 Hz phase-inverted music."""

    if not FFMPEG:
        pytest.skip("FFmpeg not installed")
    path = tmp_path_factory.mktemp("media") / "song.wav"
    expression = (
        "0.30*sin(2*PI*440*t)+0.20*sin(2*PI*220*t)"
        "|0.30*sin(2*PI*440*t)-0.20*sin(2*PI*220*t)"
    )
    subprocess.run(
        [
            FFMPEG, "-hide_banner", "-loglevel", "error", "-y",
            "-f", "lavfi", "-i", f"aevalsrc={expression}:s=44100:d=12",
            "-c:a", "pcm_s16le", str(path),
        ],
        check=True,
    )
    return path


@pytest.fixture()
def lyrics_text() -> str:
    return (
        "Aadiyile sedhi kettadha\n"
        "En aasai machan vandhadha\n"
        "Kadhal ennum kadhal dhaan\n"
        "Paadum nenjam paadudhada\n"
    )
