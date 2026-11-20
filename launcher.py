"""Frozen-executable entry point.

Running the packaged .exe with no arguments opens the desktop UI; passing
arguments behaves exactly like the ``abikaraoke`` command.
"""

from __future__ import annotations

import sys

from abikaraoke.cli import main

if __name__ == "__main__":
    if len(sys.argv) == 1:
        sys.argv.append("gui")
    raise SystemExit(main())
