# KaraokeForge: synthesized technical audit and ABI Karaoke recommendations

## Executive assessment

KaraokeForge is a single-project .NET 8 Windows Forms desktop application that orchestrates local FFmpeg conversion/rendering, optional local Demucs vocal separation, optional whisper.cpp transcription, and LRCLIB lyric lookup. The checked source demonstrates a real end-to-end workflow, editable LRC text, manual stage controls, render styling, and recent-path persistence. It does **not** demonstrate dependable word-level alignment, Malayalam-ready transcription/rendering, robust subprocess cancellation, validated outputs, or portable editable project files.

For ABI Karaoke (known here as Python/PySide6 with Demucs, faster-whisper, and FFmpeg), the most useful comparison is architectural rather than code-level. KaraokeForge shows that staged local-media workflows and explicit human correction can coexist with one-click automation, but it should not be treated as a production blueprint. ABI should retain its Python stack and build stronger job isolation, artifact provenance, timing QA, cancellation, project persistence, multilingual support, and tested media validation around it.

**Evidence discipline:** “Verified implementation” below means behavior visible in the supplied source audit. “README assertion” means documentation language that is not fully established by the code. These are not interchangeable. The audit input reports that repository commands, scripts, and binaries were not run and source was not modified; this report is a synthesis of those findings, not runtime validation.

## Actual architecture and dataflow (verified implementation)

1. **Desktop UI and transient job state.** `Program.cs` defines the WinForms entry point and main form. The user can load local media, edit lyrics, configure render controls, use manual stage buttons, or start an automatic staged pipeline. Pipeline options are assembled from current controls into a transient context; no serialized project format or settings restoration is shown (`Program.cs:103-112, 1321-1349, 2108-2135, 2698-2719`).
2. **Local media ingestion.** Imported files are local paths. The code invokes FFmpeg to extract audio as 44.1 kHz, stereo, signed 16-bit PCM WAV. Drag/drop and file dialogs accept common audio/video types. Work artifacts are stored under `%LOCALAPPDATA%/KaraokeForge/work` with fixed filenames in several stages (`Program.cs:163-178, 455-461, 2164-2253`).
3. **Instrumental generation.** The app probes generic `python`, `python3`, and `py` names for Demucs. It invokes the local Python module with `--two-stems=vocals`, default model `hdemucs`, and searches a persistent output tree for the newest recursive `no_vocals.wav`. If Demucs is unavailable or fails in the automatic pipeline, center-channel subtraction is used; the manual and automatic forced-Demucs failure paths differ (`Program.cs:658-748, 1407-1464, 2409-2432`).
4. **Lyrics and timing.** LRCLIB exact lookup is followed by search fallback, preferring synced lyrics where available. Plain lyrics can be turned into line-level synthetic timestamps. Whisper processing converts audio to 16 kHz mono, invokes an external `whisper-cli` with JSON and optional VAD/language flags, parses token- or segment-shaped JSON, and aligns lyric words with transcript entries. Unmatched words may be interpolated. If no lyric lookup succeeds, transcript entries can be grouped into generated LRC (`Program.cs:295-409, 967-1238, 1476-1551`).
5. **Subtitle/render path.** LRC is translated into UTF-8 ASS with karaoke tags and styling, then FFmpeg loops an image or background video, burns subtitles, encodes H.264/AAC with `yuv420p` and `faststart`, and bounds duration using instrumental duration; preview is capped. Optional `loudnorm` is applied. FFmpeg arguments are passed through `ArgumentList`, and stderr is drained into bounded diagnostics (`Program.cs:516-644, 756-907, 1576-1641, 2675-2696`).
6. **Persistence and external dependencies.** Recent media paths (up to 12) and diagnostic history persist under the user’s local application data. The project itself declares no audio/ML package dependency; FFmpeg, whisper.cpp executable/models, and Python/Demucs are external tools (`KaraokeForge.csproj:1-19; Program.cs:163-209, 2611-2654`). LRCLIB receives artist/title and optional duration metadata over HTTPS (`Program.cs:295-365`).

