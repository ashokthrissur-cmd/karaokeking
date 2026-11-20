"""Speech-to-text backends: faster-whisper (preferred) and whisper.cpp.

The original app only spoke whisper.cpp and failed with "Please locate
whisper-cli.exe first" even when a perfectly good Python ASR stack was
available.  This module auto-selects a backend, reports precisely what is
missing, and normalises both backends into one word-timed transcript.
"""

from __future__ import annotations

import json
import re
import threading
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from .config import AppConfig
from .models import Transcript, TranscriptWord
from .process import ProcessError, run

Progress = Callable[[str], None]


class TranscriptionError(RuntimeError):
    pass


def _noop(_: str) -> None:
    pass


_MODEL_CACHE: Dict[tuple, Any] = {}


def faster_whisper_available() -> bool:
    try:
        import faster_whisper  # noqa: F401

        return True
    except Exception:
        return False


def whisper_cpp_available(config: AppConfig) -> bool:
    return bool(config.resolve_whisper_cli() and config.resolve_whisper_model())


def _language(config: AppConfig) -> Optional[str]:
    lang = (config.whisper_language or "auto").strip().lower()
    return None if lang in ("", "auto", "detect") else lang


def _load_faster_whisper(config: AppConfig):
    from faster_whisper import WhisperModel

    key = (config.whisper_model, config.compute_type)
    if key not in _MODEL_CACHE:
        try:
            _MODEL_CACHE[key] = WhisperModel(
                config.whisper_model,
                device="cpu",
                compute_type=config.compute_type,
            )
        except Exception as exc:
            raise TranscriptionError(
                f"Could not load faster-whisper model '{config.whisper_model}': {exc}. "
                "Try model 'tiny' or 'base' on low-memory machines."
            ) from exc
    return _MODEL_CACHE[key]


def transcribe_faster_whisper(
    audio: Path,
    config: AppConfig,
    *,
    cancel: Optional[threading.Event] = None,
    progress: Progress = _noop,
) -> Transcript:
    if not faster_whisper_available():
        raise TranscriptionError("faster-whisper is not installed (pip install faster-whisper).")

    progress(f"Loading faster-whisper model '{config.whisper_model}'…")
    model = _load_faster_whisper(config)

    progress("Transcribing vocals with word timestamps…")
    try:
        segments, info = model.transcribe(
            str(audio),
            language=_language(config),
            word_timestamps=True,
            vad_filter=bool(config.vad),
            beam_size=5,
            condition_on_previous_text=False,
        )
    except Exception as exc:
        raise TranscriptionError(f"faster-whisper failed to start: {exc}") from exc

    words: List[TranscriptWord] = []
    text_parts: List[str] = []
    try:
        for segment in segments:
            if cancel is not None and cancel.is_set():
                raise TranscriptionError("Transcription cancelled.")
            segment_words = list(getattr(segment, "words", None) or [])
            if segment_words:
                for word in segment_words:
                    token = (getattr(word, "word", "") or "").strip()
                    if not token:
                        continue
                    words.append(
                        TranscriptWord(
                            text=token,
                            start=float(getattr(word, "start", segment.start) or 0.0),
                            end=float(getattr(word, "end", segment.end) or 0.0),
                            confidence=float(getattr(word, "probability", 1.0) or 1.0),
                        )
                    )
            elif getattr(segment, "text", "").strip():
                # No word timings: split the segment evenly so alignment still
                # has something monotonic to work with.
                tokens = segment.text.split()
                span = max(0.05, float(segment.end) - float(segment.start))
                step = span / max(1, len(tokens))
                for index, token in enumerate(tokens):
                    start = float(segment.start) + index * step
                    words.append(
                        TranscriptWord(text=token, start=start, end=start + step, confidence=0.5)
                    )
            text_parts.append(getattr(segment, "text", "").strip())
    except TranscriptionError:
        raise
    except Exception as exc:
        raise TranscriptionError(f"faster-whisper failed while transcribing: {exc}") from exc

    language = getattr(info, "language", None) or _language(config)
    warnings: List[str] = []
    if not words:
        warnings.append("The ASR model produced no words (is the vocal stem silent?).")
    return Transcript(
        words=words,
        text=" ".join(part for part in text_parts if part).strip(),
        language=language,
        backend="faster-whisper",
        warnings=warnings,
    )


def _parse_timestamp(value: str) -> float:
    match = re.match(r"(?:(\d+):)?(\d{1,2}):(\d{1,2})[.,](\d{1,3})", value or "")
    if not match:
        return 0.0
    hours = int(match.group(1) or 0)
    minutes = int(match.group(2))
    seconds = int(match.group(3))
    fraction = int(match.group(4))
    return hours * 3600 + minutes * 60 + seconds + fraction / (1000.0 if len(match.group(4)) == 3 else 100.0)


