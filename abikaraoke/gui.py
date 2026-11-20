"""Desktop UI for ABI Karaoke.

The layout deliberately mirrors the original Windows app — a left sidebar with
Song / Websites / Automations / Plugins / More and four numbered panels — but
every long operation runs on a worker thread with progress reporting and a real
Cancel button.  The original ran Demucs and Whisper on the UI thread, which is
why it appeared to "do nothing" and then froze.

PySide6 is imported lazily so the CLI and the test suite work on machines
without Qt installed.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
from pathlib import Path
from typing import Optional

from . import APP_NAME, __version__
from .alignment import align_lyrics
from .ass import KaraokeStyle
from .config import AppConfig
from .lrc import parse_lrc, parse_plain, to_lrc
from .lyrics import (
    LyricsError,
    fetch_lyrics,
    fetch_lyrics_multi,
    lyrics_from_candidate,
    search_lyrics,
)
from .media import extract_audio, probe
from .models import Lyrics
from .naming import guess_from_path
from .pipeline import PipelineError, PipelineOptions, run_pipeline
from .render import RenderSettings
from .separation import separate
from .transcription import TranscriptionError, transcribe
from .workspace import JobWorkspace


def _install_hint() -> str:
    return "The desktop UI needs PySide6.\n\nInstall it with:\n\n    pip install PySide6\n"


def launch(config: Optional[AppConfig] = None) -> int:
    """Start the Qt event loop.  Returns the process exit code."""

    try:
        from PySide6.QtCore import Qt, QThread, Signal
        from PySide6.QtGui import QAction, QFont
        from PySide6.QtWidgets import (
            QApplication,
            QCheckBox,
            QComboBox,
            QDialog,
            QDialogButtonBox,
            QFileDialog,
            QFormLayout,
            QFrame,
            QGroupBox,
            QHBoxLayout,
            QLabel,
            QLineEdit,
            QListWidget,
            QMainWindow,
            QMessageBox,
            QPlainTextEdit,
            QProgressBar,
            QPushButton,
            QSpinBox,
            QSplitter,
            QStackedWidget,
            QTextEdit,
            QVBoxLayout,
            QWidget,
        )
    except ImportError as exc:  # pragma: no cover - depends on environment
        raise RuntimeError(_install_hint()) from exc

    config = config or AppConfig()

    # ------------------------------------------------------------------ workers
    class RenderWorker(QThread):
        progress = Signal(str)
        succeeded = Signal(object)
        failed = Signal(str)

        def __init__(self, source: Path, options: PipelineOptions, cancel: threading.Event):
            super().__init__()
            self.source = source
            self.options = options
            self.cancel = cancel

        def run(self) -> None:  # noqa: D401 - Qt entry point
            try:
                result = run_pipeline(
                    self.source,
                    self.options,
                    config,
                    cancel=self.cancel,
                    progress=self.progress.emit,
                )
                self.succeeded.emit(result)
            except Exception as exc:  # surface every failure in the UI
                self.failed.emit(str(exc))

    class SyncWorker(QThread):
        """Extract → separate → transcribe → align, without rendering."""

        progress = Signal(str)
        succeeded = Signal(object)
        failed = Signal(str)

        def __init__(self, source: Path, lyrics: Lyrics, separator: str, cancel: threading.Event):
            super().__init__()
            self.source = source
            self.lyrics = lyrics
            self.separator = separator
            self.cancel = cancel

        def run(self) -> None:
            try:
                workspace = JobWorkspace.create(self.source)
                ffmpeg = config.resolve_ffmpeg()
                ffprobe = config.resolve_ffprobe()
                if not ffmpeg or not ffprobe:
                    raise RuntimeError("FFmpeg/ffprobe are required.")

                self.progress.emit("Reading song…")
                info = probe(self.source, ffprobe)
                self.progress.emit("Extracting audio…")
                extract_audio(
                    self.source, workspace.source_audio, ffmpeg,
                    cancel=self.cancel, timeout=config.job_timeout,
                )

                self.progress.emit("Removing vocals…")
                separation = separate(
                    workspace, config, method=self.separator,
                    cancel=self.cancel, progress=self.progress.emit,
                )
                audio = Path(separation.vocals_path or separation.instrumental_path)

                self.progress.emit("Transcribing vocals…")
                transcript = transcribe(audio, config, cancel=self.cancel, progress=self.progress.emit)

                self.progress.emit("Aligning lyrics to the performance…")
                report = align_lyrics(self.lyrics, transcript, duration=info.duration)
                timed = Lyrics(
                    lines=report.lines,
                    source=self.lyrics.source,
                    synced=True,
                    title=self.lyrics.title,
                    artist=self.lyrics.artist,
                    raw_lrc=self.lyrics.raw_lrc,
                )
                workspace.lrc.write_text(to_lrc(timed), encoding="utf-8")
                self.succeeded.emit(
                    {"lyrics": timed, "report": report, "separation": separation, "workspace": workspace}
                )
            except Exception as exc:
                self.failed.emit(str(exc))

    # ------------------------------------------------------------------- window
    class MainWindow(QMainWindow):
        def __init__(self) -> None:
            super().__init__()
            self.setWindowTitle(f"{APP_NAME} {__version__}")
            self.resize(1180, 760)

            self.source: Optional[Path] = None
            self.lyrics: Optional[Lyrics] = None
            self.worker: Optional[QThread] = None
            self.cancel_event = threading.Event()
            self.last_output: Optional[Path] = None

            splitter = QSplitter(Qt.Horizontal)
            splitter.addWidget(self._build_sidebar())
            splitter.addWidget(self._build_main())
            splitter.setStretchFactor(1, 1)
            splitter.setSizes([210, 970])
            self.setCentralWidget(splitter)

            self._log(f"{APP_NAME} {__version__} ready.")
            self._check_tools()

        # -- sidebar -------------------------------------------------------
        def _build_sidebar(self) -> QWidget:
            panel = QFrame()
            panel.setObjectName("sidebar")
            panel.setStyleSheet(
                "#sidebar { background: #14161d; }"
                "QListWidget { background: #14161d; color: #d7dbe7; border: 0; font-size: 15px; }"
                "QListWidget::item { padding: 12px 16px; }"
                "QListWidget::item:selected { background: #2a2f3d; color: #ffd54a; }"
            )
            layout = QVBoxLayout(panel)
            layout.setContentsMargins(0, 16, 0, 16)

            brand = QLabel("ABI\nKARAOKE")
            brand.setStyleSheet("color:#ffd54a; font-size:22px; font-weight:800; padding:0 16px 12px 16px;")
            layout.addWidget(brand)

            self.nav = QListWidget()
            self.nav.addItems(["Song", "Websites", "Automations", "Plugins", "More"])
            self.nav.currentRowChanged.connect(self._nav_changed)
            layout.addWidget(self.nav, 1)

            version = QLabel(f"v{__version__}")
            version.setStyleSheet("color:#6b7280; padding:0 16px;")
            layout.addWidget(version)
            return panel

        def _nav_changed(self, row: int) -> None:
            self.pages.setCurrentIndex(max(0, min(row, self.pages.count() - 1)))

        # -- main ----------------------------------------------------------
        def _build_main(self) -> QWidget:
            self.pages = QStackedWidget()
            self.pages.addWidget(self._build_song_page())
            self.pages.addWidget(self._placeholder(
                "Websites",
                "Open the LRCLIB record for this track, or paste lyrics from any site.\n"
                "The old build had a dead button here; lyric lookup now reports exactly\n"
                "what happened (found / not found / network error).",
            ))
            self.pages.addWidget(self._placeholder(
                "Automations",
                "Batch mode: point ABI Karaoke at a folder and it will process every\n"
                "song with the same settings. Use the CLI today:\n\n"
                "    abikaraoke run song.mp3 --artist ... --title ... --out out.mp4",
            ))
            self.pages.addWidget(self._placeholder(
                "Plugins",
                "Separation and speech engines are pluggable:\n"
                "  • Demucs (best quality, GPU optional)\n"
                "  • Center-cancel (instant, no download)\n"
                "  • faster-whisper / whisper.cpp for timing",
            ))
            self.pages.addWidget(self._build_more_page())
            return self.pages

        def _placeholder(self, title: str, body: str) -> QWidget:
            page = QWidget()
            layout = QVBoxLayout(page)
            layout.setContentsMargins(28, 24, 28, 24)
            heading = QLabel(title)
            heading.setStyleSheet("font-size:24px; font-weight:700;")
            text = QLabel(body)
            text.setWordWrap(True)
            text.setStyleSheet("color:#9aa3b5; font-size:14px;")
            layout.addWidget(heading)
            layout.addWidget(text)
            layout.addStretch(1)
            return page

        def _build_song_page(self) -> QWidget:
            page = QWidget()
            outer = QVBoxLayout(page)
            outer.setContentsMargins(24, 20, 24, 20)
            outer.setSpacing(12)

            heading = QLabel("Make a karaoke video")
            heading.setStyleSheet("font-size:24px; font-weight:700;")
            subtitle = QLabel("Pick a song, get lyrics, align them to the vocal, render an MP4.")
            subtitle.setStyleSheet("color:#9aa3b5;")
            outer.addWidget(heading)
            outer.addWidget(subtitle)

            # 1 — song ------------------------------------------------------
            song_box = QGroupBox("1  Song")
            song_layout = QFormLayout(song_box)
            pick_row = QHBoxLayout()
            self.song_path = QLineEdit()
            self.song_path.setPlaceholderText("Choose an audio or video file…")
            self.song_path.setReadOnly(True)
            browse = QPushButton("Browse…")
            browse.clicked.connect(self._browse)
            pick_row.addWidget(self.song_path, 1)
            pick_row.addWidget(browse)
            song_layout.addRow("File", pick_row)

            self.artist_edit = QLineEdit()
            self.artist_edit.setPlaceholderText("Artist (optional, improves matching)")
            self.title_edit = QLineEdit()
            self.title_edit.setPlaceholderText("Title (defaults to the file name)")
            song_layout.addRow("Artist", self.artist_edit)
            song_layout.addRow("Title", self.title_edit)
            outer.addWidget(song_box)

            # 2 — lyrics & timing ------------------------------------------
            lyrics_box = QGroupBox("2  Lyrics & AI timing")
            lyrics_layout = QVBoxLayout(lyrics_box)
            lyrics_buttons = QHBoxLayout()
            self.fetch_button = QPushButton("Fetch lyrics (LRCLIB)")
            self.fetch_button.clicked.connect(self._fetch_lyrics)
            load_button = QPushButton("Load .lrc / .txt…")
            load_button.clicked.connect(self._load_lyrics_file)
            self.sync_button = QPushButton("AI auto-sync")
            self.sync_button.clicked.connect(self._auto_sync)
            lyrics_buttons.addWidget(self.fetch_button)
            lyrics_buttons.addWidget(load_button)
            lyrics_buttons.addWidget(self.sync_button)
            lyrics_buttons.addStretch(1)
            lyrics_layout.addLayout(lyrics_buttons)

            self.lyrics_edit = QTextEdit()
            self.lyrics_edit.setPlaceholderText("Lyrics appear here. You can edit them before syncing.")
            self.lyrics_edit.setMinimumHeight(140)
            lyrics_layout.addWidget(self.lyrics_edit)

            self.lyrics_status = QLabel("No lyrics loaded.")
            self.lyrics_status.setStyleSheet("color:#9aa3b5;")
            lyrics_layout.addWidget(self.lyrics_status)
            outer.addWidget(lyrics_box)

            # 3 — instrumental ---------------------------------------------
            separation_box = QGroupBox("3  Instrumental")
            separation_layout = QFormLayout(separation_box)
            self.separator_combo = QComboBox()
            self.separator_combo.addItems([
                "Automatic (Demucs if installed)",
                "Demucs (AI, best quality)",
                "Center-cancel (fast, no download)",
                "Keep original mix",
            ])
            separation_layout.addRow("Vocal removal", self.separator_combo)
            self.separation_status = QLabel("Not processed yet.")
            self.separation_status.setStyleSheet("color:#9aa3b5;")
            separation_layout.addRow("Status", self.separation_status)
            outer.addWidget(separation_box)

            # 4 — output ---------------------------------------------------
            output_box = QGroupBox("4  Karaoke video output")
            output_layout = QFormLayout(output_box)
            self.sync_combo = QComboBox()
            self.sync_combo.addItems(["Automatic", "AI (Whisper)", "Smart Sync (energy)", "Keep existing LRC"])
            output_layout.addRow("Timing", self.sync_combo)

            resolution_row = QHBoxLayout()
            self.width_spin = QSpinBox()
            self.width_spin.setRange(320, 3840)
            self.width_spin.setValue(1920)
            self.height_spin = QSpinBox()
            self.height_spin.setRange(180, 2160)
            self.height_spin.setValue(1080)
            resolution_row.addWidget(self.width_spin)
            resolution_row.addWidget(QLabel("×"))
            resolution_row.addWidget(self.height_spin)
            resolution_row.addStretch(1)
            output_layout.addRow("Resolution", resolution_row)

            self.next_line_check = QCheckBox("Show the next line")
            self.next_line_check.setChecked(True)
            output_layout.addRow("", self.next_line_check)
            outer.addWidget(output_box)

            # actions ------------------------------------------------------
            actions = QHBoxLayout()
            self.preview_button = QPushButton("Quick preview (20 s)")
            self.preview_button.clicked.connect(lambda: self._render(preview=20))
            self.render_button = QPushButton("MAKE KARAOKE VIDEO (automatic)")
            self.render_button.setStyleSheet(
                "QPushButton { background:#ffd54a; color:#14161d; font-weight:800; padding:12px 18px; }"
                "QPushButton:disabled { background:#4b4f5c; color:#9aa3b5; }"
            )
            self.render_button.clicked.connect(lambda: self._render(preview=None))
            self.cancel_button = QPushButton("Cancel")
            self.cancel_button.setEnabled(False)
            self.cancel_button.clicked.connect(self._cancel)
            actions.addWidget(self.preview_button)
            actions.addWidget(self.render_button, 1)
            actions.addWidget(self.cancel_button)
            outer.addLayout(actions)

            self.progress_bar = QProgressBar()
            self.progress_bar.setRange(0, 0)
            self.progress_bar.setVisible(False)
            outer.addWidget(self.progress_bar)

            self.log_view = QPlainTextEdit()
            self.log_view.setReadOnly(True)
            self.log_view.setMaximumHeight(150)
            self.log_view.setStyleSheet("background:#0f1116; color:#a9b4c7; font-family:monospace;")
            outer.addWidget(self.log_view)

            self.open_output_button = QPushButton("Open output folder")
            self.open_output_button.setEnabled(False)
            self.open_output_button.clicked.connect(self._open_output)
            outer.addWidget(self.open_output_button)
            return page

        def _build_more_page(self) -> QWidget:
            page = QWidget()
            layout = QVBoxLayout(page)
            layout.setContentsMargins(28, 24, 28, 24)
            heading = QLabel("More")
            heading.setStyleSheet("font-size:24px; font-weight:700;")
            layout.addWidget(heading)

            self.doctor_view = QPlainTextEdit()
            self.doctor_view.setReadOnly(True)
            self.doctor_view.setStyleSheet("font-family:monospace;")
            layout.addWidget(self.doctor_view, 1)

            refresh = QPushButton("Re-run capability check")
            refresh.clicked.connect(self._check_tools)
            layout.addWidget(refresh)
            return page

        # -- helpers -------------------------------------------------------
        def _log(self, message: str) -> None:
            self.log_view.appendPlainText(message)
            self.log_view.verticalScrollBar().setValue(
                self.log_view.verticalScrollBar().maximum()
            )

        def _check_tools(self) -> None:
            lines = [f"{APP_NAME} {__version__}", ""]
            for entry in config.doctor():
                ok = entry.get("status") == "ok"
                lines.append(f"[{'OK  ' if ok else 'MISS'}] {entry['name']}: {entry['detail']}")
            self.doctor_view.setPlainText("\n".join(lines))

        def _browse(self) -> None:
            path, _ = QFileDialog.getOpenFileName(
                self,
                "Choose a song",
                "",
                "Media (*.mp3 *.wav *.flac *.m4a *.aac *.ogg *.opus *.mp4 *.mkv *.mov *.webm);;All files (*)",
            )
            if not path:
                return
            self.source = Path(path)
            self.song_path.setText(path)
            # Parse the file name instead of dumping it into the title box.
            # Downloads are full of "HD video song" noise that makes every
            # lyric lookup miss.
            guess = guess_from_path(path)
            if guess.title:
                self.title_edit.setText(guess.title)
            if guess.artist:
                self.artist_edit.setText(guess.artist)
            if guess.title:
                detail = f"Detected title “{guess.title}”"
                if guess.artist:
                    detail += f" by {guess.artist}"
                detail += f" (confidence {int(guess.confidence * 100)}%)."
                if guess.confidence < 0.6:
                    detail += " Edit the fields if this is wrong."
                self._log(detail)
            self._log(f"Selected {self.source.name}.")

        def _set_busy(self, busy: bool) -> None:
            self.progress_bar.setVisible(busy)
            self.cancel_button.setEnabled(busy)
            for widget in (
                self.render_button, self.preview_button, self.sync_button,
                self.fetch_button, self.separator_combo, self.sync_combo,
            ):
                widget.setEnabled(not busy)

        def _cancel(self) -> None:
            self.cancel_event.set()
            self._log("Cancel requested — stopping the running job…")

        def _separator(self) -> str:
            return ["auto", "demucs", "center", "none"][self.separator_combo.currentIndex()]

        def _sync_mode(self) -> str:
            return ["auto", "ai", "energy", "none"][self.sync_combo.currentIndex()]

        def _style(self) -> KaraokeStyle:
            return KaraokeStyle(
                width=self.width_spin.value(),
                height=self.height_spin.value(),
                next_line=self.next_line_check.isChecked(),
            )

        def _require_source(self) -> bool:
            if self.source is None or not self.source.is_file():
                QMessageBox.warning(self, APP_NAME, "Choose a song file first.")
                return False
            return True

        # -- lyrics --------------------------------------------------------
        def _current_lyrics(self) -> Optional[Lyrics]:
            text = self.lyrics_edit.toPlainText().strip()
            if not text:
                return None
            if "[" in text and "]" in text and any(
                ch.isdigit() for ch in text.split("]", 1)[0]
            ):
                return parse_lrc(text)
            return parse_plain(text)

        def _fetch_lyrics(self) -> None:
            title = self.title_edit.text().strip()
            artist = self.artist_edit.text().strip()
            if not title and self.source:
                guess = guess_from_path(self.source)
                title, artist = guess.title, guess.artist or artist
                self.title_edit.setText(title)
                if artist:
                    self.artist_edit.setText(artist)
            if not title:
                QMessageBox.warning(self, APP_NAME, "Enter a title or choose a file first.")
                return

            queries = []
            if artist and title:
                queries.append(f"{artist} - {title}")
            queries.append(title)
            if self.source:
                queries.extend(guess_from_path(self.source).search_queries())
            seen, ordered = set(), []
            for q in queries:
                if q and q.casefold() not in seen:
                    seen.add(q.casefold())
                    ordered.append(q)

            self._log(f"Looking up {title!r} on LRCLIB (trying {len(ordered)} spelling(s))...")
            try:
                lyrics = fetch_lyrics_multi(
                    ordered,
                    duration=None,
                    timeout=config.lyrics_timeout,
                    retries=config.lyrics_retries,
                    cache_dir=Path(config.data_dir) / "lyrics-cache",
                )
            except LyricsError as exc:
                self._log(f"Automatic lookup failed: {exc}")
                self._search_lyrics_dialog(f"{artist} {title}".strip() or title)
                return

            self._apply_lyrics(lyrics)

        def _apply_lyrics(self, lyrics: Lyrics) -> None:
            self.lyrics = lyrics
            self.lyrics_edit.setPlainText(
                to_lrc(lyrics) if lyrics.synced
                else "\n".join(line.text for line in lyrics.sorted_lines())
            )
            state = "synced" if lyrics.synced else "plain (needs timing)"
            self.lyrics_status.setText(
                f"{len(lyrics.lines)} lines - {state} - {lyrics.source}"
            )
            self._log(f"Loaded {len(lyrics.lines)} lines ({state}) from {lyrics.source}.")

        def _search_lyrics_dialog(self, initial_query: str) -> None:
            """Manual LRCLIB search so a miss is never a dead end."""

            dialog = QDialog(self)
            dialog.setWindowTitle("Search lyrics")
            dialog.resize(640, 420)
            layout = QVBoxLayout(dialog)

            hint = QLabel(
                "Automatic matching failed. Search LRCLIB by title or artist and "
                "pick the correct record."
            )
            hint.setWordWrap(True)
            layout.addWidget(hint)

            row = QHBoxLayout()
            query_edit = QLineEdit(initial_query)
            search_button = QPushButton("Search")
            row.addWidget(query_edit, 1)
            row.addWidget(search_button)
            layout.addLayout(row)

            results = QListWidget()
            layout.addWidget(results, 1)
            status = QLabel("")
            status.setStyleSheet("color:#9aa3b5;")
            layout.addWidget(status)

            buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
            ok_button = buttons.button(QDialogButtonBox.Ok)
            ok_button.setText("Use selected lyrics")
            ok_button.setEnabled(False)
            layout.addWidget(buttons)

            found: list = []

            def do_search() -> None:
                results.clear()
                found.clear()
                ok_button.setEnabled(False)
                status.setText("Searching...")
                try:
                    candidates = search_lyrics(
                        query_edit.text(),
                        timeout=config.lyrics_timeout,
                        retries=config.lyrics_retries,
                    )
                except LyricsError as exc:
                    status.setText(str(exc))
                    return
                if not candidates:
                    status.setText("No records matched. Try fewer words.")
                    return
                found.extend(candidates)
                for candidate in candidates:
                    kind = "synced" if candidate.has_synced else "plain"
                    minutes = int(candidate.duration // 60)
                    seconds = int(candidate.duration % 60)
                    results.addItem(
                        f"{candidate.title} - {candidate.artist} "
                        f"({minutes}:{seconds:02d}, {kind})"
                    )
                status.setText(f"{len(candidates)} result(s). Pick one and press OK.")

            def on_row(row_index: int) -> None:
                ok_button.setEnabled(row_index >= 0)

            search_button.clicked.connect(do_search)
            query_edit.returnPressed.connect(do_search)
            results.currentRowChanged.connect(on_row)
            buttons.accepted.connect(dialog.accept)
            buttons.rejected.connect(dialog.reject)

            if initial_query:
                do_search()

            if dialog.exec() == QDialog.Accepted:
                row_index = results.currentRow()
                if 0 <= row_index < len(found):
                    try:
                        lyrics = lyrics_from_candidate(found[row_index])
                    except LyricsError as exc:
                        QMessageBox.warning(self, "Lyrics", str(exc))
                        return
                    self._apply_lyrics(lyrics)

        def _load_lyrics_file(self) -> None:
            path, _ = QFileDialog.getOpenFileName(
                self, "Load lyrics", "", "Lyrics (*.lrc *.txt);;All files (*)"
            )
            if not path:
                return
            text = Path(path).read_text(encoding="utf-8", errors="replace")
            self.lyrics_edit.setPlainText(text)
            self.lyrics = self._current_lyrics()
            if self.lyrics:
                state = "synced" if self.lyrics.synced else "plain (needs timing)"
                self.lyrics_status.setText(f"{len(self.lyrics.lines)} lines · {state} · {path}")
                self._log(f"Loaded lyrics from {Path(path).name}.")

        # -- sync ----------------------------------------------------------
        def _auto_sync(self) -> None:
            if not self._require_source():
                return
            lyrics = self._current_lyrics()
            if lyrics is None or not lyrics.lines:
                QMessageBox.warning(self, APP_NAME, "Fetch or paste lyrics before syncing.")
                return

            if not self._ensure_ai_ready():
                return

            self.cancel_event = threading.Event()
            self._set_busy(True)
            self._log("AI auto-sync started.")
            worker = SyncWorker(self.source, lyrics, self._separator(), self.cancel_event)
            worker.progress.connect(self._log)
            worker.succeeded.connect(self._sync_done)
            worker.failed.connect(self._failed)
            worker.finished.connect(lambda: self._set_busy(False))
            self.worker = worker
            worker.start()

        def _ensure_ai_ready(self) -> bool:
            """Offer to download what AI sync needs instead of failing outright."""

            from .provision import MODEL_SIZES_MB, ensure_whisper_cli, ensure_whisper_model
            from .transcription import faster_whisper_available, whisper_cpp_available

            if faster_whisper_available():
                return True
            if whisper_cpp_available(config):
                return True

            answer = QMessageBox.question(
                self,
                "AI sync needs a model",
                "No speech-recognition backend is installed yet.\n\n"
                f"Download the whisper.cpp 'base' model (~{MODEL_SIZES_MB['base']} MB) now?\n"
                "It is a one-time download and makes AI sync work offline.",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.Yes,
            )
            if answer != QMessageBox.Yes:
                self._log(
                    "AI sync skipped: no ASR backend. Install with "
                    "'pip install faster-whisper' or run 'abikaraoke setup'."
                )
                return False

            self._log("Downloading whisper model (one time)...")
            try:
                path = ensure_whisper_model(
                    config.data_dir,
                    "base",
                    progress=lambda done, total: self._log(
                        f"  model {done // 1048576} MB"
                        + (f" / {total // 1048576} MB" if total else "")
                    ) if done % (8 * 1048576) < 1048576 else None,
                )
            except Exception as exc:
                QMessageBox.warning(self, "Download failed", str(exc))
                self._log(f"Model download failed: {exc}")
                return False

            self._log(f"Model ready: {path}")
            if whisper_cpp_available(config):
                return True

            # The model alone is useless without whisper-cli, so fetch it too.
            self._log("Downloading the whisper.cpp speech engine (~20 MB)...")
            try:
                cli = ensure_whisper_cli(config.data_dir)
                self._log(f"Speech engine ready: {cli}")
            except Exception as exc:
                self._log(f"Speech engine download failed: {exc}")
            if whisper_cpp_available(config):
                return True

            # The model alone is useless without whisper-cli; fall back to
            # faster-whisper, which pip can install.
            answer = QMessageBox.question(
                self,
                "whisper.cpp not found",
                "The model downloaded, but whisper-cli is not installed.\n\n"
                "Install faster-whisper instead? (~200 MB, works without a separate binary.)",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.Yes,
            )
            if answer != QMessageBox.Yes:
                return False
            import subprocess
            import sys as _sys
            try:
                subprocess.run(
                    [_sys.executable, "-m", "pip", "install", "faster-whisper"],
                    check=True,
                )
            except Exception as exc:
                QMessageBox.warning(self, "Install failed", str(exc))
                return False
            return faster_whisper_available()

        def _sync_done(self, payload: object) -> None:
            data = payload  # type: ignore[assignment]
            lyrics = data["lyrics"]
            report = data["report"]
            self.lyrics = lyrics
            self.lyrics_edit.setPlainText(to_lrc(lyrics))
            self.lyrics_status.setText(
                f"{len(lyrics.lines)} lines · AI-synced · "
                f"{report.matched_ratio * 100:.0f}% matched · {report.method}"
            )
            self.separation_status.setText(
                f"{data['separation'].method} · {data['separation'].duration:.1f}s"
            )
            for warning in report.warnings:
                self._log(f"Warning: {warning}")
            self._log("AI auto-sync finished. Review the highlighted lines, then render.")

        # -- render --------------------------------------------------------
        def _render(self, preview: Optional[int]) -> None:
            if not self._require_source():
                return
            lyrics = self._current_lyrics()
            if lyrics is None or not lyrics.lines:
                QMessageBox.warning(self, APP_NAME, "Fetch or paste lyrics first.")
                return

            output = Path(config.data_dir) / "output" / f"{self.source.stem}-karaoke.mp4"
            options = PipelineOptions(
                artist=self.artist_edit.text().strip(),
                title=self.title_edit.text().strip() or self.source.stem,
                lyrics_file=None,
                fetch_lyrics=False,
                sync_mode=self._sync_mode(),
                separator=self._separator(),
                preview_seconds=preview,
                output_path=str(output),
                render=RenderSettings(style=self._style()),
            )
            # Hand the edited lyrics to the pipeline through a temp .lrc file so
            # the user's manual corrections are respected.
            temp = Path(config.data_dir) / "output" / f"{self.source.stem}-edited.lrc"
            temp.parent.mkdir(parents=True, exist_ok=True)
            temp.write_text(to_lrc(lyrics), encoding="utf-8")
            options.lyrics_file = str(temp)

            self.cancel_event = threading.Event()
            self._set_busy(True)
            self._log("Starting render…")
            worker = RenderWorker(self.source, options, self.cancel_event)
            worker.progress.connect(self._log)
            worker.succeeded.connect(self._render_done)
            worker.failed.connect(self._failed)
            worker.finished.connect(lambda: self._set_busy(False))
            self.worker = worker
            worker.start()

        def _render_done(self, result: object) -> None:
            data = result  # type: ignore[assignment]
            self.last_output = Path(data.render.output_path)
            self.open_output_button.setEnabled(True)
            self.separation_status.setText(
                f"{data.separation.method} · {data.separation.duration:.1f}s"
            )
            self._log(f"Done: {self.last_output}")
            for warning in data.warnings:
                self._log(f"Warning: {warning}")
            QMessageBox.information(self, APP_NAME, f"Karaoke video ready:\n{self.last_output}")

        def _failed(self, message: str) -> None:
            self._log(f"ERROR: {message}")
            QMessageBox.critical(self, APP_NAME, message)

        def _open_output(self) -> None:
            if not self.last_output:
                return
            folder = self.last_output.parent
            try:
                if os.name == "nt":
                    os.startfile(str(folder))  # type: ignore[attr-defined]
                elif sys.platform == "darwin":
                    subprocess.Popen(["open", str(folder)])
                else:
                    subprocess.Popen(["xdg-open", str(folder)])
            except Exception as exc:  # pragma: no cover - platform specific
                self._log(f"Could not open folder: {exc}")

    app = QApplication.instance() or QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    window = MainWindow()
    window.show()
    try:
        return app.exec()
    finally:
        # Tear the window down *before* Qt destroys the application object;
        # otherwise the widget tree outlives QApplication and Qt warns about
        # a "shared QObject deleted directly".
        window.close()
        window.deleteLater()
        app.processEvents()