## Feature-to-implementation matrix

| Feature | Verified implementation | Important qualification |
|---|---|---|
| Local import and audio extraction | FFmpeg decodes selected local media to stereo 44.1 kHz signed 16-bit PCM WAV; file dialog and drag/drop paths exist. | Shared fixed work filenames and no visible cleanup create stale-artifact/collision risk. |
| Vocal separation | Local Demucs invocation and center-cancellation fallback exist. | Center cancellation is not source separation. Discovery/process handling is basic; forced-mode behavior differs by pathway. |
| Lyrics retrieval | LRCLIB exact query then search; synced lyrics preferred, plain lyrics retained as fallback. | Artist/title/optional duration are sent to LRCLIB; “no upload” does not mean no network disclosure. |
| Whisper transcription | External whisper.cpp invocation, 16 kHz mono conversion, JSON parsing, optional language and VAD flags. | Token/segment shapes vary; timing assumptions and output units depend on installed backend/version. |
| Word highlighting | Enhanced LRC parsing and ASS karaoke intervals based on word start timestamps are implemented. | Timing may be synthetic, interpolated, segment-coarse, or token-fragmented; “exact” is not established. |
| Malayalam | Auto language mode is available; Unicode text can flow through files and ASS generation. | Fixed language dropdown omits Malayalam; no Malayalam-specific normalization, alignment, font fallback, shaping, or QA is evidenced. |
| Editing and controls | Editable multiline LRC, manual lyric/separation/background/preview/export controls, presets and render options. | Some controls remain editable during a run although active options are already snapshotted. |
| Preview and recents | Quick preview renders a short MP4 opened externally; recent paths persist locally. | No in-app video preview; recents are not populated at startup according to the audited constructor path. |
| Project persistence | None evidenced beyond recent media paths and diagnostic log. | No save/open project, settings restoration, artifact manifest, or portable editable generation. |
| Export | MP4 export via FFmpeg with ASS, background image/video, H.264/AAC, optional loudness normalization. | Validation is mostly process exit status; there is no post-render probe/decodability/sync check. |
| Build/deployment | .NET 8 Windows Forms project and a Windows build helper are present. | No tracked installer, tests, dependency lock, or CI workflow was observed; no artifact was built or verified. |

## README assertions versus code evidence

The README describes automatic Demucs detection/use, CUDA as potentially helpful, Whisper word-by-word or “exact” timing, VAD/full JSON, styles, preview, and output capabilities (`README.md:27-29, 63-85, 192-201, 223-236`). The implementation does contain Demucs probing, Whisper flags, karaoke ASS generation, styling, and preview wiring. However:

- **Word timing:** the code can consume token timestamps, but does not combine subword tokens into linguistic words; if token timing is absent it can treat a segment as a single timed entry. Alignment may interpolate unmatched lyric words. This does not establish exact or reliable word-level timing.
- **CUDA:** the code has no GPU capability detection or device selection. README’s CUDA note is not a compatibility guarantee, particularly for a legacy GeForce 820.
- **VAD:** optional flags/model plumbing exists, but the audit does not establish that VAD validates transcript completeness or timing.
- **Preview:** the short preview is rendered and opened externally; it is not an in-app synchronized preview.
- **Build/CI:** README describes a proposed workflow and makes claims not supported by a checked-in workflow in the observed tracked files. The build helper was inspected only as text, not run.

Treat README statements as product documentation claims, not runtime test evidence or license permission.

## Risk register

### High