def parse_whisper_cpp_json(data: Dict[str, Any]) -> Transcript:
    """Parse whisper.cpp ``-oj`` output (both token and segment shapes)."""

    words: List[TranscriptWord] = []
    text_parts: List[str] = []
    language = data.get("result", {}).get("language") if isinstance(data.get("result"), dict) else None

    transcription = data.get("transcription")
    if isinstance(transcription, list):
        for item in transcription:
            if not isinstance(item, dict):
                continue
            text = (item.get("text") or "").strip()
            if not text:
                continue
            offsets = item.get("offsets") or {}
            timestamps = item.get("timestamps") or {}
            if offsets:
                start = float(offsets.get("from", 0)) / 1000.0
                end = float(offsets.get("to", 0)) / 1000.0
            elif timestamps:
                start = _parse_timestamp(str(timestamps.get("from", "")))
                end = _parse_timestamp(str(timestamps.get("to", "")))
            else:
                start = end = 0.0
            tokens = item.get("tokens")
            if isinstance(tokens, list) and tokens:
                for token in tokens:
                    if not isinstance(token, dict):
                        continue
                    token_text = (token.get("text") or "").strip()
                    if not token_text:
                        continue
                    token_offsets = token.get("offsets") or {}
                    t_start = float(token_offsets.get("from", start * 1000)) / 1000.0
                    t_end = float(token_offsets.get("to", end * 1000)) / 1000.0
                    words.append(TranscriptWord(text=token_text, start=t_start, end=max(t_start + 0.02, t_end)))
            else:
                words.append(TranscriptWord(text=text, start=start, end=max(start + 0.05, end)))
            text_parts.append(text)

    if not words and isinstance(data.get("segments"), list):
        for segment in data["segments"]:
            if not isinstance(segment, dict):
                continue
            text = (segment.get("text") or "").strip()
            start = float(segment.get("start", 0.0))
            end = float(segment.get("end", start + 0.1))
            if text:
                words.append(TranscriptWord(text=text, start=start, end=max(start + 0.05, end)))
                text_parts.append(text)

    return Transcript(
        words=merge_subword_tokens(words),
        text=" ".join(text_parts).strip(),
        language=language,
        backend="whisper.cpp",
        warnings=[] if words else ["whisper.cpp produced no words."],
    )


def merge_subword_tokens(words: List[TranscriptWord]) -> List[TranscriptWord]:
    """Merge BPE-style continuation tokens into linguistic words.

    whisper.cpp can emit ``"kara"`` + ``"oke"``; faster-whisper usually emits
    whole words.  A token that does not begin with whitespace is treated as a
    continuation of the previous word.
    """

    merged: List[TranscriptWord] = []
    for word in words:
        raw = word.text
        if not raw.strip():
            continue
        is_continuation = not raw[:1].isspace() and merged and not re.search(r"[\s]$", merged[-1].text)
        if is_continuation:
            previous = merged[-1]
            previous.text = (previous.text + raw.strip()).strip()
            previous.end = max(previous.end, word.end)
            previous.confidence = min(previous.confidence, word.confidence)
        else:
            merged.append(
                TranscriptWord(
                    text=raw.strip(),
                    start=word.start,
                    end=word.end,
                    confidence=word.confidence,
                )
            )
    return merged


def transcribe_whisper_cpp(
    audio: Path,
    config: AppConfig,
    *,
    cancel: Optional[threading.Event] = None,
    progress: Progress = _noop,
) -> Transcript:
    cli = config.resolve_whisper_cli()
    model = config.resolve_whisper_model()
    if not cli or not model:
        raise TranscriptionError(
            "whisper.cpp needs both whisper-cli and a ggml model. "
            "Download whisper-cli and ggml-base.bin, then set their paths in Settings."
        )

    out_base = audio.with_suffix("")
    command = [
        cli, "-m", model, "-f", str(audio),
        "-oj", "-of", str(out_base),
        "-l", _language(config) or "auto",
        "-ml", "1",
    ]
    if config.vad:
        command.append("--vad")

    progress("Transcribing with whisper.cpp…")
    result = run(command, timeout=config.job_timeout, cancel=cancel, heartbeat_interval=10.0)
    if result.cancelled:
        raise TranscriptionError("Transcription cancelled.")
    if result.timed_out:
        raise TranscriptionError("whisper.cpp timed out.")
    if result.returncode != 0:
        raise TranscriptionError(f"whisper.cpp failed: {result.tail(2500)}")

    json_path = Path(str(out_base) + ".json")
    if not json_path.is_file():
        raise TranscriptionError("whisper.cpp did not produce a JSON transcript.")
    try:
        data = json.loads(json_path.read_text(encoding="utf-8", errors="replace"))
    except json.JSONDecodeError as exc:
        raise TranscriptionError("whisper.cpp produced invalid JSON.") from exc
    return parse_whisper_cpp_json(data)


def transcribe(
    audio: Path,
    config: AppConfig,
    *,
    cancel: Optional[threading.Event] = None,
    progress: Progress = _noop,
) -> Transcript:
    """Auto-select an ASR backend and return a normalised transcript."""

    audio = Path(audio)
    if not audio.is_file():
        raise TranscriptionError(f"Audio for transcription not found: {audio}")

    backend = (config.whisper_backend or "auto").lower()
    if backend in ("auto", "faster-whisper", "faster_whisper"):
        if faster_whisper_available():
            return transcribe_faster_whisper(audio, config, cancel=cancel, progress=progress)
        if backend != "auto":
            raise TranscriptionError(
                "faster-whisper is selected but not installed. Run: "
                f'"{config.python}" -m pip install faster-whisper'
            )
    if backend in ("auto", "whisper.cpp", "whisper_cpp", "cpp"):
        if whisper_cpp_available(config):
            return transcribe_whisper_cpp(audio, config, cancel=cancel, progress=progress)
        if backend != "auto":
            raise TranscriptionError(
                "whisper.cpp is selected but whisper-cli/model are not configured."
            )

    raise TranscriptionError(
        "No AI transcription backend is available. Install faster-whisper "
        f'("{config.python}" -m pip install faster-whisper) or configure whisper.cpp. '
        "You can still use Smart Sync (energy) or manual LRC timing."
    )
