"""Per-job workspaces and artifact manifests.

The original app reused fixed filenames (``work/song.wav``,
``no_vocals.wav``) across runs, so a stale file from another song could be
silently used.  Every run here gets a unique directory and a manifest that
records the source hash and every stage result.
"""

from __future__ import annotations

import hashlib
import json
import re
import shutil
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

MANIFEST_SCHEMA = 2


def sha256_file(path: Path, chunk_size: int = 1 << 20) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while True:
            chunk = handle.read(chunk_size)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def _slug(text: str, limit: int = 40) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "-", text).strip("-._")
    return (cleaned or "song")[:limit]


@dataclass
class JobWorkspace:
    root: Path
    job_id: str
    source: Path
    manifest: Dict[str, Any] = field(default_factory=dict)

    # -- construction ----------------------------------------------------
    @classmethod
    def create(
        cls,
        source: Path,
        base_dir: Optional[Path] = None,
        job_id: Optional[str] = None,
    ) -> "JobWorkspace":
        source = Path(source).expanduser().resolve()
        if not source.is_file():
            raise FileNotFoundError(f"Source media not found: {source}")

        if base_dir is None:
            from .config import default_data_dir

            base_dir = default_data_dir() / "jobs"
        base_dir = Path(base_dir)
        base_dir.mkdir(parents=True, exist_ok=True)

        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        digest = sha256_file(source)[:10]
        explicit_id = job_id is not None
        job_id = job_id or f"{stamp}-{_slug(source.stem, 24)}-{digest}"
        root = base_dir / job_id
        # Two jobs started in the same second must never share a directory:
        # that collision is what let one song overwrite another's stems.
        if not explicit_id:
            suffix = 2
            while root.exists():
                job_id = f"{stamp}-{_slug(source.stem, 24)}-{digest}-{suffix}"
                root = base_dir / job_id
                suffix += 1
        root.mkdir(parents=True, exist_ok=True)

        workspace = cls(root=root, job_id=job_id, source=source)
        workspace.manifest = {
            "schema": MANIFEST_SCHEMA,
            "app": "ABI Karaoke",
            "job_id": job_id,
            "created_utc": datetime.now(timezone.utc).isoformat(),
            "source": {
                "path": str(source),
                "name": source.name,
                "size": source.stat().st_size,
                "sha256": sha256_file(source),
            },
            "stages": {},
            "artifacts": {},
            "warnings": [],
        }
        workspace.save_manifest()
        return workspace

    # -- paths -----------------------------------------------------------
    def path(self, name: str) -> Path:
        return self.root / name

    @property
    def source_audio(self) -> Path:
        return self.path("source.wav")

    @property
    def instrumental(self) -> Path:
        return self.path("instrumental.wav")

    @property
    def vocals(self) -> Path:
        return self.path("vocals.wav")

    @property
    def lyrics_json(self) -> Path:
        return self.path("lyrics.json")

    @property
    def lrc(self) -> Path:
        return self.path("lyrics.lrc")

    @property
    def ass(self) -> Path:
        return self.path("karaoke.ass")

    @property
    def output(self) -> Path:
        return self.path("karaoke.mp4")

    @property
    def manifest_path(self) -> Path:
        return self.path("manifest.json")

    # -- manifest --------------------------------------------------------
    def save_manifest(self) -> Path:
        self.manifest["updated_utc"] = datetime.now(timezone.utc).isoformat()
        tmp = self.manifest_path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(self.manifest, indent=2), encoding="utf-8")
        tmp.replace(self.manifest_path)
        return self.manifest_path

    def stage(self, name: str, status: str, **info: Any) -> None:
        entry = self.manifest.setdefault("stages", {}).setdefault(name, {})
        entry.update({"status": status, "at": time.time(), **info})
        self.save_manifest()

    def artifact(self, name: str, path: Path, **info: Any) -> None:
        path = Path(path)
        record = {
            "path": str(path),
            "exists": path.is_file(),
            "size": path.stat().st_size if path.is_file() else 0,
            **info,
        }
        if path.is_file():
            record["sha256"] = sha256_file(path)
        self.manifest.setdefault("artifacts", {})[name] = record
        self.save_manifest()

    def warn(self, message: str) -> None:
        self.manifest.setdefault("warnings", []).append(message)
        self.save_manifest()

    def is_current_source(self) -> bool:
        """Guard against reusing artifacts from a different source file."""

        record = self.manifest.get("source", {})
        if not self.source.is_file():
            return False
        return record.get("sha256") == sha256_file(self.source)

    def cleanup(self, keep_intermediates: bool = False) -> None:
        if keep_intermediates:
            return
        for name in ("source.wav", "vocals.wav"):
            target = self.path(name)
            if target.exists():
                target.unlink()


def cleanup_old_jobs(base_dir: Path, keep: int = 20) -> List[Path]:
    """Delete the oldest job directories beyond ``keep``.  Returns removed paths."""

    base_dir = Path(base_dir)
    if not base_dir.is_dir():
        return []
    jobs = sorted(
        (p for p in base_dir.iterdir() if p.is_dir() and (p / "manifest.json").exists()),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    removed: List[Path] = []
    for old in jobs[keep:]:
        try:
            shutil.rmtree(old)
            removed.append(old)
        except OSError:
            pass
    return removed