1. **Shared stale audio can be reused for the wrong song.** The pipeline skips extraction if shared `work/song.wav` exists without verifying it corresponds to the current source (`Program.cs:1407-1415`; work directory at `163-178`). This is a data-integrity defect, not just a cleanup concern.
2. **Subprocesses can hang and cancellation does not stop them.** FFmpeg/Whisper/Demucs process execution is not wired to pipeline cancellation or a timeout. Demucs drains stdout before stderr; probe stderr is redirected but not read. A full unread pipe may block the child (`Program.cs:701-708, 726-748, 1353-1465`).
3. **Timing claims exceed demonstrated timing quality.** Whisper token handling does not assemble tokens into words; segment fallback is coarse; alignment can invent/interpolate timestamps. Plain-lyrics skeleton timestamps are placeholders, not observed singing times (`Program.cs:388-409, 1035-1065, 1086-1200`).
4. **ASS lyric escaping is incomplete.** The renderer escapes braces/newlines but not backslashes/control sequences; lyric content may alter ASS formatting or drawing behavior (`Program.cs:838-842, 872-892`).
5. **No license grant is evidenced.** The observed tracked-file list contains no project `LICENSE`. Third-party attributions in README do not authorize copying KaraokeForge source (`README.md:255-263`).

### Medium

1. **Demucs outputs are persistent/shared and selection can be stale or cross-job.** The app searches the newest recursive `no_vocals.wav` in a shared Demucs tree; no job identity/cleanup is shown (`Program.cs:685-718`).
2. **Manual and automatic forced-Demucs failure behavior disagrees.** Manual removal can fall back to center cancellation despite Demucs selection, while automatic pipeline throws when explicitly selected Demucs is unavailable (`Program.cs:1438-1446, 2409-2432`).
3. **Malformed/inexact timing can cascade.** Matching is bounded and heuristic; low-confidence/missing entries are dropped or replaced and unresolved lyric timestamps get generic interpolation/defaults (`Program.cs:1041-1053, 1145-1200`).
4. **Malayalam support is not established.** Language dropdown omits `ml`; there is no Malayalam-specific matching or font/shaping fallback verification (`Program.cs:1683-1687, 1826-1834, 762-800`).
5. **Render output is weakly validated.** A successful FFmpeg exit is treated as success without post-render checks for streams, duration, resolution, decodeability, or A/V sync (`Program.cs:613-623`).
6. **Fixed output/work names and absent cleanup permit collisions and accumulation.** Instrumental, preview and other files share persistent paths; no cleanup routine is evidenced (`Program.cs:163-178, 1407-1464, 2687-2696`).
7. **Project work is not portable/editable as a generation.** Only recent file paths persist; lyrics, source references, settings, tool versions, generated assets, and provenance are not bundled/restored (`Program.cs:1321-1349, 2108-2135, 2611-2654`).
8. **Privacy and executable trust boundaries need explicit UX/security policy.** Local media processing is visible, but LRCLIB receives identifying metadata; configured Whisper and Python/Demucs plus PATH-resolved FFmpeg are executable dependencies. Recent paths/logs/work artifacts persist in the user profile (`Program.cs:163-209, 295-365, 431-453, 658-724, 967-1014`).

### Low

1. **Narrow export/build support.** UI export is MP4; build helper requires FFmpeg on PATH even for build-only, although FFmpeg is a runtime dependency (`Program.cs:2675-2685; build.bat:11-18`).
2. **No checked-in quality/release evidence.** The observed tracked list contains no tests, installer, dependency lock, or CI workflow. README sample/output claims do not substitute for reproducible validation (`KaraokeForge.csproj:1-19; README.md:136-169; samples/README.md:3-21`).
3. **Layout may constrain scaling.** Fixed dimensions and positioned controls may limit resize/high-DPI behavior (`Program.cs:1697-1764, 1767-2068`).

## Comparison with ABI Karaoke’s known current approach

This comparison is limited to the stated ABI baseline—Python/PySide6, Demucs, faster-whisper, and FFmpeg—and does not infer unprovided ABI implementation details.

### Where KaraokeForge demonstrates useful advantages

