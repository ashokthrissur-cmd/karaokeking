---
name: karaoke-video-pipeline
description: Builds karaoke videos from a song file by removing vocals, fetching or transcribing lyrics, time-aligning them, and burning animated word-level subtitles. Covers LRCLIB lookup and scoring, filename title parsing, center-cancel versus Demucs separation, whisper.cpp and faster-whisper alignment, ASS/libass rendering with non-Latin fonts, and FFmpeg muxing. Use when generating karaoke or lyric videos, fetching synced lyrics, removing vocals from audio, or syncing lyrics to a track.
license: Apache-2.0
metadata:
  author: karaokeking
  version: "1.0"
---

# Karaoke video pipeline

A karaoke video is four stages, each with a failure mode that looks like a
different bug to the user:

```
song file → instrumental → lyrics text → timed lines → rendered video
             (separation)   (fetch/ASR)    (alignment)     (ASS + ffmpeg)
```

## Stage 1 — Vocal removal

Three methods, in order of quality:

| Method | Quality | Cost | When |
|---|---|---|---|
| Demucs (`htdemucs`) | Best | torch, ~2 GB, slow | User has it installed |
| Center cancel | Mediocre | instant, FFmpeg only | Default fallback |
| None | Original | — | Instrumental already |

Center cancel is a stereo mid-side trick: vocals are usually mixed to the
centre, so subtracting the channels removes them.

```bash
ffmpeg -i in.wav -af "pan=stereo|c0=c0-c1|c1=c1-c0" out.wav
```

It destroys bass and any centred instrument. Never present it as equivalent to
Demucs. Detect Demucs with an import check and fall back silently, recording
the method used in the result so the UI can say which one ran.

## Stage 2 — Lyrics

### LRCLIB first, transcription second

LRCLIB (`https://lrclib.net/api`) is free, needs no key, and returns
time-stamped LRC for a large catalogue.

Two endpoints, in this order:

1. `/api/get?artist_name=…&track_name=…&duration=…` — exact match, best quality
2. `/api/search?q=…` — fuzzy, needs scoring

**Always prefer a synced result over a plain-text one**, even if the plain-text
one scores higher on title similarity. Unsynced lyrics force the app to guess
timing, which is the single biggest quality drop.

Score candidates on: exact title match, artist match, duration within ±3 s, and
`syncedLyrics` present. Reject anything with an empty or whitespace-only body.

### Parsing the title out of a filename

This is where most "lyrics not found" reports come from. Real-world filenames
look like:

```
Aaja Re Pardesi - HD difsat ait - en atte - fect pa saat ore - 12.mp3
Song Name (Official Video) [1080p].mp3
01 - Artist - Title.mp3
Title - Artist.mp3
```

A naive `filename.split(" - ")[0]` returns `Aaja Re Pardesi` only by luck; on
`01 - Artist - Title` it returns `01`. Rules that actually work:

1. Strip the extension, and any bracketed/parenthesised noise
   (`(Official Video)`, `[HD]`, `{...}`).
2. Drop a leading track number (`^\d{1,3}[\s._-]+`).
3. Split on ` - `. If there are exactly two parts, treat them as
   title/artist (or artist/title — try both).
4. If there are **three or more** parts, the first part is the title and the
   rest is junk from re-uploaders. This is the case that broke
   `Aaja Re Pardesi - HD difsat ait - en atte - …`.
5. Strip quality tokens: `HD`, `4K`, `1080p`, `720p`, `320kbps`, `x264`,
   `remastered`, `lyrical`, `full song`.
6. Collapse repeated whitespace and trim punctuation.

Then query LRCLIB with the cleaned title, and retry with the raw filename if
that returns nothing.

### Typed errors, not silent no-ops

A dead button is worse than an error. Raise distinct exceptions
(`LyricsNotFound`, `LyricsError`) carrying the query that failed, and show that
text in the UI. Add retries with backoff for 429/5xx, and cache responses on
disk keyed by the normalised query so repeat runs are instant and offline-safe.

