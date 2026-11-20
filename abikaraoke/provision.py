"""Fetch the small files the AI path needs, so "not configured" stops happening.

The original app required the user to hand-place ``whisper-cli.exe`` and a
``ggml-*.bin`` model.  Almost nobody did, so AI sync always failed with
"Please locate whisper-cli.exe first".  This module downloads a whisper.cpp
model on demand and can report exactly what is still missing.
"""

from __future__ import annotations

import shutil
import tempfile
import urllib.error
import urllib.request
from pathlib import Path
from typing import Callable, Dict, Optional

from . import __version__

MODEL_BASE = "https://huggingface.co/ggerganov/whisper.cpp/resolve/main"
# Ordered smallest-first; "base" is the quality/size sweet spot for lyrics.
MODEL_FILES: Dict[str, str] = {
    "tiny": "ggml-tiny.bin",
    "base": "ggml-base.bin",
    "small": "ggml-small.bin",
}
MODEL_SIZES_MB = {"tiny": 75, "base": 142, "small": 466}

USER_AGENT = f"ABIKaraoke/{__version__} (+https://github.com/ashokthrissur-cmd/karaokeking)"


class ModelError(RuntimeError):
    """A model could not be provisioned."""


def models_dir(data_dir: str | Path) -> Path:
    return Path(data_dir) / "models"


def model_path(data_dir: str | Path, size: str = "base") -> Path:
    filename = MODEL_FILES.get(size, MODEL_FILES["base"])
    return models_dir(data_dir) / filename


def has_model(data_dir: str | Path, size: str = "base") -> bool:
    path = model_path(data_dir, size)
    return path.is_file() and path.stat().st_size > 1_000_000


def _download(url: str, destination: Path, progress: Optional[Callable[[int, int], None]] = None) -> None:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    destination.parent.mkdir(parents=True, exist_ok=True)
    handle, temp_name = tempfile.mkstemp(dir=str(destination.parent), suffix=".part")
    temp = Path(temp_name)
    try:
        with urllib.request.urlopen(request, timeout=60) as response, open(handle, "wb") as out:
            total = int(response.headers.get("Content-Length") or 0)
            done = 0
            while True:
                chunk = response.read(1 << 20)
                if not chunk:
                    break
                out.write(chunk)
                done += len(chunk)
                if progress:
                    progress(done, total)
        if temp.stat().st_size < 1_000_000:
            raise ModelError("Downloaded file is too small to be a whisper model.")
        temp.replace(destination)
    except urllib.error.HTTPError as exc:
        raise ModelError(f"Model download failed: HTTP {exc.code}.") from exc
    except urllib.error.URLError as exc:
        raise ModelError(f"Cannot reach the model host ({exc.reason}).") from exc
    finally:
        if temp.exists():
            temp.unlink(missing_ok=True)


def ensure_whisper_model(
    data_dir: str | Path,
    size: str = "base",
    *,
    progress: Optional[Callable[[int, int], None]] = None,
) -> Path:
    """Return a local whisper.cpp model, downloading it if necessary."""

    if size not in MODEL_FILES:
        raise ModelError(f"Unknown model size {size!r}; choose from {sorted(MODEL_FILES)}.")
    destination = model_path(data_dir, size)
    if destination.is_file() and destination.stat().st_size > 1_000_000:
        return destination
    url = f"{MODEL_BASE}/{MODEL_FILES[size]}"
    _download(url, destination, progress)
    return destination


WHISPER_RELEASE = "v1.9.2"
WHISPER_ZIP = "whisper-bin-x64.zip"
WHISPER_URL = (
    f"https://github.com/ggerganov/whisper.cpp/releases/download/{WHISPER_RELEASE}/{WHISPER_ZIP}"
)


def whisper_tools_dir(data_dir: str | Path) -> Path:
    return Path(data_dir) / "tools" / "whisper"


def has_whisper_cli(data_dir: str | Path) -> bool:
    folder = whisper_tools_dir(data_dir)
    return any((folder / name).is_file() for name in ("whisper-cli.exe", "whisper-cli", "main.exe"))


def ensure_whisper_cli(
    data_dir: str | Path,
    *,
    progress: Optional[Callable[[int, int], None]] = None,
) -> Path:
    """Download whisper.cpp's Windows CLI so AI sync works without a manual setup.

    The official release ships ``whisper-cli.exe`` plus a handful of ``ggml-*``
    DLLs.  We unpack only the executables and DLLs, which keeps the footprint
    around 20 MB.
    """

    import zipfile

    folder = whisper_tools_dir(data_dir)
    existing = folder / "whisper-cli.exe"
    if existing.is_file():
        return existing

    archive = folder / WHISPER_ZIP
    _download(WHISPER_URL, archive, progress)
    try:
        with zipfile.ZipFile(archive) as zf:
            for member in zf.namelist():
                name = Path(member).name
                if not name:
                    continue
                lower = name.lower()
                if not (lower.endswith(".exe") or lower.endswith(".dll")):
                    continue
                # Skip the test/benchmark binaries we never call.
                if lower.startswith(("test-", "bench", "command", "parakeet-")):
                    continue
                target = folder / name
                with zf.open(member) as src, open(target, "wb") as out:
                    shutil.copyfileobj(src, out)
    except zipfile.BadZipFile as exc:
        raise ModelError("whisper.cpp download was corrupt; please retry.") from exc
    finally:
        archive.unlink(missing_ok=True)

    if not existing.is_file():
        raise ModelError("whisper.cpp archive did not contain whisper-cli.exe.")
    return existing


def find_whisper_cli(config) -> Optional[str]:
    """Locate whisper.cpp's CLI under any of the names it has shipped with."""

    explicit = config.resolve_whisper_cli()
    if explicit:
        return explicit
    for name in ("whisper-cli", "main", "whisper", "whisper-cpp"):
        found = shutil.which(name)
        if found:
            return found
    return None