- **Integrated local workflow:** source shows an actual path from local media through instrumental generation/lyrics/rendering, including manual controls and an automatic pipeline. ABI can use this as a product-flow checklist, not code to transplant.
- **Fallback and editability:** center cancellation provides a low-cost fallback when Demucs is unavailable, and editable LRC gives a human correction surface. ABI could expose comparable explicit fallback modes while labeling their quality honestly.
- **Concrete renderer choices:** explicit PCM conversion, argument-list process launching, ASS output, H.264/AAC settings, optional loudness normalization, and bounded preview illustrate useful implementation decisions to validate independently.
- **Local-first processing with transparent network boundary:** visible audio/transcription/render stages use local files/tools; lyric lookup is the identifiable metadata network call. ABI should communicate this precisely rather than claiming zero disclosure.

These are demonstrated patterns, not evidence that KaraokeForge is more robust or more accurate than ABI’s current application.

### Where KaraokeForge is worse or does not support known ABI needs

- **Stack/deployment fit:** it is Windows-only WinForms and depends on external executables; ABI’s Python/PySide6 stack is already the known product baseline. No evidence supports replacing it.
- **ASR backend:** it invokes whisper.cpp, not faster-whisper. It does not establish equivalent model/language/timestamp behavior and lacks ABI-specific Malayalam validation.
- **Malayalam:** explicit Malayalam selection is absent; Malayalam-specific text alignment, code-switching, normalization, font selection, shaping tests, and rendered QA are not demonstrated.
- **Generation portability:** no portable editable project/generation package or save/reopen model is shown. Recent paths are not a project archive and can break when source files move.
- **Reliability:** subprocesses are not cancellable/time-bounded; outputs share fixed directories; validation is limited; stale files can be mistaken for current results.
- **Timing trustworthiness:** “word-level” output may be token-level, segment-level, or interpolated. It needs ground-truth evaluation before being used as a quality benchmark.
- **Operational readiness:** tests, release installer, signed artifacts, dependency manifest/lock, and checked-in CI are not evidenced.

## Recommended ABI Karaoke architecture

Keep the Python/PySide6 application and existing Demucs/faster-whisper/FFmpeg strategy unless measured product requirements justify a change. Use a job-oriented architecture with clear boundaries:

- **Project manifest as source of truth:** versioned, portable project document records source assets (relative path plus optional content hash), lyrics and provenance, language, timing/alignment method and confidence, separation model/config, render settings, tool versions, and generated artifact paths. Save/open must handle moved assets and schema migrations. Keep large media external or package them explicitly; do not silently duplicate copyrighted source media.
- **Per-job workspace:** create unique temporary directories and output filenames for every run; write a manifest linking every output to input hashes and job ID. Clean temporary artifacts according to a documented policy, with user opt-in for retained intermediates.
- **Subprocess supervisor:** centralized wrapper for FFmpeg, Demucs, and ASR with explicit executable paths/version checks, argument arrays, concurrent stdout/stderr draining, timeout, cancellation that terminates process trees, bounded logs, and structured error results. Never infer success from filename alone.
- **Stage graph and resumability:** model ingest, separation, transcription, lyric lookup, alignment, review, render, and validation as explicit stages. Cache only with verified input/config identity; make retries idempotent. UI progress and cancellation should reflect actual child-process state.
- **Separate transcript from alignment:** preserve raw ASR segments/tokens, normalized text, lyric text, alignment mapping, confidence, and manual edits independently. Do not present interpolated timestamps as measured word times. Show low-confidence/unmatched spans for review and retain source provenance.
- **Malayalam-first capability:** expose Malayalam (`ml`) explicitly in ASR; test code-switching and common orthographic variants; use Unicode grapheme-aware normalization rather than ASCII-space assumptions; validate compatible fonts and shaping in the actual subtitle renderer. Include manual correction where ASR/alignment is uncertain.
- **Render QA:** produce ASS/SRT/LRC as intentional artifacts with tested escaping and deterministic timestamps. Probe the final file (streams, duration, dimensions, codec), decode-test it, and measure audio/video start/end and sync. Include optional loudness statistics and validate normalized audio.
- **Clear privacy/trust UX:** state exactly which metadata is sent to lyric services, what stays local, where logs/intermediates live, and retention behavior. Verify executable paths and versions; offer manual/offline lyric entry.

