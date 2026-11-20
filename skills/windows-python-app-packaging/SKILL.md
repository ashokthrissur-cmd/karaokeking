---
name: windows-python-app-packaging
description: Builds a self-contained Windows desktop app from a Python/PySide6 project with no Python installed on the target PC, and diagnoses "installed but nothing happens" launch failures. Covers embeddable CPython bundles, python311._pth, DLL search order, MSVC runtime, NSIS installers cross-compiled from Linux, and shortcut/launcher pitfalls. Use when packaging Python for Windows, building an .exe installer, or when a bundled Windows app installs but will not open.
license: Apache-2.0
metadata:
  author: karaokeking
  version: "1.0"
---

# Packaging a Python app for Windows (self-contained)

## When to use this

- Shipping a Python GUI app to users who have no Python and no admin rights.
- Building a Windows `.exe` installer from a Linux CI box.
- Debugging **"the app installed but nothing happens when I click it."**

That last symptom is the most common and the least informative. Work the
diagnosis order below before changing any code.

---

## Diagnosis order for "installs but will not open"

Check these in order. Each one produces a *completely silent* failure, which is
why they are so hard to tell apart.

### 1. The shortcut is the problem, not the app

**Windows 11 24H2 disables Windows Script Host (VBScript) by default.**
A shortcut targeting `wscript.exe "App.vbs"` does *literally nothing* — no
window, no error, no flash. This is the single most common cause.

Never ship a `.vbs` or `.bat` as the primary launch path. Point shortcuts at
the interpreter directly:

```nsis
CreateShortcut "$DESKTOP\My App.lnk" \
  "$INSTDIR\pythonw.exe" "-m myapp gui" "$INSTDIR\app.ico" 0 SW_SHOWNORMAL "" "Tagline"
```

Verify: `grep -i wscript installer/*.nsi` must return nothing.

### 2. `pythonw.exe` swallows every error

`pythonw.exe` has no console, so `stdout`/`stderr` are `None`. Any traceback is
discarded and the process exits quietly. The window never appears and the user
sees nothing.

Fix it in the entry point, not in the launcher:

```python
# myapp/__main__.py
def _attach_log():
    if sys.stdout is not None and sys.stderr is not None:
        return None                      # real console, leave it alone
    path = Path(os.environ["LOCALAPPDATA"]) / "My App" / "logs" / "startup.log"
    path.parent.mkdir(parents=True, exist_ok=True)
    stream = open(path, "a", encoding="utf-8", buffering=1)
    sys.stdout = sys.stdout or stream
    sys.stderr = sys.stderr or stream
    return path

def _show_error(msg):
    if os.name == "nt":
        import ctypes
        ctypes.windll.user32.MessageBoxW(None, msg, "My App", 0x10)
```

`MessageBoxW` works even when Qt itself failed to import, so the user always
gets a readable error. Wrap the whole `main()` in `except BaseException`.

### 3. `python311._pth` is wrong

The embeddable distribution uses a `._pth` file that **replaces** normal
`sys.path` seeding. If it is wrong, `import` fails instantly.

```
python311.zip
.
Lib\site-packages
import site
```

The trailing `import site` is what enables `site-packages` processing. Without
it, third-party packages are invisible. `..` is only needed if the package sits
one level above the interpreter.

### 4. DLL search order

Windows searches, in order: the **module's own directory**, then the **process
directory**, then `System32`. A DLL in an unrelated subfolder is invisible.

Consequence: put `msvcp140.dll` and friends in the **app root** (next to
`python.exe`), not in `vendor/`. PySide6 additionally ships its own
`msvcp140.dll` inside `Lib/site-packages/PySide6/` and calls
`os.add_dll_directory()` on that folder in `PySide6/__init__.py`, so Qt
usually resolves it regardless — do not assume a missing MSVC runtime is the
bug without checking that folder first.

### 5. Missing Qt platform plugin

`QApplication` aborts with no dialog if `plugins/platforms/qwindows.dll` is
absent. Confirm it exists:

```bash
ls Lib/site-packages/PySide6/plugins/platforms/qwindows.dll
```

---

## Building the bundle

### Download the embeddable interpreter

```python
PYTHON_VERSION = "3.11.9"
PYTHON_URL = (
    f"https://www.python.org/ftp/python/{PYTHON_VERSION}/"
    f"python-{PYTHON_VERSION}-embed-amd64.zip"
)
```

Unzip into `dist/`. You get `python.exe`, `pythonw.exe`, `python311.dll`,
`python311.zip` (stdlib as `.pyc`), and `python311._pth`.

### Cross-install Windows wheels from Linux

You cannot `pip install` win_amd64 wheels on Linux normally, but you can
download and unpack them:

```bash
pip download PySide6-Essentials==6.7.3 \
  --no-deps --only-binary=:all: \
  --platform win_amd64 --python-version 311 \
  --implementation cp --abi cp311 \
  -d wheels/
```

Then unzip each wheel's contents into `dist/Lib/site-packages/`. Wheel
`*.data/` subdirectories need to be flattened to the right place.

