# ABI Karaoke

A rebuild of the ABI Karaoke desktop app that fixes the three failures users hit
constantly — **vocal removal**, **fetch lyrics**, and **AI sync** — and replaces
the silent-fallback behaviour that made them so hard to diagnose.

The engine is pure Python 3.9+ (standard library only), FFmpeg for media, an
optional PySide6 desktop UI, and optional Demucs / faster-whisper for the
best-quality path. Every stage writes a per-job manifest with SHA-256
provenance, validates its own output, and reports *why* something failed.

---

## What was broken, and why

| Symptom | Real cause in the old build | What this build does instead |
|---|---|---|
| **Vocal removal not working** | It probed generic `python` / `python3` / `py` and could launch an interpreter without Demucs. It then searched a **shared** work tree for the newest `no_vocals.wav`, so it often picked another song's stem. Output was never validated. | Verifies `import demucs` in the chosen interpreter, writes into a **per-job** `demucs/` directory, locates the exact `<model>/<track>/no_vocals.wav`, probes duration, and falls back to a documented center-cancel separator with a clear warning. |
| **Fetch lyrics not working** | Any HTTP error, 404, timeout, or empty payload became a silent no-op. The button appeared dead. | Typed errors (`LyricsNotFound`, `LyricsError`) with actionable text, retries with backoff, disk cache, LRCLIB `/get` then `/search`, and scoring that prefers synced lyrics over plain text. |
| **AI sync not working** | It only supported whisper.cpp and hard-failed with *"Please locate whisper-cli.exe first"*. Token timings were treated as word timings. Interpolated timings were labelled "exact". | Auto-selects faster-whisper or whisper.cpp, merges BPE sub-word tokens into words, runs a monotonic global alignment (Needleman–Wunsch style) with fuzzy matching, marks interpolated words `synthetic=True`, and reports a match ratio plus low-confidence lines. |
| **App hangs / freezes** | stdout was drained to EOF before stderr; a child that filled the other pipe deadlocked. Subprocesses were not cancellable. | A supervised runner drains both pipes on separate threads, enforces a timeout, supports cancellation, bounds memory, and kills the entire process tree. |
| **Wrong or corrupt output** | No post-render checks. | Probes streams, checks resolution and duration tolerance, runs a full decode test, and raises instead of shipping a broken MP4. |

The full audit that motivated these changes is in
[`docs/AUDIT.md`](docs/AUDIT.md).

---

## Architecture

```
abikaraoke/
  process.py        supervised subprocess runner (concurrent drain, timeout, cancel, kill-tree)
  config.py         explicit tool discovery + doctor() report
  workspace.py      per-job directory, manifest.json, source SHA-256, cleanup
  media.py          ffprobe / extract / decode test / ASS path escaping
  separation.py     Demucs + center-cancel + mid/vocal extraction + validation
  lyrics.py         LRCLIB client (retries, cache, scoring, typed errors)
  lrc.py            standard + enhanced LRC parser/writer, even spreading
  transcription.py  faster-whisper + whisper.cpp, token→word merging
  alignment.py      monotonic fuzzy DP alignment, synthetic/confidence flags
  energy_sync.py    dependency-free vocal-energy fallback
  ass.py            safe ASS escaping, `\kf` karaoke runs, Malayalam font style
  render.py         FFmpeg/libass render + post-render QA
  pipeline.py       ingest → extract → separate → lyrics → sync → render
  cli.py            doctor / gui / separate / lyrics / sync / render / run
  gui.py            PySide6 desktop UI with worker threads and Cancel
```

Each job lives in its own directory:

```
<jobs>/20261120-110728-song-4a2d5bc9a2/
  manifest.json      stages, artifacts, hashes, warnings
  source.wav         normalised 44.1 kHz stereo
  instrumental.wav   vocals removed
  vocals.wav         rough vocal stem (used for timing)
  lyrics.lrc         enhanced LRC with <mm:ss.xx> word tags
  lyrics.json        full model, including synthetic flags
  karaoke.ass        subtitle events
  karaoke.mp4        rendered video
```

---

## Proof the fixes work

The test fixture is physically meaningful: a 440 Hz tone panned centre and in
phase (the "vocal") plus a 220 Hz tone phase-inverted between channels (the
"music"). A correct center-cancel must remove 440 Hz and preserve 220 Hz.

Measured with the Goertzel algorithm (full-scale amplitude = 1.0):

| File | 440 Hz (vocal) | 220 Hz (music) |
|---|---|---|
| `song.wav` | 0.30 | 0.20 |
| `instrumental.wav` | **0.00** | **0.20** |
| `vocals.wav` | **0.30** | **0.00** |

The automated suite asserts those relationships, renders a real MP4, probes the
streams, and decodes the whole file. Run it with:

```bash
python -m pytest tests -q
```

Current status: **63 passed**.

---

## Install

### 1. FFmpeg (required)