## Ordered migration and build plan

1. **Capture ABI baseline and acceptance criteria.** Inventory current UI/dataflow and representative supported media; define required Windows/CPU/GPU configurations, Malayalam language cases, maximum run times, and project portability goals. Do not presume GeForce 820 CUDA support; benchmark CPU-first.
2. **Add reproducible test fixtures.** Create synthetic/publicly usable short audio/video fixtures and hand-reviewed Malayalam/English/code-switched lyric cases, with expected durations, alignment anchors, and render checks. Keep licensing for fixtures explicit.
3. **Introduce job workspace and artifact manifest.** Replace shared fixed filenames with unique workspaces, job IDs, input identity hashes, deterministic stage outputs, and safe cleanup. This is the first reliability improvement before model changes.
4. **Centralize external process lifecycle.** Add async stream draining, timeouts, cancellation/kill-tree semantics, executable/version checks, and structured diagnostics for FFmpeg, Demucs, and faster-whisper. Verify cancellation in integration tests.
5. **Formalize project persistence.** Add versioned save/open manifests, portable asset references, migration tests, and a round-trip test that reopens an editable generation on another directory/machine. Define how generated subtitles, settings, and derived audio travel.
6. **Improve lyrics and multilingual alignment.** Preserve raw model output; support explicit Malayalam; add Unicode-aware normalization, code-switch tests, confidence/unmatched visualization, and explicit distinction among word, token, segment, and synthetic timing. Never label interpolation as exact.
7. **Harden subtitle generation and rendering.** Escape ASS control syntax; test fonts/shaping; render deterministic test clips; probe outputs and verify duration/streams/decode and A/V synchronization. Retain FFmpeg argument arrays.
8. **Benchmark separation and ASR configurations.** Compare ABI’s existing Demucs/faster-whisper CPU behavior and any optional GPU mode on actual supported devices, including legacy GeForce 820 only if hardware is available. Measure latency, peak memory, quality, cancellation, and failure modes; make optional heavy models opt-in.
9. **Ship with quality gates.** Add CI for lint/type checks/unit tests and media integration tests where feasible; pin/document external tool/model versions; produce a tested installer/package and release notes. Make runtime dependencies explicit and verify artifacts rather than relying on README claims.

## Tests to add

- **Project lifecycle:** save/open round trip; schema migration; moved-source relinking; missing-source recovery; relative paths; generated artifact provenance and hashes.
- **Workspace/isolation:** two concurrent jobs with same song basename; stale files present; interrupted run; cleanup retention; ensure each job consumes only its own outputs.
- **Process supervisor:** large stdout and stderr concurrently; malformed arguments; missing executable; nonzero exit; hang/timeout; cancellation during each tool; child process tree termination; bounded logs.
- **Media ingestion/render:** supported extension matrix; corrupt/zero-length input; unusual paths/Unicode filenames; probe duration; post-render stream/codec/resolution/duration/decode validation; audio-video sync tolerance; normalization behavior.
- **Lyrics/ASR/alignment:** LRCLIB exact/search/no-result/timeout; synced versus plain preference; Whisper JSON token and segment variants; timestamp units; confidence filtering; repeated lyrics; mismatches; missing tokens; interpolation labeled synthetic; no transcript fallback.
- **Malayalam:** explicit `ml`, auto versus explicit language, Malayalam-only and code-switched lyrics, punctuation/spacing/Unicode normalization, grapheme boundaries, font glyph coverage and conjunct shaping in final rendered video, manual edit round trip.
- **ASS safety:** braces, backslashes, newlines, ASS override-like text, Unicode, empty lyrics, long lines, timestamp edge cases, and color/position settings.
- **UI behavior:** recent list loaded at startup; edits during processing either disabled or clearly staged for next run; progress/cancel reflects actual subprocess; preview opens correct job output; standalone separation updates the preview source.
- **Privacy/release:** assert no media bytes sent to LRCLIB; document and test metadata fields; log redaction/retention; dependency/version inventory; packaged release smoke test.

