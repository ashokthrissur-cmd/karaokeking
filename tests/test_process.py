"""Tests for the supervised process runner.

These cover the exact failure mode that made the original app hang forever:
reading stdout to EOF before touching stderr deadlocks as soon as the child
fills the other pipe.  The runner must drain both concurrently.
"""

from __future__ import annotations

import sys
import threading
import time

import pytest

from abikaraoke.process import ProcessError, run, run_checked


def test_captures_stdout_and_exit_code():
    result = run([sys.executable, "-c", "print('hello')"], timeout=30)
    assert result.ok
    assert result.returncode == 0
    assert "hello" in result.stdout
    assert result.duration > 0


def test_captures_stderr():
    result = run(
        [sys.executable, "-c", "import sys; sys.stderr.write('bad thing')"], timeout=30
    )
    assert result.ok
    assert "bad thing" in result.stderr


def test_does_not_deadlock_on_large_both_streams():
    """Write ~400 KB to each pipe: sequential draining would hang here."""

    script = (
        "import sys\n"
        "for _ in range(4000):\n"
        "    sys.stdout.write('o'*100 + '\\n')\n"
        "    sys.stderr.write('e'*100 + '\\n')\n"
        "sys.stdout.flush(); sys.stderr.flush()\n"
    )
    started = time.time()
    result = run([sys.executable, "-c", script], timeout=60)
    assert result.ok
    assert len(result.stdout) >= 400_000
    assert len(result.stderr) >= 400_000
    assert time.time() - started < 60


def test_output_is_bounded():
    script = "import sys; sys.stdout.write('x'*500000)"
    result = run([sys.executable, "-c", script], timeout=30, output_limit=10_000)
    assert result.ok
    assert len(result.stdout) <= 11_000
    assert result.truncated


def test_timeout_kills_process():
    started = time.time()
    result = run(
        [sys.executable, "-c", "import time; time.sleep(30)"], timeout=1.5
    )
    assert result.timed_out
    assert not result.ok
    assert time.time() - started < 15


def test_cancel_event_stops_process():
    cancel = threading.Event()
    threading.Timer(0.5, cancel.set).start()
    started = time.time()
    result = run(
        [sys.executable, "-c", "import time; time.sleep(30)"],
        timeout=30,
        cancel=cancel,
    )
    assert result.cancelled
    assert not result.ok
    assert time.time() - started < 15


def test_stdin_text_is_delivered():
    result = run(
        [sys.executable, "-c", "import sys; print(sys.stdin.read().upper())"],
        timeout=30,
        stdin_text="abc",
    )
    assert result.ok
    assert "ABC" in result.stdout


def test_missing_executable_raises():
    with pytest.raises(ProcessError):
        run(["definitely-not-a-real-binary-xyz"], timeout=5)


def test_run_checked_raises_on_failure():
    with pytest.raises(ProcessError) as excinfo:
        run_checked([sys.executable, "-c", "import sys; sys.exit(3)"], timeout=30)
    assert "3" in str(excinfo.value)
