"""Lyric-to-transcript alignment.

The original app could treat a whole ASR segment as one "word" and silently
interpolate everything else while calling the result exact.  This module:
  * assembles tokens into words (see transcription.merge_subword_tokens);
  * performs monotonic fuzzy alignment, not just exact matching;
  * marks every interpolated timestamp as ``synthetic``;
  * reports a per-line confidence so the UI can ask for review.
"""

from __future__ import annotations

import difflib
import re
import unicodedata
from typing import Dict, List, Optional, Sequence, Tuple

from .models import AlignmentReport, LyricLine, Lyrics, Transcript, TranscriptWord, Word

_PUNCT_RE = re.compile(r"^[\W_]+|[\W_]+$", re.UNICODE)


def normalize_token(text: str) -> str:
    """Unicode-aware normalisation used only for matching, never for display."""

    text = unicodedata.normalize("NFKC", text or "").casefold().strip()
    text = _PUNCT_RE.sub("", text)
    return text


def tokenize(text: str) -> List[str]:
    tokens = [t for t in re.split(r"\s+", (text or "").strip()) if t]
    if len(tokens) <= 1 and len(text.strip()) > 1:
        stripped = text.strip()
        if not re.search(r"\s", stripped) and re.search(r"[\u3040-\u9fff\uac00-\ud7af]", stripped):
            tokens = list(stripped)
    return tokens


def _similarity(a: str, b: str) -> float:
    if not a or not b:
        return 0.0
    if a == b:
        return 1.0
    if len(a) >= 3 and (a in b or b in a):
        return 0.85
    return difflib.SequenceMatcher(None, a, b).ratio()


def fuzzy_align(
    lyrics_tokens: Sequence[str],
    transcript_tokens: Sequence[str],
    *,
    threshold: float = 0.55,
) -> List[Tuple[int, int, float]]:
    """Monotonic global alignment returning ``(lyric_index, word_index, score)``."""

    n, m = len(lyrics_tokens), len(transcript_tokens)
    if n == 0 or m == 0:
        return []

    if n * m > 4_000_000:
        matcher = difflib.SequenceMatcher(None, list(lyrics_tokens), list(transcript_tokens), autojunk=False)
        matches: List[Tuple[int, int, float]] = []
        for block in matcher.get_matching_blocks():
            for offset in range(block.size):
                matches.append((block.a + offset, block.b + offset, 1.0))
        return matches

    gap = -0.65
    score = [[0.0] * (m + 1) for _ in range(n + 1)]
    move = [[0] * (m + 1) for _ in range(n + 1)]  # 0 diag, 1 up, 2 left

    for i in range(1, n + 1):
        score[i][0] = i * gap
        move[i][0] = 1
    for j in range(1, m + 1):
        score[0][j] = j * gap
        move[0][j] = 2

    for i in range(1, n + 1):
        a = lyrics_tokens[i - 1]
        for j in range(1, m + 1):
            sim = _similarity(a, transcript_tokens[j - 1])
            diag = score[i - 1][j - 1] + (2.0 * sim if sim >= threshold else -1.0)
            up = score[i - 1][j] + gap
            left = score[i][j - 1] + gap
            best = max(diag, up, left)
            score[i][j] = best
            move[i][j] = 0 if best == diag else (1 if best == up else 2)

    matches = []
    i, j = n, m
    while i > 0 and j > 0:
        direction = move[i][j]
        if direction == 0:
            sim = _similarity(lyrics_tokens[i - 1], transcript_tokens[j - 1])
            if sim >= threshold:
                matches.append((i - 1, j - 1, sim))
            i -= 1
            j -= 1
        elif direction == 1:
            i -= 1
        else:
            j -= 1
    matches.reverse()
    return matches


def _line_windows(lyrics: Lyrics, duration: float) -> List[Tuple[float, float]]:
    """Best-effort time window for each line before alignment."""

    lines = lyrics.sorted_lines()
    windows: List[Optional[Tuple[float, float]]] = []
    for line in lines:
        if line.end > line.start and not line.synthetic:
            windows.append((line.start, line.end))
        else:
            windows.append(None)

    known = [i for i, window in enumerate(windows) if window is not None]
    if not known:
        cursor = 0.0
        total_weight = sum(max(1, len(tokenize(ln.text))) for ln in lines) or 1
        usable = max(1.0, duration)
        for index, line in enumerate(lines):
            weight = max(1, len(tokenize(line.text)))
            span = usable * weight / total_weight
            windows[index] = (cursor, min(duration, cursor + span) if duration else cursor + span)
            cursor += span
        return [w for w in windows if w is not None]  # type: ignore[misc]

    for index, window in enumerate(windows):
        if window is not None:
            continue
        previous = max((i for i in known if i < index), default=None)
        following = min((i for i in known if i > index), default=None)
        start = windows[previous][1] if previous is not None else 0.0  # type: ignore[index]
        end = windows[following][0] if following is not None else (duration or start + 4.0)  # type: ignore[index]
        if end <= start:
            end = start + 1.0
        count = (following if following is not None else len(lines)) - (previous if previous is not None else -1) - 1
        count = max(1, count)
        slot = (end - start) / count
        offset = index - (previous + 1 if previous is not None else 0)
        windows[index] = (start + offset * slot, start + (offset + 1) * slot)
    return [w for w in windows if w is not None]  # type: ignore[misc]