## License and permission warning

The supplied audit reports no `LICENSE` among the tracked repository files. **Do not copy, adapt, redistribute, or treat KaraokeForge source as open source based on its public availability, README, or third-party attributions.** Obtain explicit permission or a valid applicable license first. ABI may independently implement general ideas and behaviors, while avoiding source/text/assets copied from this repository; separately comply with licenses for FFmpeg, Demucs, Whisper/whisper.cpp, fonts, models, and any fixtures it uses.


## Current .NET support and CI tooling check (2026-11-20)

Microsoft’s current lifecycle page lists .NET 8 support ending November 10, 2026, while .NET 10 LTS is supported through November 2028. Since the current date is after .NET 8’s support end, a new release should target a supported runtime unless backward compatibility with older Windows editions is the controlling requirement [1]. Microsoft’s Windows install matrix says .NET 10 supports Windows 11 and specified Windows 10 Enterprise/LTSC releases; it also states Windows 10 support is limited to LTSC and Enterprise editions. This edition constraint must be checked against ABI’s actual target PC before switching the project framework [2].

Current official action repositories document `actions/checkout@v7`, `actions/setup-dotnet@v6`, and `actions/upload-artifact@v7`; the local workflow scaffold should use these versions rather than older examples [3] [4] [5]. These are source-documentation checks, not evidence that a hosted Windows workflow has executed.

### References

[1]: https://learn.microsoft.com/en-us/dotnet/core/releases-and-support "Releases and support for .NET"
[2]: https://learn.microsoft.com/en-us/dotnet/core/install/windows "Install .NET on Windows"
[3]: https://github.com/actions/checkout "actions/checkout"
[4]: https://github.com/actions/setup-dotnet "actions/setup-dotnet"
[5]: https://github.com/actions/upload-artifact "actions/upload-artifact"


## ABI target-device implications and current implementation status

ABI provided the target laptop specifications: Intel Core i5-3230M, 4 GB RAM, NVIDIA GeForce 820M with 1 GB graphics memory, Intel HD Graphics 4000, 64-bit x64, and a 477 GB SSD. These specs establish a constrained CPU/RAM budget, but do not identify the Windows version or edition. No claim is made that the 820M is supported by the installed PyTorch or whisper.cpp CUDA builds; that must be checked on the device.

The README and setup dialog now recommend `ggml-base.bin` as the first Whisper model to try on low-memory hardware, distinguish the fast-but-lower-quality centre-cancellation route, and describe AI word timing as an estimate that must be reviewed. Demucs now runs through a supervised process helper that drains stdout and stderr concurrently, emits elapsed-time heartbeats every ten seconds, propagates cancellation, and has a one-hour safety timeout. This addresses the prior “looks stuck / waits forever” behavior, but does not make Demucs fast on ABI’s laptop.

The process helper was exercised by tests that write heavily to both output pipes, assert ongoing heartbeats, force a timeout, and test prompt cancellation of a running child. The complete test suite currently contains ten tests (five existing core tests and five process-supervision tests); Linux sandbox verification is not a substitute for a Windows run on ABI’s machine.

Still not verified or implemented: a real Malayalam-song end-to-end accuracy/latency benchmark; Demucs-versus-MDX/UVR-style separation comparisons on the GeForce 820M; a durable editable project save/open format; safe old-scratch cleanup; bundling or managed installation of FFmpeg/Whisper/Demucs; and native Windows installer execution. The current installer workflow still depends on FFmpeg being installed separately, and the Windows target framework decision remains pending the exact Windows edition/build from `winver`.
