"""Headless smoke test for the PySide6 desktop UI."""

from __future__ import annotations

import os

import pytest

pytest.importorskip("PySide6")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QTimer  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from abikaraoke import gui  # noqa: E402
from abikaraoke.config import AppConfig  # noqa: E402


def test_gui_builds_and_exits_cleanly(tmp_path, monkeypatch):
    original_exec = QApplication.exec

    def patched_exec(self=None):
        QTimer.singleShot(250, QApplication.instance().quit)
        return original_exec()

    monkeypatch.setattr(QApplication, "exec", patched_exec)
    assert gui.launch(AppConfig(data_dir=str(tmp_path / "data"))) == 0