Download a *full* build from [gyan.dev](https://www.gyan.dev/ffmpeg/builds/) or
[BtbN](https://github.com/BtbN/FFmpeg-Builds), then either add its `bin` folder
to `PATH` or set:

```
ABI_FFMPEG=C:\ffmpeg\bin\ffmpeg.exe
ABI_FFPROBE=C:\ffmpeg\bin\ffprobe.exe
```

The build must include libass (the `ass` filter). The full builds do.

### 2. The app

```bash
git clone https://github.com/ashokthrissur-cmd/karaokeking.git
cd karaokeking
python -m pip install -r requirements.txt      # PySide6 UI
python -m pip install -r requirements-ai.txt   # optional: Demucs + faster-whisper
```

### 3. Verify

```bash
python -m abikaraoke doctor
```

```
[OK  ] FFmpeg: /usr/bin/ffmpeg
[OK  ] FFprobe: /usr/bin/ffprobe
[OK  ] Demucs (AI vocal removal): /usr/bin/python3 (model htdemucs)
[OK  ] faster-whisper: model 'base'
[MISS] whisper.cpp: whisper-cli not found; model=not set
[OK  ] PySide6 GUI: available
```

`MISS` is not fatal: the center-cancel and Smart Sync fallbacks still work.

---

## Use

### Desktop UI

```bash
python -m abikaraoke gui
```

The layout mirrors the original app — sidebar (Song / Websites / Automations /
Plugins / More) and four numbered panels:

1. **Song** — choose a file, artist, title.
2. **Lyrics & AI timing** — *Fetch lyrics (LRCLIB)*, load `.lrc`/`.txt`, or
   *AI auto-sync*.
3. **Instrumental** — Automatic / Demucs / Center-cancel / Keep original.
4. **Karaoke video output** — timing mode, resolution, next-line preview, then
   *Quick preview (20 s)* or *MAKE KARAOKE VIDEO (automatic)*.

Every long operation runs on a worker thread; the progress log is live and
**Cancel** actually stops the child process tree.

### Command line

```bash
# Full pipeline
python -m abikaraoke run song.mp3 \
  --artist "A. R. Rahman" --title "Song Name" \
  --sync auto --separator auto \
  --resolution 1920x1080 --out karaoke.mp4

# Preview the first 20 seconds
python -m abikaraoke run song.mp3 --artist ... --title ... --preview 20

# Just remove vocals
python -m abikaraoke separate song.mp3 --method center --out instrumental.wav

# Just fetch lyrics
python -m abikaraoke lyrics --artist "..." --title "..." --out song.lrc

# Re-time an existing LRC against the vocal
python -m abikaraoke sync --audio song.mp3 --lyrics song.lrc --mode ai --out song.synced.lrc

# Render from an existing LRC
python -m abikaraoke render --audio instrumental.wav --lyrics song.lrc --out karaoke.mp4
```

Useful flags:

| Flag | Meaning |
|---|---|
| `--sync auto\|ai\|energy\|none` | `auto` tries AI then falls back to energy |
| `--separator auto\|demucs\|center\|none` | `auto` uses Demucs if installed |
| `--language ml` | force a Whisper language (default auto-detect) |
| `--keep-intermediates` | keep `source.wav` and `vocals.wav` |
| `--font`, `--font-size`, `--position`, `--next-line` | subtitle styling |

---

## Honest timing

Karaoke timing is only as good as the evidence behind it. Every word carries:

- `start`, `end` — seconds,
- `confidence` — ASR confidence multiplied by alignment similarity,
- `synthetic` — `true` when the time was interpolated between two measured
  words rather than heard.

Lines also carry a confidence score. The pipeline warns when fewer than half of
the lyric tokens were matched, and the GUI shows the match percentage after
AI sync. Interpolated words are rendered normally, but they are never described
as "exact".

---

## Troubleshooting

**"FFmpeg/ffprobe are required"**
Install a full FFmpeg build and restart. Check `python -m abikaraoke doctor`.

**"This FFmpeg build has no 'ass' filter"**
You have a minimal build. Install a full one (gyan.dev `release-full`).

**Vocal removal is only "center-cancel"**
Demucs is not importable by the interpreter ABI Karaoke is using. Install it
into the *same* environment (`python -m pip install demucs`) and re-run
`doctor`. Center-cancel is instant and works well for centre-panned vocals, but
it thins bass and drums — Demucs is much better.

**"No lyrics found for …"**
LRCLIB has no record for that artist/title combination. Try a shorter title,
add the artist, or load an `.lrc`/`.txt` file manually. Network failures are
reported separately from "not found".

**AI sync says "AI backend unavailable"**
Neither faster-whisper nor whisper.cpp is installed. Install
`faster-whisper`, or set `ABI_WHISPER_CLI` and `ABI_WHISPER_MODEL` for
whisper.cpp. Smart Sync (energy) is used automatically and labelled as such.

**Malayalam / Tamil text shows boxes**
Install **Noto Sans Malayalam** (and Noto Sans Tamil). The ASS file references
those families; libass will fall back to a default font if they are missing.

**A render was cancelled but a process is still running**
Cancellation kills the whole process tree (`taskkill /T` on Windows,
`killpg` elsewhere). If a third-party tool spawned a detached daemon, kill it
manually.

---

## Development

```bash
python -m pip install -e ".[dev]"
python -m pytest tests -q
```

The suite covers the process supervisor (including the 400 KB dual-pipe
deadlock case), LRC parsing/round-trips, LRCLIB behaviour with a fake
transport, alignment monotonicity and synthetic flags, ASS escaping, workspace
provenance, Goertzel-verified separation, real FFmpeg rendering, the full
pipeline, and a headless Qt smoke test.

### Build the Windows executable and installer

```powershell
pyinstaller --noconfirm --clean abikaraoke.spec
& "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe" "installer\KaraokeForge.iss"
```

GitHub Actions does this automatically on every push and pull request; see
`.github/workflows/windows-ci.yml`.

---

## License

MIT. See [`LICENSE`](LICENSE).
