"""Vocal-removal tests, including a physical Goertzel amplitude proof.

Fixture layout: 440 Hz is the centre-panned "vocal", 220 Hz is the
phase-inverted "music".  A correct centre-cancel must zero 440 Hz while
leaving 220 Hz untouched.
"""

from __future__ import annotations

import math
import wave
from array import array

import pytest

from abikaraoke.config import AppConfig
from abikaraoke.separation import (
    SeparationError,
    build_demucs_command,
    center_cancel,
    extract_mid,
    find_demucs_outputs,
    separate,
)
from abikaraoke.workspace import JobWorkspace
from tests.conftest import requires_ffmpeg


def goertzel_amplitude(path, frequency, seconds=4.0):
    """Return the amplitude of ``frequency`` in the first ``seconds`` of a WAV."""

    with wave.open(str(path), "rb") as handle:
        rate = handle.getframerate()
        channels = handle.getnchannels()
        width = handle.getsampwidth()
        assert width == 2
        frames = min(handle.getnframes(), int(rate * seconds))
        raw = handle.readframes(frames)

    samples = array("h")
    samples.frombytes(raw)
    if channels > 1:
        mono = [samples[i] / 32768.0 for i in range(0, len(samples), channels)]
    else:
        mono = [s / 32768.0 for s in samples]

    n = len(mono)
    k = int(0.5 + n * frequency / rate)
    omega = 2.0 * math.pi * k / n
    coeff = 2.0 * math.cos(omega)
    s_prev = s_prev2 = 0.0
    for sample in mono:
        s = sample + coeff * s_prev - s_prev2
        s_prev2, s_prev = s_prev, s
    power = s_prev2 ** 2 + s_prev ** 2 - coeff * s_prev * s_prev2
    # Goertzel magnitude for a sinusoid of amplitude A is A*N/2.
    return 2.0 * math.sqrt(max(0.0, power)) / n


def test_demucs_command_is_scoped_and_explicit(tmp_path):
    command = build_demucs_command(
        "/usr/bin/python3", tmp_path / "in.wav", tmp_path / "out",
        model="htdemucs", device="cpu", segment=7,
    )
    assert command[:3] == ["/usr/bin/python3", "-m", "demucs"]
    assert "--two-stems=vocals" in command
    assert str(tmp_path / "out") in command
    assert str(tmp_path / "in.wav") in command


def test_find_demucs_outputs_uses_exact_track_stem(tmp_path):
    track = tmp_path / "htdemucs" / "song"
    track.mkdir(parents=True)
    (track / "no_vocals.wav").write_bytes(b"x")
    (track / "vocals.wav").write_bytes(b"x")
    instrumental, vocals = find_demucs_outputs(tmp_path, "song")
    assert instrumental == track / "no_vocals.wav"
    assert vocals == track / "vocals.wav"


def test_find_demucs_outputs_ignores_other_tracks(tmp_path):
    other = tmp_path / "htdemucs" / "other_song"
    other.mkdir(parents=True)
    (other / "no_vocals.wav").write_bytes(b"x")
    instrumental, vocals = find_demucs_outputs(tmp_path, "song")
    assert instrumental is None and vocals is None


@requires_ffmpeg
def test_center_cancel_removes_centre_vocal_and_keeps_music(song_wav, tmp_path):
    config = AppConfig(data_dir=str(tmp_path / "data"))
    instrumental = tmp_path / "instrumental.wav"
    vocals = tmp_path / "vocals.wav"

    center_cancel(song_wav, instrumental, config.resolve_ffmpeg())
    extract_mid(song_wav, vocals, config.resolve_ffmpeg())

    vocal_before = goertzel_amplitude(song_wav, 440)
    music_before = goertzel_amplitude(song_wav, 220)
    vocal_after = goertzel_amplitude(instrumental, 440)
    music_after = goertzel_amplitude(instrumental, 220)
    vocal_stem = goertzel_amplitude(vocals, 440)
    music_stem = goertzel_amplitude(vocals, 220)

    # The centre vocal is gone from the instrumental (>= 95% attenuation).
    assert vocal_after < vocal_before * 0.05
    # The phase-inverted music survives intact (within 10%).
    assert music_after > music_before * 0.90
    # The vocal stem keeps the vocal and drops the music.
    assert vocal_stem > vocal_before * 0.50
    assert music_stem < music_before * 0.10


@requires_ffmpeg
def test_separate_center_method_writes_validated_outputs(song_wav, tmp_path):
    config = AppConfig(data_dir=str(tmp_path / "data"))
    workspace = JobWorkspace.create(song_wav, base_dir=tmp_path / "jobs")
    result = separate(workspace, config, source_audio=song_wav, method="center")

    assert result.method == "center-cancel"
    assert result.vocals_path is not None
    assert abs(result.duration - 12.0) < 0.5
    # Amplitudes are normalised (full-scale = 1.0): vocal ≈ 0.30, music ≈ 0.20.
    assert goertzel_amplitude(result.instrumental_path, 440) < 0.01
    assert goertzel_amplitude(result.instrumental_path, 220) > 0.15


@requires_ffmpeg
def test_separate_none_keeps_original_mix(song_wav, tmp_path):
    config = AppConfig(data_dir=str(tmp_path / "data"))
    workspace = JobWorkspace.create(song_wav, base_dir=tmp_path / "jobs")
    result = separate(workspace, config, source_audio=song_wav, method="none")
    assert result.method == "none"
    assert goertzel_amplitude(result.instrumental_path, 440) > 0.20


def test_separate_missing_source_raises(tmp_path):
    config = AppConfig(data_dir=str(tmp_path / "data"))
    workspace = JobWorkspace.create(__file__, base_dir=tmp_path / "jobs")
    with pytest.raises(SeparationError):
        separate(workspace, config, source_audio=tmp_path / "missing.wav", method="center")
