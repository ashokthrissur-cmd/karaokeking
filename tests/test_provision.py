"""The AI path must work without the user hand-placing binaries.

These tests cover the provisioning helpers that make ``abikaraoke setup``
sufficient on a clean Windows machine: locating a bundled ``whisper-cli`` and
unpacking the official whisper.cpp release.
"""

from __future__ import annotations

import zipfile
from pathlib import Path

import pytest

from abikaraoke import config as config_module
from abikaraoke import provision
from abikaraoke.config import AppConfig


def _make_app_layout(root: Path, exe_name: str = "whisper-cli") -> Path:
    """Create a portable-bundle layout: <root>/abikaraoke + <root>/whisper."""

    package = root / "abikaraoke"
    package.mkdir(parents=True)
    (package / "__init__.py").write_text("", encoding="utf-8")
    tools = root / "whisper"
    tools.mkdir()
    binary = tools / exe_name
    binary.write_text("", encoding="utf-8")
    binary.chmod(0o755)
    return binary


def test_bundled_whisper_cli_is_found(tmp_path, monkeypatch):
    binary = _make_app_layout(tmp_path)
    monkeypatch.setattr(config_module, "__file__", str(tmp_path / "abikaraoke" / "config.py"))

    found = AppConfig(data_dir=str(tmp_path / "data")).resolve_whisper_cli()

    assert found == str(binary)


def test_explicit_whisper_cli_wins(tmp_path, monkeypatch):
    _make_app_layout(tmp_path)
    monkeypatch.setattr(config_module, "__file__", str(tmp_path / "abikaraoke" / "config.py"))
    explicit = tmp_path / "custom-cli"
    explicit.write_text("", encoding="utf-8")
    explicit.chmod(0o755)

    found = AppConfig(
        data_dir=str(tmp_path / "data"), whisper_cli=str(explicit)
    ).resolve_whisper_cli()

    assert found == str(explicit)


def test_ensure_whisper_cli_extracts_the_release(tmp_path, monkeypatch):
    payload = tmp_path / "fake.zip"
    with zipfile.ZipFile(payload, "w") as zf:
        zf.writestr("Release/whisper-cli.exe", "MZ fake")
        zf.writestr("Release/ggml.dll", "dll")
        zf.writestr("Release/ggml-cpu-x64.dll", "dll")
        zf.writestr("Release/test-vad.exe", "skip me")
        zf.writestr("Release/README.md", "skip me too")

    def fake_download(url, destination, progress=None):
        Path(destination).parent.mkdir(parents=True, exist_ok=True)
        Path(destination).write_bytes(payload.read_bytes())

    monkeypatch.setattr(provision, "_download", fake_download)

    result = provision.ensure_whisper_cli(tmp_path)

    assert result.name == "whisper-cli.exe"
    assert result.is_file()
    folder = provision.whisper_tools_dir(tmp_path)
    assert (folder / "ggml.dll").is_file()
    assert (folder / "ggml-cpu-x64.dll").is_file()
    assert not (folder / "test-vad.exe").exists()
    assert not (folder / "README.md").exists()
    assert not list(folder.glob("*.zip")), "the archive should be cleaned up"
    assert provision.has_whisper_cli(tmp_path)


def test_ensure_whisper_cli_is_idempotent(tmp_path, monkeypatch):
    folder = provision.whisper_tools_dir(tmp_path)
    folder.mkdir(parents=True)
    (folder / "whisper-cli.exe").write_bytes(b"MZ")

    def explode(*args, **kwargs):
        raise AssertionError("should not download when the CLI is already present")

    monkeypatch.setattr(provision, "_download", explode)

    assert provision.ensure_whisper_cli(tmp_path).is_file()


def test_ensure_whisper_cli_rejects_a_corrupt_archive(tmp_path, monkeypatch):
    def fake_download(url, destination, progress=None):
        Path(destination).parent.mkdir(parents=True, exist_ok=True)
        Path(destination).write_bytes(b"not a zip")

    monkeypatch.setattr(provision, "_download", fake_download)

    with pytest.raises(provision.ModelError):
        provision.ensure_whisper_cli(tmp_path)


def test_model_size_mapping_is_sane():
    assert set(provision.MODEL_FILES) == {"tiny", "base", "small"}
    assert provision.MODEL_SIZES_MB["base"] < provision.MODEL_SIZES_MB["small"]
    assert provision.WHISPER_URL.startswith("https://")
    assert provision.WHISPER_URL.endswith(".zip")
