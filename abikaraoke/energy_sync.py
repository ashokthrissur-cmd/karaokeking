"""Dependency-free "Smart Sync" fallback based on vocal energy.

When no ASR backend is installed, the original app either failed or produced
meaningless evenly-spaced timestamps.  This module detects sung regions from
the separated vocal/instrumental track and packs lyric lines into those
regions, skipping instrumental gaps.  It is heuristic (confidence ~0.35) but
far better than a uniform spread, and it works with only FFmpeg.
"""

from __future__ import annotations

import array
import math
import wave
from pathlib import Path
from typing import List, Optional, Tuple

from .models import AlignmentReport, LyricLine, Lyrics, Word


def _read_wav(path: Path) -> Tuple[array.array, int, int]:
    with wave.open(str(path), "rb") as handle:
        channels = handle.getnchannels()
        width = handle.getsampwidth()
        rate = handle.getframerate()
        frames = handle.readframes(handle.getnframes())
    if width != 2:
        raise ValueError("Expected 16-bit PCM WAV for energy analysis.")
    samples = array.array("h")
    samples.frombytes(frames)
    return samples, channels, rate


def detect_vocal_regions(
    audio_path: Path,
    *,
    frame_seconds: float = 0.05,
    threshold_ratio: float = 0.12,
    min_gap: float = 0.30,
    min_region: float = 0.35,
) -> List[Tuple[float, float]]:
    """Return ``(start, end)`` regions where vocal energy is present."""

    samples, channels, rate = _read_wav(Path(audio_path))
    frame_size = max(1, int(rate * frame_seconds))
    stride = frame_size * channels
    energies: List[float] = []
    # RMS across all channels (not a mono downmix): a mono downmix can cancel
    # phase-inverted stereo music and report false silence.
    for offset in range(0, len(samples), stride):
        chunk = samples[offset:offset + stride]
        if not chunk:
            break
        rms = math.sqrt(sum(sample * sample for sample in chunk) / len(chunk))
        energies.append(rms)
    if not energies:
        return []

    peak = max(energies)
    if peak <= 0:
        return []
    ordered = sorted(energies)
    noise_floor = ordered[int(len(ordered) * 0.20)]
    # Cap the noise-floor term at half the peak: for continuously loud backing
    # tracks the 20th percentile is close to the peak, which would otherwise
    # put the threshold above every frame and report "no vocals".
    adaptive = min(noise_floor * 1.8, peak * 0.5)
    threshold = max(peak * threshold_ratio, adaptive, 60.0)

    active = [energy >= threshold for energy in energies]
    regions: List[Tuple[float, float]] = []
    start_index: Optional[int] = None
    for index, is_active in enumerate(active + [False]):
        if is_active and start_index is None:
            start_index = index
        elif not is_active and start_index is not None:
            regions.append((start_index * frame_seconds, index * frame_seconds))
            start_index = None

    merged: List[Tuple[float, float]] = []
    for region in regions:
        if merged and region[0] - merged[-1][1] <= min_gap:
            merged[-1] = (merged[-1][0], region[1])
        else:
            merged.append(region)
    return [r for r in merged if r[1] - r[0] >= min_region]


def spread_evenly(lyrics: Lyrics, duration: float, *, lead_in: float = 2.0) -> Lyrics:
    from .lrc import spread_plain_lyrics

    if duration <= 0:
        duration = max((ln.end for ln in lyrics.lines), default=0.0) or 30.0
    return spread_plain_lyrics(lyrics, duration, lead_in=min(lead_in, duration * 0.1))


def energy_sync(lyrics: Lyrics, audio_path: Path, duration: float) -> AlignmentReport:
    lines = [ln for ln in lyrics.sorted_lines() if ln.text.strip()]
    if not lines:
        return AlignmentReport(lines=[], method="none", warnings=["No lyric lines to align."])

    try:
        regions = detect_vocal_regions(Path(audio_path))
    except Exception as exc:
        spread = spread_evenly(lyrics, duration)
        return AlignmentReport(
            lines=spread.lines,
            method="even",
            matched_ratio=0.0,
            low_confidence_lines=list(range(len(spread.lines))),
            warnings=[f"Energy analysis failed ({exc}); timings were spread evenly."],
        )

    if not regions:
        spread = spread_evenly(lyrics, duration)
        return AlignmentReport(
            lines=spread.lines,
            method="even",
            matched_ratio=0.0,
            low_confidence_lines=list(range(len(spread.lines))),
            warnings=["No vocal activity detected; timings were spread evenly."],
        )

    active_total = sum(end - start for start, end in regions)
    weights = [max(1, len(line.text.split())) for line in lines]
    total_weight = sum(weights)

    def active_to_real(active_time: float) -> float:
        remaining = active_time
        for start, end in regions:
            span = end - start
            if remaining <= span:
                return start + remaining
            remaining -= span
        return regions[-1][1]

    result: List[LyricLine] = []
    cursor = 0.0
    for line, weight in zip(lines, weights):
        span = active_total * weight / total_weight
        start = active_to_real(cursor)
        end = active_to_real(min(active_total, cursor + span))
        cursor += span
        if end <= start:
            end = start + 0.4
        tokens = line.text.split()
        step = (end - start) / max(1, len(tokens))
        words = [
            Word(text=token, start=start + i * step, end=start + (i + 1) * step, confidence=0.35, synthetic=True)
            for i, token in enumerate(tokens)
        ]
        result.append(
            LyricLine(
                start=start,
                end=end,
                text=line.text,
                words=words,
                confidence=0.35,
                synthetic=True,
                source="energy",
            )
        )

    return AlignmentReport(
        lines=result,
        method="energy",
        matched_ratio=0.35,
        low_confidence_lines=list(range(len(result))),
        warnings=[
            "Smart Sync (energy) is a heuristic: review line timing before export. "
            "Install faster-whisper for word-level AI sync."
        ],
    )
