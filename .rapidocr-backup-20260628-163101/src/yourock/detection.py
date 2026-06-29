from __future__ import annotations

from dataclasses import dataclass
import re

from .transcripts import TranscriptSnippet


@dataclass(frozen=True)
class Candidate:
    timestamp_seconds: float
    matched_phrase: str
    context: str


def find_candidates(
    snippets: list[TranscriptSnippet],
    patterns: tuple[str, ...],
    *,
    window_snippets: int,
    context_before: int,
    context_after: int,
    dedupe_seconds: int,
) -> list[Candidate]:
    compiled = [re.compile(pattern, flags=re.IGNORECASE) for pattern in patterns]
    candidates: list[Candidate] = []

    for index, snippet in enumerate(snippets):
        window = " ".join(item.text for item in snippets[index : index + window_snippets])
        window = _normalize_text(window)
        match = next((pattern.search(window) for pattern in compiled if pattern.search(window)), None)
        if not match:
            continue

        timestamp = float(snippet.start)
        if candidates and timestamp - candidates[-1].timestamp_seconds < dedupe_seconds:
            continue

        context_start = max(0, index - context_before)
        context_end = min(len(snippets), index + context_after + 1)
        context = " ".join(item.text for item in snippets[context_start:context_end])
        candidates.append(
            Candidate(
                timestamp_seconds=timestamp,
                matched_phrase=match.group(0),
                context=_normalize_text(context),
            )
        )

    return candidates


def parse_name_from_ocr(text: str) -> str:
    cleaned = " ".join(text.replace("\n", " ").split()).upper()
    match = re.search(r"(.{2,80}?)\s*[-–—:|]\s*YOU\s+ROCK\b", cleaned)
    if not match:
        match = re.search(r"(.{2,80}?)\s+YOU\s+ROCK\b", cleaned)
    if not match:
        return ""

    name = match.group(1)
    name = re.sub(r"[^A-Z0-9' .-]", " ", name)
    name = re.sub(r"\s+", " ", name).strip(" .-|")
    words = name.split()
    if len(words) > 6:
        words = words[-6:]
    return " ".join(word.capitalize() if not word.isdigit() else word for word in words)


def _normalize_text(text: str) -> str:
    text = text.replace("\n", " ").replace("’", "'")
    return re.sub(r"\s+", " ", text).strip()