**Verify every native module's imports before shipping.** This catches a
missing DLL without a Windows machine:

```bash
objdump -p Lib/site-packages/PySide6/Qt6Widgets.pyd | grep "DLL Name"
```

Every non-system name must exist in a directory Windows actually searches.

### MSVC runtime

The `msvc-runtime` PyPI wheel carries the official Microsoft redistributable
DLLs. They are nested under `<name>.data/data/`, so filter on `.data/data/`
(not `/data/data/`):

```python
if ".data/data/" not in member.replace("\\", "/"):
    continue
```

Copy them to the **app root**, but skip any file the interpreter already ships
(`vcruntime140.dll`, `vcruntime140_1.dll`) — CPython is built against exactly
those.

### FFmpeg and native CLI tools

Grab the gyan.dev essentials build for `ffmpeg.exe` / `ffprobe.exe`. Keep them
in `dist/ffmpeg/` and resolve them at runtime by probing several relative
locations, because the app may be run from the bundle root or from a
`site-packages` install.

---

## NSIS installer, cross-compiled from Linux

```bash
apt-get install -y nsis
```

`makensis` produces a genuine Windows PE installer on Linux. Verify with:

```bash
file dist/Setup.exe            # "PE32 executable (GUI) ... Nullsoft Installer"
7z l dist/Setup.exe | tail -3  # file count and uncompressed size
```

### Working `.nsi` skeleton

```nsis
Unicode true
SetCompressor /SOLID lzma
SetCompressorDictSize 32

!define APP_NAME    "My App"
!define APP_VERSION "1.2.0"
!define APP_EXE     "pythonw.exe"
!define APP_ARGS    "-m myapp gui"
!define SOURCE_DIR  "..\..\build\portable\app"

Name "${APP_NAME} ${APP_VERSION}"
OutFile "..\dist\My-App-Setup-${APP_VERSION}.exe"
InstallDir "$LOCALAPPDATA\Programs\${APP_NAME}"
RequestExecutionLevel user          ; per-user: no admin prompt
VIProductVersion "1.2.0.0"

Section "!${APP_NAME} (required)" SEC_MAIN
  SectionIn RO
  SetOutPath "$INSTDIR"
  File /r "${SOURCE_DIR}\*.*"
  CreateShortcut "$INSTDIR\Launch.lnk" "$INSTDIR\${APP_EXE}" "${APP_ARGS}" \
    "$INSTDIR\app.ico" 0 SW_SHOWNORMAL "" "Tagline"
  WriteUninstaller "$INSTDIR\Uninstall.exe"
  ; ... HKCU Add/Remove Programs entry ...
SectionEnd
```

### NSIS pitfalls that cost real time

| Symptom | Cause | Fix |
|---|---|---|
| `Exec expects 1 parameters, got 3` | `MUI_FINISHPAGE_RUN` + `_RUN_PARAMETERS` conflict | Launch a `.lnk` instead: `!define MUI_FINISHPAGE_RUN "$INSTDIR\Launch.lnk"` |
| `Bus error` from makensis | Disk full during LZMA solid compression | Free space; the temp file grows to ~uncompressed size |
| Command times out | Solid LZMA on 450 MB takes 5+ minutes | Run non-blocking and poll `pgrep makensis` |
| Shortcut does nothing | `wscript.exe` launcher | Target `pythonw.exe` directly |
| Uninstall leaves files | Glob deletes miss `*.lnk` | Add `Delete "$INSTDIR\*.lnk"` |

### Always verify the built installer, not just the source tree

The bundle directory and the installer can drift apart — a stale app copy
inside `dist/` will ship old code. Re-sync before every build and then extract
from the finished `.exe` to confirm:

```bash
rm -rf dist/app/myapp && cp -r myapp dist/app/myapp
makensis installer/App.nsi
7z x -y -o/tmp/chk dist/Setup.exe "myapp/__init__.py"
grep __version__ /tmp/chk/myapp/__init__.py
```

---

## Ship a diagnostic entry point

Always include a `Troubleshoot.bat` that runs three visible checks and pauses:

```bat
@echo off
cd /d "%~dp0"
"%~dp0python.exe" -c "import sys; print('Python', sys.version)"
"%~dp0python.exe" -c "import PySide6; from PySide6 import QtWidgets; print('Qt OK')"
"%~dp0python.exe" -c "import myapp; print('app', myapp.__version__, 'OK')"
pause
```

This converts an invisible failure into a copy-pasteable error message.

---

## Regression tests worth writing

These are cheap and catch the exact bugs above:

```python
def test_installer_never_uses_windows_script_host():
    script = (ROOT / "installer" / "App.nsi").read_text()
    assert "wscript" not in script.lower()
    assert "pythonw.exe" in script.lower()

def test_entry_point_reports_fatal_errors_visibly():
    source = (ROOT / "myapp" / "__main__.py").read_text()
    assert "MessageBoxW" in source
```

See `references/dll-audit.md` for a script that checks every native module's
import table against the bundle.
