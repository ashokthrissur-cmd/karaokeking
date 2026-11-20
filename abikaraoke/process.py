"""Supervised external-process execution.

Fixes the original application's two worst process bugs:
  * stdout and stderr were read sequentially, so a full pipe could deadlock;
  * child processes were never cancellable or time-bounded.

This module drains both pipes on dedicated threads, enforces a timeout,
propagates cancellation, and kills the whole process tree.
"""

from __future__ import annotations

import os
import signal
import subprocess
import sys
import threading
import time
from dataclasses import dataclass
from typing import Callable, Dict, List, Optional, Sequence

IS_WINDOWS = os.name == "nt"


class ProcessError(RuntimeError):
    """Raised when a required external tool cannot be started or fails."""


@dataclass
class ProcessResult:
    argv: List[str]
    returncode: int
    stdout: str
    stderr: str
    timed_out: bool = False
    cancelled: bool = False
    duration: float = 0.0
    truncated: bool = False

    @property
    def ok(self) -> bool:
        return self.returncode == 0 and not self.timed_out and not self.cancelled

    def tail(self, limit: int = 4000) -> str:
        text = (self.stderr or self.stdout or "").strip()
        return text[-limit:]


class _BoundedBuffer:
    """Thread-safe rolling text buffer with a hard character cap."""

    def __init__(self, limit: int) -> None:
        self._limit = limit
        self._chunks: List[str] = []
        self._size = 0
        self._lock = threading.Lock()
        self.truncated = False

    def append(self, text: str) -> None:
        if not text:
            return
        with self._lock:
            self._chunks.append(text)
            self._size += len(text)
            while self._size > self._limit and len(self._chunks) > 1:
                removed = self._chunks.pop(0)
                self._size -= len(removed)
                self.truncated = True

    def value(self) -> str:
        with self._lock:
            return "".join(self._chunks)


def _kill_tree(process: subprocess.Popen) -> None:
    if process.poll() is not None:
        return
    try:
        if IS_WINDOWS:
            subprocess.run(
                ["taskkill", "/F", "/T", "/PID", str(process.pid)],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=15,
                check=False,
            )
        else:
            try:
                os.killpg(os.getpgid(process.pid), signal.SIGKILL)
            except (ProcessLookupError, PermissionError):
                process.kill()
    except Exception:
        try:
            process.kill()
        except Exception:
            pass


def _reader(pipe, buffer: _BoundedBuffer) -> None:
    try:
        while True:
            chunk = pipe.read(4096)
            if not chunk:
                break
            if isinstance(chunk, bytes):
                chunk = chunk.decode("utf-8", "replace")
            buffer.append(chunk)
    except (ValueError, OSError):
        pass
    finally:
        try:
            pipe.close()
        except Exception:
            pass


def run(
    argv: Sequence[str],
    *,
    timeout: Optional[float] = None,
    cwd: Optional[str] = None,
    env: Optional[Dict[str, str]] = None,
    cancel: Optional[threading.Event] = None,
    on_heartbeat: Optional[Callable[[float], None]] = None,
    heartbeat_interval: float = 10.0,
    output_limit: int = 2_000_000,
    stdin_text: Optional[str] = None,
) -> ProcessResult:
    """Run ``argv`` to completion, concurrently draining both pipes.

    ``cancel`` is a :class:`threading.Event`; when set the child process tree is
    killed and ``cancelled=True`` is returned.  A ``timeout`` (seconds) does the
    same with ``timed_out=True``.  A missing executable raises
    :class:`ProcessError` with an actionable message.
    """

    argv = [str(a) for a in argv]
    if not argv:
        raise ValueError("argv must not be empty")

    merged_env = os.environ.copy()
    if env:
        merged_env.update(env)

    creationflags = 0
    if IS_WINDOWS:
        creationflags = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)

    started = time.monotonic()
    try:
        process = subprocess.Popen(
            argv,
            cwd=cwd,
            env=merged_env,
            stdin=subprocess.PIPE if stdin_text is not None else subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
            creationflags=creationflags,
            start_new_session=not IS_WINDOWS,
        )
    except FileNotFoundError as exc:
        raise ProcessError(
            f"Executable not found: {argv[0]}. Install it or set its path in Settings."
        ) from exc
    except OSError as exc:
        raise ProcessError(f"Could not start {argv[0]}: {exc}") from exc

    out_buf = _BoundedBuffer(output_limit)
    err_buf = _BoundedBuffer(output_limit)
    out_thread = threading.Thread(target=_reader, args=(process.stdout, out_buf), daemon=True)
    err_thread = threading.Thread(target=_reader, args=(process.stderr, err_buf), daemon=True)
    out_thread.start()
    err_thread.start()

    if stdin_text is not None and process.stdin is not None:
        try:
            process.stdin.write(stdin_text)
            process.stdin.close()
        except Exception:
            pass

    timed_out = False
    cancelled = False
    next_heartbeat = started + heartbeat_interval

    try:
        while process.poll() is None:
            now = time.monotonic()
            if cancel is not None and cancel.is_set():
                cancelled = True
                _kill_tree(process)
                break
            if timeout is not None and (now - started) >= timeout:
                timed_out = True
                _kill_tree(process)
                break
            if on_heartbeat is not None and now >= next_heartbeat:
                next_heartbeat = now + heartbeat_interval
                try:
                    on_heartbeat(now - started)
                except Exception:
                    pass
            time.sleep(0.05)
    finally:
        try:
            process.wait(timeout=15)
        except subprocess.TimeoutExpired:
            _kill_tree(process)
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                pass

    out_thread.join(timeout=10)
    err_thread.join(timeout=10)

    return ProcessResult(
        argv=list(argv),
        returncode=process.returncode if process.returncode is not None else -1,
        stdout=out_buf.value(),
        stderr=err_buf.value(),
        timed_out=timed_out,
        cancelled=cancelled,
        duration=time.monotonic() - started,
        truncated=out_buf.truncated or err_buf.truncated,
    )


def run_checked(argv: Sequence[str], **kwargs) -> ProcessResult:
    """Like :func:`run` but raises :class:`ProcessError` on a non-zero exit."""

    result = run(argv, **kwargs)
    if not result.ok:
        reason = "cancelled" if result.cancelled else "timed out" if result.timed_out else f"exit {result.returncode}"
        raise ProcessError(f"{argv[0]} failed ({reason}): {result.tail()}")
    return result
