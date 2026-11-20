# Auditing DLL dependencies without a Windows machine

Windows will fail to start a process if a native module's import table names a
DLL it cannot find. On Linux you can still prove every dependency is
satisfiable by reading the PE import tables and simulating the loader's search
order.

## 1. List the imports of every native module

```bash
find dist -name "*.pyd" -o -name "*.dll" | while read -r f; do
  echo "== $f"
  objdump -p "$f" 2>/dev/null | grep "DLL Name" | awk '{print $3}'
done
```

`objdump` from binutils understands PE files. `llvm-objdump` works too.

## 2. Decide which names are system-provided

These live in `System32` on every supported Windows and never need bundling:

```
kernel32.dll user32.dll gdi32.dll advapi32.dll shell32.dll ole32.dll
oleaut32.dll comdlg32.dll comctl32.dll ws2_32.dll winmm.dll version.dll
shlwapi.dll setupapi.dll imm32.dll uxtheme.dll dwmapi.dll
d3d9.dll d3d11.dll d3d12.dll dxgi.dll opengl32.dll glu32.dll
msi.dll cabinet.dll winspool.drv winhttp.dll wininet.dll crypt32.dll
bcrypt.dll ncrypt.dll secur32.dll iphlpapi.dll netapi32.dll
api-ms-win-*.dll ext-ms-*.dll
```

Everything else must be present in a directory the loader searches.

## 3. Simulate the loader's search order

For a module at `M`, Windows looks in:

1. `M`'s own directory
2. the process directory (the folder holding `python.exe`)
3. `System32`
4. any directory added with `os.add_dll_directory()`

PySide6 calls `os.add_dll_directory()` on `Lib/site-packages/PySide6/` and on
`Lib/site-packages/shiboken6/` from its `__init__.py`, so both of those count.

```python
def searchable_dirs(module: Path, bundle: Path) -> list[Path]:
    dirs = [module.parent, bundle,
            bundle / "Lib" / "site-packages" / "PySide6",
            bundle / "Lib" / "site-packages" / "shiboken6"]
    return [d for d in dirs if d.is_dir()]
```

## 4. The trap that produces false passes

Do **not** glob the whole tree for a DLL name. A `msvcp140.dll` sitting inside
`shiboken6/` will satisfy a naive check while the actual module still cannot
load it. Restrict the search to `searchable_dirs(module)`.

This exact mistake hid a real problem: a test passed after the root copy of
`msvcp140.dll` was removed, because a stray copy in a subfolder was found.

## 5. A compact checker

```python
import subprocess
from pathlib import Path

SYSTEM = {"kernel32.dll", "user32.dll", "gdi32.dll", "advapi32.dll"}

def imports(path: Path) -> set[str]:
    out = subprocess.run(["objdump", "-p", str(path)],
                         capture_output=True, text=True).stdout
    return {line.split()[-1].lower()
            for line in out.splitlines() if "DLL Name" in line}

def check(bundle: Path) -> list[str]:
    problems = []
    for module in list(bundle.rglob("*.pyd")) + list(bundle.rglob("*.dll")):
        dirs = searchable_dirs(module, bundle)
        for name in imports(module):
            if name in SYSTEM or name.startswith(("api-ms-win-", "ext-ms-")):
                continue
            if not any((d / name).is_file() for d in dirs):
                problems.append(f"{module.relative_to(bundle)} needs {name}")
    return problems
```

Run it in CI. An empty list means the bundle can start.