def align_lyrics(
    lyrics: Lyrics,
    transcript: Transcript,
    *,
    duration: float = 0.0,
) -> AlignmentReport:
    """Align lyric tokens to transcript words and produce timed lines."""

    lines = lyrics.sorted_lines()
    if not lines:
        return AlignmentReport(lines=[], method="none", warnings=["No lyric lines to align."])

    if not transcript.words:
        from .energy_sync import spread_evenly

        spread = spread_evenly(lyrics, duration or max((ln.end for ln in lines), default=0.0))
        return AlignmentReport(
            lines=spread.lines,
            method="even",
            matched_ratio=0.0,
            low_confidence_lines=list(range(len(spread.lines))),
            warnings=["No transcript available; timings were spread evenly and are synthetic."],
        )

    windows = _line_windows(lyrics, duration)

    flat_tokens: List[str] = []
    token_owner: List[Tuple[int, int]] = []
    for line_index, line in enumerate(lines):
        tokens = tokenize(line.text)
        for token_index, token in enumerate(tokens):
            flat_tokens.append(normalize_token(token))
            token_owner.append((line_index, token_index))

    transcript_tokens = [normalize_token(w.text) for w in transcript.words]
    matches = fuzzy_align(flat_tokens, transcript_tokens)

    matched: Dict[Tuple[int, int], Tuple[float, float, float]] = {}
    for lyric_index, word_index, score in matches:
        line_index, token_index = token_owner[lyric_index]
        word = transcript.words[word_index]
        matched[(line_index, token_index)] = (word.start, max(word.start + 0.05, word.end), word.confidence * score)

    result: List[LyricLine] = []
    low_confidence: List[int] = []
    total_tokens = 0
    matched_tokens = 0

    for line_index, line in enumerate(lines):
        tokens = tokenize(line.text)
        total_tokens += len(tokens)
        window_start, window_end = windows[line_index] if line_index < len(windows) else (line.start, line.end)
        line_matches = [(idx, matched[(line_index, idx)]) for idx in range(len(tokens)) if (line_index, idx) in matched]
        matched_tokens += len(line_matches)

        if line_matches:
            window_start = min(window_start, line_matches[0][1][0])
            window_end = max(window_end, line_matches[-1][1][1])

        words: List[Word] = []
        for token_index, token in enumerate(tokens):
            if (line_index, token_index) in matched:
                start, end, confidence = matched[(line_index, token_index)]
                words.append(Word(text=token, start=start, end=end, confidence=confidence, synthetic=False))
                continue

            previous = next(
                ((idx, matched[(line_index, idx)]) for idx in range(token_index - 1, -1, -1) if (line_index, idx) in matched),
                None,
            )
            following = next(
                ((idx, matched[(line_index, idx)]) for idx in range(token_index + 1, len(tokens)) if (line_index, idx) in matched),
                None,
            )
            if previous and following:
                gap_start = previous[1][1]
                gap_end = following[1][0]
                span = max(0.05, gap_end - gap_start)
                steps = following[0] - previous[0]
                step = span / max(1, steps)
                start = gap_start + (token_index - previous[0] - 1) * step
                end = start + step
            elif previous:
                start = previous[1][1]
                end = start + max(0.18, (window_end - start) / max(1, len(tokens) - token_index))
            elif following:
                end = following[1][0]
                start = max(window_start, end - max(0.18, (end - window_start) / max(1, token_index + 1)))
            else:
                span = max(0.2, (window_end - window_start) / max(1, len(tokens)))
                start = window_start + token_index * span
                end = start + span
            words.append(Word(text=token, start=start, end=max(start + 0.05, end), confidence=0.2, synthetic=True))

        cursor = max(0.0, window_start)
        for word in words:
            if word.start < cursor:
                word.start = cursor
            if word.end <= word.start:
                word.end = word.start + 0.05
            cursor = word.end

        confidence = (len(line_matches) / len(tokens)) if tokens else 0.0
        synthetic = len(line_matches) == 0
        if confidence < 0.5:
            low_confidence.append(line_index)

        result.append(
            LyricLine(
                start=words[0].start if words else window_start,
                end=words[-1].end if words else window_end,
                text=line.text,
                words=words,
                confidence=confidence,
                synthetic=synthetic,
                source="whisper" if not synthetic else "whisper-interpolated",
            )
        )

    ratio = matched_tokens / total_tokens if total_tokens else 0.0
    warnings: List[str] = []
    if ratio < 0.5:
        warnings.append(
            f"Only {ratio:.0%} of lyric words matched the transcript. Review the timing before export."
        )
    if any(word.synthetic for line in result for word in line.words):
        warnings.append("Some word timings are interpolated (marked synthetic), not measured.")

    return AlignmentReport(
        lines=result,
        method="whisper-words",
        matched_ratio=ratio,
        low_confidence_lines=low_confidence,
        warnings=warnings,
    )
