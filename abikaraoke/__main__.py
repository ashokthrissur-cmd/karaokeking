"""Entry point used by ``python -m abikaraoke`` and the Windows shortcuts.

The Windows build launches the app with ``pythonw.exe``, which has no console
and therefore silently discards anything written to stdout/stderr.  A crash
then looks exactly like "nothing happened".  This module makes sure that never
happens again:

* when there is no console, stdout/stderr are redirected to a log file;
* any unhandled exception is written to that log *and* shown in a native
  Win32 message box, which works even if Qt itself failed to load.
"""

from __future__ import annotations

import os
import sys
import traceback
from pathlib import Path


def _log_folder() -> Path:
    """Return a writable folder for logs, preferring %LOCALAPPDATA%."""
    candidates = [
        os.environ.get("LOCALAPPDATA"),
        os.environ.get("APPDATA"),
        os.environ.get("TEMP"),
        str(Path.home()),
    ]
    for base in candidates:
        if not base:
            continue
        folder = Path(base) / "ABI Karaoke" / "logs"
        try:
            folder.mkdir(parents=True, exist_ok=True)
            probe = folder / ".write-test"
            probe.write_text("ok", encoding="utf-8")
            probe.unlink()
            return folder
        except OSError:
            continue
    return Path(os.environ.get("TEMP", "."))


def _attach_log() -> Path | None:
    """Point stdout/stderr at a log file when running without a console."""
    if sys.stderr is not None and sys.stdout is not None:
        return None
    try:
        path = _log_folder() / "startup.log"
        stream = open(path, "a", encoding="utf-8", buffering=1)
    except OSError:
        return None
    if sys.stdout is None:
        sys.stdout = stream
    if sys.stderr is None:
        sys.stderr = stream
    return path


def _show_error(message: str) -> None:
    """Show a native dialog even when Qt is broken or unavailable."""
    if os.name == "nt":
        try:
            import ctypes

            ctypes.windll.user32.MessageBoxW(None, message, "ABI Karaoke", 0x10)
            return
        except Exception:  # pragma: no cover - best effort only
            pass
    try:
        print(message, file=sys.stderr)
    except Exception:
        pass


def main() -> int:
    log_path = _attach_log()
    try:
        from .cli import main as cli_main

        return cli_main()
    except SystemExit:
        raise
    except BaseException:
        detail = traceback.format_exc()
        if log_path is not None:
            try:
                with open(log_path, "a", encoding="utf-8") as handle:
                    handle.write(detail + "\n")
            except OSError:
                pass
        last_line = detail.strip().splitlines()[-1] if detail.strip() else "Unknown error"
        message = f"ABI Karaoke could not start.\n\n{last_line}"
        if log_path is not None:
            message += f"\n\nFull details were saved to:\n{log_path}"
        _show_error(message)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
