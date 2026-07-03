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
    """Extract the name from the OCR segment associated with YOU ROCK."""
    rock = r"Y[O0]U\s+R[O0]C[KX](?:\s*[!1I|W]*)?"

    for raw_line in text.replace("\r", "\n").splitlines():
        line = " ".join(raw_line.split())
        if not line:
            continue

        segments = [
            segment.strip()
            for segment in re.split(r"\s*\|\s*", line)
            if segment.strip()
        ]
        for index, segment in enumerate(segments):
            if not re.search(rock, segment, flags=re.IGNORECASE):
                continue

            candidates = [segment]
            if index > 0:
                candidates.append(f"{segments[index - 1]} {segment}")

            for candidate in candidates:
                name = _name_before_rock(candidate, rock)
                if name:
                    return _format_ocr_name(name)

    flattened = " ".join(text.replace("\n", " ").split())
    name = _name_before_rock(flattened, rock)
    return _format_ocr_name(name) if name else ""


def _name_before_rock(text: str, rock: str) -> str:
    cleaned = " ".join(text.split()).upper()
    match = re.search(rf"(.{{2,80}}?)\s*[-–—:|]\s*{rock}", cleaned)
    if not match:
        match = re.search(rf"(.{{2,80}}?)\s+{rock}", cleaned)
    if not match:
        return ""

    name = re.sub(r"[^A-Z0-9' .-]", " ", match.group(1))
    name = re.sub(r"\s+", " ", name).strip(" .-|")
    words = name.split()
    if len(words) > 6:
        words = words[-6:]
    return " ".join(words)


def _format_ocr_name(name: str) -> str:
    return " ".join(
        word.capitalize() if not word.isdigit() else word
        for word in name.split()
    )


def _normalize_text(text: str) -> str:
    text = text.replace("\n", " ").replace("’", "'")
    return re.sub(r"\s+", " ", text).strip()