## Stage 3 — Alignment

If lyrics are already synced (LRC), use the timestamps directly. Otherwise:

| Backend | Notes |
|---|---|
| whisper.cpp (`whisper-cli.exe`) | Small, CPU-only, ships as a zip with `ggml-*.dll`. Preferred for bundled builds. |
| faster-whisper | Needs CTranslate2 + torch; better accuracy, much larger. |

Both produce word-level timings. Two things matter:

- **Language hint.** Passing `--language hi` (or `en`, `ta`, `ml`) dramatically
  improves accuracy and speed versus autodetect on short clips.
- **Model size.** `tiny` is unusable for singing. `base` is the practical
  minimum; `small` is noticeably better. Download the model once and cache it.

If the fetched lyrics and the audio disagree (common with covers), prefer the
**audio's** timings and map the fetched text onto them by sequence alignment
(`difflib.SequenceMatcher` on normalised words), rather than trusting either
source alone.

There is also a zero-dependency fallback: energy-based sync, which detects
vocal onsets from an RMS envelope and distributes lines across them. Crude, but
it beats no timing at all and needs no model.

## Stage 4 — Rendering

Use ASS subtitles with libass, not `drawtext`. `drawtext` cannot do
word-by-word highlighting or per-syllable colour sweeps.

Key ASS features for karaoke:

```
[Script Info]
ScriptType: v4.00+
PlayResX: 1920
PlayResY: 1080

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, ...
Style: Karaoke,Noto Sans,64,&H00FFFFFF,&H0000A5FF,...

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
Dialogue: 0,0:00:12.40,0:00:16.10,Karaoke,,0,0,0,,{\k45}AA {\k60}JA {\k38}RE
```

- `\k<centiseconds>` is the per-syllable sweep. `PrimaryColour` is the
  already-sung colour, `SecondaryColour` the upcoming one.
- `\kf` sweeps smoothly instead of jumping.

### Non-Latin scripts

Devanagari, Malayalam, Tamil, Telugu, and Bengali need an explicit font or
libass renders tofu boxes. Bundle the Noto fonts and point libass at them:

```bash
ffmpeg -i instrumental.wav -vf "ass=subs.ass:fontsdir=./fonts" out.mp4
```

`fontsdir` is essential — libass does not use the system font path reliably on
Windows. Verify a glyph actually exists before shipping a font; a 4 KB "font"
is usually a broken download.

### Muxing

```bash
ffmpeg -i instrumental.wav -i video.mp4 \
  -vf "ass=subs.ass:fontsdir=fonts" \
  -c:v libx264 -crf 18 -preset medium -pix_fmt yuv420p \
  -c:a aac -b:a 192k -shortest out.mp4
```

`-pix_fmt yuv420p` is required for playback in Windows Media Player and most
phones. Without it you get a video that plays in VLC and nowhere else.

## Common user-visible failures and their real causes

| User says | Actual cause |
|---|---|
| "Lyrics not found" | Filename parser took the first ` - ` split; query was garbage |
| "Vocal removal not working" | Demucs absent, center-cancel ran, result was labelled a failure |
| "AI sync not working" | `whisper-cli.exe` missing; model downloaded but no engine |
| "Subtitles are boxes" | No `fontsdir`, or a non-Noto font without Indic coverage |
| "Video won't play on my phone" | Missing `-pix_fmt yuv420p` |
| "Timing is way off" | Unsynced lyrics chosen over a synced candidate |

## Testing without a GPU

Unit-test the pure functions — filename parsing, LRC parsing, candidate
scoring, ASS generation — with fixtures. Those are where the bugs live. Keep
separation and transcription behind interfaces so they can be stubbed, and
assert on the *structure* of the output (line count, monotonic timestamps,
non-empty text) rather than exact timings.
