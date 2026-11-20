"""Guards against shipping a bundle that cannot start on a clean Windows PC.

The first installer we shipped omitted ``MSVCP140.dll``.  ``Qt6Core.dll`` links
against it, so on any machine without the Visual C++ redistributable Qt failed
to load, Python exited immediately, and because the launcher uses
``pythonw.exe`` the user saw nothing at all -- the app simply "did not open".

These tests read the PE import tables of the bundled Qt libraries and assert
that every non-system dependency is actually present next to them.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
# ``build_portable.py`` writes here.  Override with ABI_BUNDLE_DIR to point at
# a bundle assembled somewhere else.
BUNDLE = Path(os.environ.get("ABI_BUNDLE_DIR", ROOT / "build" / "portable" / "app"))

# DLLs Windows itself always provides.
SYSTEM_DLLS = {
    "kernel32.dll", "user32.dll", "gdi32.dll", "advapi32.dll", "shell32.dll",
    "ole32.dll", "oleaut32.dll", "ws2_32.dll", "version.dll", "winmm.dll",
    "mpr.dll", "netapi32.dll", "userenv.dll", "authz.dll", "imm32.dll",
    "comdlg32.dll", "comctl32.dll", "uxtheme.dll", "dwmapi.dll", "d3d11.dll",
    "d3d12.dll", "d3d9.dll", "dxgi.dll", "opengl32.dll", "glu32.dll",
    "crypt32.dll", "bcrypt.dll", "secur32.dll", "iphlpapi.dll", "psapi.dll",
    "shlwapi.dll", "rpcrt4.dll", "setupapi.dll", "wtsapi32.dll", "dnsapi.dll",
    "winhttp.dll", "wininet.dll", "urlmon.dll", "msimg32.dll", "gdiplus.dll",
    "dbghelp.dll", "powrprof.dll", "ntdll.dll", "msvcrt.dll", "ucrtbase.dll",
    "dwrite.dll", "dcomp.dll", "propsys.dll", "wldap32.dll", "cfgmgr32.dll",
    "pdh.dll", "avrt.dll", "mfplat.dll", "shcore.dll", "d2d1.dll",
    "d3dcompiler_47.dll", "msi.dll", "cabinet.dll", "winspool.drv",
    "imagehlp.dll", "odbc32.dll", "avicap32.dll",
}

# The Qt libraries the GUI cannot start without.
CRITICAL = [
    "Lib/site-packages/PySide6/Qt6Core.dll",
    "Lib/site-packages/PySide6/Qt6Gui.dll",
    "Lib/site-packages/PySide6/Qt6Widgets.dll",
    "Lib/site-packages/PySide6/QtWidgets.pyd",
    "Lib/site-packages/shiboken6/Shiboken.pyd",
]


def _imports(path: Path) -> set:
    objdump = shutil.which("objdump")
    if not objdump:
        pytest.skip("objdump is required to inspect PE imports")
    out = subprocess.run(
        [objdump, "-p", str(path)], capture_output=True, text=True, timeout=60
    ).stdout
    return {m.group(1).lower() for m in re.finditer(r"DLL Name:\s*(\S+)", out)}


def _bundle_files() -> set:
    return {
        p.name.lower()
        for p in BUNDLE.rglob("*")
        if p.is_file() and p.suffix.lower() in (".dll", ".pyd", ".exe")
    }


def _searchable_dirs(module: Path) -> list:
    """Directories Windows actually searches when loading *module*.

    The loader looks in the module's own folder first, then the process
    directory (the app root), then System32.  A DLL sitting in some unrelated
    sub-folder -- ``shiboken6/``, say -- is invisible to it.
    """

    dirs = []
    for candidate in (
        module.parent,
        BUNDLE,
        BUNDLE / "Lib" / "site-packages" / "PySide6",
        # PySide6/__init__.py calls os.add_dll_directory() on this folder, so
        # shiboken6.abi3.dll and its runtime are genuinely reachable.
        BUNDLE / "Lib" / "site-packages" / "shiboken6",
    ):
        if candidate.is_dir() and candidate not in dirs:
            dirs.append(candidate)
    return dirs


def _available_for(module: Path) -> set:
    names = set()
    for folder in _searchable_dirs(module):
        for p in folder.iterdir():
            if p.is_file():
                names.add(p.name.lower())
    return names


needs_bundle = pytest.mark.skipif(
    not BUNDLE.is_dir(), reason="portable bundle has not been built"
)


@needs_bundle
@pytest.mark.parametrize("relative", CRITICAL)
def test_critical_library_dependencies_are_bundled(relative):
    path = BUNDLE / relative
    if not path.is_file():
        pytest.skip(f"{relative} not present in this bundle")

    available = _available_for(path)
    unresolved = [
        dep
        for dep in _imports(path)
        if dep not in available
        and dep not in SYSTEM_DLLS
        and not dep.startswith(("api-ms-win", "ext-ms-win"))
    ]

    assert not unresolved, (
        f"{relative} needs {unresolved}, which the bundle does not ship. "
        "The app would exit before drawing a window."
    )


@needs_bundle
def test_msvc_runtime_is_shipped():
    """Qt is C++; the embedded CPython only ships VCRUNTIME140."""

    # Must be in the app root: that is the process directory, so every Qt
    # library resolves it without depending on PySide6's DLL-directory setup.
    for required in ("msvcp140.dll", "msvcp140_1.dll", "vcruntime140.dll"):
        assert (BUNDLE / required).is_file(), f"{required} missing from the bundle root"


@needs_bundle
def test_launchers_and_diagnostics_exist():
    for name in (
        "ABI Karaoke.vbs",
        "ABI Karaoke.bat",
        "Doctor.bat",
        "Setup AI.bat",
        "Troubleshoot.bat",
        "Launch.bat",
        "python311._pth",
    ):
        assert (BUNDLE / name).is_file(), f"{name} missing from the bundle"


@needs_bundle
def test_bundled_fonts_are_present():
    fonts = BUNDLE / "abikaraoke" / "assets" / "fonts"
    names = {p.name for p in fonts.glob("*.ttf")}
    assert "NotoSansDevanagari-Regular.ttf" in names
    assert "NotoSansMalayalam-Regular.ttf" in names


@needs_bundle
def test_whisper_and_ffmpeg_are_bundled():
    assert (BUNDLE / "ffmpeg" / "ffmpeg.exe").is_file()
    assert (BUNDLE / "ffmpeg" / "ffprobe.exe").is_file()
    assert (BUNDLE / "whisper" / "whisper-cli.exe").is_file()


def test_installer_never_uses_windows_script_host():
    """Windows 11 24H2 disables VBScript by default.

    A shortcut that runs ``wscript.exe "ABI Karaoke.vbs"`` does nothing at all
    when clicked, which is indistinguishable from a broken install.  The
    installer must launch pythonw.exe directly instead.
    """
    script = (ROOT / "installer" / "ABIKaraoke.nsi").read_text(encoding="utf-8")
    lowered = script.lower()
    assert "wscript" not in lowered
    assert "pythonw.exe" in lowered
    assert "-m abikaraoke gui" in script


def test_entry_point_reports_fatal_errors_visibly():
    """pythonw.exe has no console, so a crash must show a native dialog."""
    source = (ROOT / "abikaraoke" / "__main__.py").read_text(encoding="utf-8")
    assert "MessageBoxW" in source
    assert "_attach_log" in source
