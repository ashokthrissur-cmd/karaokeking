"""Configuration and tool discovery.

The original app guessed at ``python``/``python3``/``py`` on PATH and silently
fell back when Demucs was missing.  Here every tool has an explicit, testable
resolution order and a diagnostic report.
"""

from __future__ import annotations

import json
import os
import shutil
import sys
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Dict, List, Optional

APP_DIR_NAME = "ABIKaraoke"


def default_data_dir() -> Path:
    if os.name == "nt":
        base = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
    elif sys.platform == "darwin":
        base = str(Path.home() / "Library" / "Application Support")
    else:
        base = os.environ.get("XDG_DATA_HOME") or str(Path.home() / ".local" / "share")
    return Path(base) / APP_DIR_NAME


def _first_existing(candidates: List[Optional[str]]) -> Optional[str]:
    for candidate in candidates:
        if not candidate:
            continue
        expanded = os.path.expandvars(os.path.expanduser(candidate))
        if os.path.isfile(expanded) and os.access(expanded, os.X_OK):
            return expanded
        found = shutil.which(expanded)
        if found:
            return found
    return None


@dataclass
class AppConfig:
    data_dir: str = field(default_factory=lambda: str(default_data_dir()))
    ffmpeg: str = ""
    ffprobe: str = ""
    python: str = ""
    demucs_model: str = "htdemucs"
    demucs_device: str = "cpu"
    demucs_segment: int = 7
    whisper_backend: str = "auto"  # auto | faster-whisper | whisper.cpp | none
    whisper_model: str = "base"    # faster-whisper size or whisper.cpp .bin path
    whisper_model_path: str = ""
    whisper_cli: str = ""
    whisper_language: str = "auto"
    vad: bool = True
    compute_type: str = "int8"
    lyrics_timeout: float = 12.0
    lyrics_retries: int = 2
    job_timeout: float = 3600.0
    keep_intermediates: bool = False
    max_jobs: int = 20

    def __post_init__(self) -> None:
        if not self.ffmpeg:
            self.ffmpeg = _first_existing(["ffmpeg"]) or ""
        if not self.ffprobe:
            self.ffprobe = _first_existing(["ffprobe"]) or ""
        if not self.python:
            self.python = sys.executable or _first_existing(["python3", "python", "py"]) or ""

    # -- persistence -----------------------------------------------------
    @property
    def settings_path(self) -> Path:
        return Path(self.data_dir) / "settings.json"

    def save(self, path: Optional[Path] = None) -> Path:
        target = path or self.settings_path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(asdict(self), indent=2), encoding="utf-8")
        return target

    @classmethod
    def load(cls, path: Optional[Path] = None) -> "AppConfig":
        target = path or (default_data_dir() / "settings.json")
        if target.exists():
            try:
                data = json.loads(target.read_text(encoding="utf-8"))
                known = set(cls.__dataclass_fields__)  # type: ignore[attr-defined]
                return cls(**{k: v for k, v in data.items() if k in known})
            except Exception:
                pass
        return cls()

    # -- tool checks -----------------------------------------------------
    def resolve_ffmpeg(self) -> Optional[str]:
        self.ffmpeg = self.ffmpeg or (_first_existing(["ffmpeg"]) or "")
        return self.ffmpeg or None

    def resolve_ffprobe(self) -> Optional[str]:
        self.ffprobe = self.ffprobe or (_first_existing(["ffprobe"]) or "")
        return self.ffprobe or None

    def resolve_demucs_python(self) -> Optional[str]:
        """Return a Python interpreter that can import ``demucs``."""

        from .process import run

        candidates = [self.python, sys.executable, "python3", "python", "py"]
        seen = set()
        for candidate in candidates:
            if not candidate or candidate in seen:
                continue
            seen.add(candidate)
            exe = shutil.which(candidate) or candidate
            if not os.path.isfile(exe):
                continue
            try:
                result = run(
                    [exe, "-c", "import demucs, sys; print(demucs.__version__)"],
                    timeout=30,
                )
            except Exception:
                continue
            if result.ok:
                self.python = exe
                return exe
        return None

    def resolve_whisper_cli(self) -> Optional[str]:
        candidates = [
            self.whisper_cli,
            os.environ.get("WHISPER_CLI"),
            "whisper-cli",
            "whisper-cli.exe",
            "main.exe",
        ]
        found = _first_existing(candidates)
        if found:
            self.whisper_cli = found
        return found

    def resolve_whisper_model(self) -> Optional[str]:
        candidates = [self.whisper_model_path, os.environ.get("WHISPER_MODEL")]
        for candidate in candidates:
            if candidate:
                expanded = os.path.expanduser(os.path.expandvars(candidate))
                if os.path.isfile(expanded):
                    return expanded
        for name in ("ggml-base.bin", "ggml-small.bin", "ggml-tiny.bin"):
            for root in (Path.cwd(), Path(self.data_dir) / "models"):
                candidate = root / name
                if candidate.is_file():
                    return str(candidate)
        return None

    def doctor(self) -> List[Dict[str, str]]:
        """Return a human-readable capability report."""

        report: List[Dict[str, str]] = []

        def add(name: str, ok: bool, detail: str) -> None:
            report.append({"name": name, "status": "ok" if ok else "missing", "detail": detail})

        ffmpeg = self.resolve_ffmpeg()
        add("FFmpeg", bool(ffmpeg), ffmpeg or "Install FFmpeg and add it to PATH")
        ffprobe = self.resolve_ffprobe()
        add("FFprobe", bool(ffprobe), ffprobe or "Ships with FFmpeg")

        demucs_python = self.resolve_demucs_python()
        add(
            "Demucs (AI vocal removal)",
            bool(demucs_python),
            f"{demucs_python} (model {self.demucs_model})"
            if demucs_python
            else "pip install demucs  (center-cancel fallback still works)",
        )

        try:
            import faster_whisper  # noqa: F401

            add("faster-whisper", True, f"model '{self.whisper_model}'")
        except Exception:
            add("faster-whisper", False, "pip install faster-whisper  (or use whisper.cpp)")

        cli = self.resolve_whisper_cli()
        model = self.resolve_whisper_model()
        add("whisper.cpp", bool(cli and model), f"{cli or 'whisper-cli not found'}; model={model or 'not set'}")

        try:
            from PySide6 import QtCore  # noqa: F401

            add("PySide6 GUI", True, "available")
        except Exception:
            add("PySide6 GUI", False, "pip install PySide6 (CLI still works)")

        return report
