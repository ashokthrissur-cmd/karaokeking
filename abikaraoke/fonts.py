"""Pick a font that can actually draw the lyrics.

The original app hard-coded a Latin font, so Malayalam, Tamil and Devanagari
lyrics rendered as empty boxes.  This module detects which scripts appear in
the lyrics and chooses an installed font that covers them, falling back to a
sensible name when fontconfig is unavailable.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path
from typing import Dict, List, Optional, Tuple

# Fonts shipped with the app.  libass is pointed at this folder, so these work
# even on a machine with no Indic fonts installed at all.
_BUNDLED: Dict[str, Tuple[str, str]] = {
    "malayalam": ("NotoSansMalayalam-Regular.ttf", "Noto Sans Malayalam"),
    "devanagari": ("NotoSansDevanagari-Regular.ttf", "Noto Sans Devanagari"),
    "tamil": ("NotoSansTamil-Regular.ttf", "Noto Sans Tamil"),
}

# Script name -> (fontconfig language tag, preferred font families)
_SCRIPTS: Dict[str, Tuple[str, List[str]]] = {
    "malayalam": ("ml", ["Noto Sans Malayalam", "Manjari", "AnjaliOldLipi", "Rachana"]),
    "tamil": ("ta", ["Noto Sans Tamil", "Lohit Tamil", "Tamil Sangam MN"]),
    "telugu": ("te", ["Noto Sans Telugu", "Lohit Telugu"]),
    "kannada": ("kn", ["Noto Sans Kannada", "Lohit Kannada"]),
    "bengali": ("bn", ["Noto Sans Bengali", "Lohit Bengali"]),
    "gujarati": ("gu", ["Noto Sans Gujarati", "Lohit Gujarati"]),
    "gurmukhi": ("pa", ["Noto Sans Gurmukhi", "Lohit Punjabi"]),
    "devanagari": ("hi", ["Noto Sans Devanagari", "Mangal", "Lohit Devanagari"]),
    "arabic": ("ar", ["Noto Sans Arabic", "Amiri", "Segoe UI"]),
    "hebrew": ("he", ["Noto Sans Hebrew", "David CLM"]),
    "thai": ("th", ["Noto Sans Thai", "Loma"]),
    "japanese": ("ja", ["Noto Sans JP", "Yu Gothic", "Meiryo"]),
    "korean": ("ko", ["Noto Sans KR", "Malgun Gothic"]),
    "chinese": ("zh", ["Noto Sans SC", "Microsoft YaHei", "SimHei"]),
}


def bundled_fonts_dir() -> Optional[Path]:
    """Folder holding the fonts shipped with the app, if present."""

    directory = Path(__file__).resolve().parent / "assets" / "fonts"
    return directory if directory.is_dir() else None


def bundled_font(script: str) -> Optional[Tuple[Path, str]]:
    """Return ``(path, family_name)`` for a bundled font covering ``script``."""

    entry = _BUNDLED.get(script)
    if not entry:
        return None
    filename, family = entry
    directory = bundled_fonts_dir()
    if not directory:
        return None
    path = directory / filename
    return (path, family) if path.is_file() else None


_RANGES: Dict[str, List[Tuple[int, int]]] = {
    "malayalam": [(0x0D00, 0x0D7F)],
    "tamil": [(0x0B80, 0x0BFF)],
    "telugu": [(0x0C00, 0x0C7F)],
    "kannada": [(0x0C80, 0x0CFF)],
    "bengali": [(0x0980, 0x09FF)],
    "gujarati": [(0x0A80, 0x0AFF)],
    "gurmukhi": [(0x0A00, 0x0A7F)],
    "devanagari": [(0x0900, 0x097F)],
    "arabic": [(0x0600, 0x06FF)],
    "hebrew": [(0x0590, 0x05FF)],
    "thai": [(0x0E00, 0x0E7F)],
    "japanese": [(0x3040, 0x30FF), (0x4E00, 0x9FFF)],
    "korean": [(0xAC00, 0xD7AF)],
    "chinese": [(0x4E00, 0x9FFF)],
}


def detect_scripts(text: str) -> List[str]:
    """Return the non-Latin scripts present in ``text``, most frequent first."""

    counts: Dict[str, int] = {}
    for char in text:
        code = ord(char)
        for script, ranges in _RANGES.items():
            if any(start <= code <= end for start, end in ranges):
                counts[script] = counts.get(script, 0) + 1
                break
    return [name for name, _ in sorted(counts.items(), key=lambda item: -item[1])]


def _installed_families() -> Optional[set]:
    if not shutil.which("fc-list"):
        return None
    try:
        output = subprocess.run(
            ["fc-list", ":", "family"], capture_output=True, text=True, timeout=10
        )
    except Exception:
        return None
    if output.returncode != 0:
        return None
    families = set()
    for line in output.stdout.splitlines():
        for part in line.split(","):
            name = part.strip()
            if name:
                families.add(name.casefold())
    return families


def _has_language(tag: str) -> Optional[bool]:
    if not shutil.which("fc-list"):
        return None
    try:
        output = subprocess.run(
            ["fc-list", f":lang={tag}"], capture_output=True, text=True, timeout=10
        )
    except Exception:
        return None
    if output.returncode != 0:
        return None
    return bool(output.stdout.strip())


def choose_font(text: str, *, default: str = "Arial") -> Tuple[str, List[str]]:
    """Pick a font family for ``text``.

    Returns ``(font_name, warnings)``.  Warnings explain when a script has no
    installed font, which is exactly the case that produced boxes in the
    original app.
    """

    scripts = detect_scripts(text)
    if not scripts:
        return default, []

    warnings: List[str] = []

    for script in scripts:
        # A bundled font always wins: it is guaranteed to be there and to have
        # complete coverage, unlike whatever the system happens to ship.
        shipped = bundled_font(script)
        if shipped:
            return shipped[1], warnings

        tag, preferred = _SCRIPTS.get(script, ("", []))
        if not preferred:
            continue
        installed = _installed_families()
        if installed is not None:
            for family in preferred:
                if family.casefold() in installed:
                    return family, warnings
        else:
            return preferred[0], warnings

        covers = _has_language(tag) if tag else None
        if covers is False:
            warnings.append(
                f"No installed font covers {script} text. Install "
                f"'{preferred[0]}' or the lyrics will render as boxes."
            )
        return preferred[0], warnings

    return default, warnings
