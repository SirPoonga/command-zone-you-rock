from yourock.detection import find_candidates, parse_name_from_ocr
from yourock.transcripts import TranscriptSnippet


def test_finds_phrase_split_across_snippets():
    snippets = [
        TranscriptSnippet("Our supporter Ben", 10.0, 1.0),
        TranscriptSnippet("you", 11.0, 1.0),
        TranscriptSnippet("rock!", 12.0, 1.0),
    ]
    matches = find_candidates(
        snippets,
        (r"\byou(?: really)? rock\b",),
        window_snippets=4,
        context_before=1,
        context_after=2,
        dedupe_seconds=20,
    )
    assert len(matches) == 1
    assert matches[0].timestamp_seconds == 10.0


def test_deduplicates_overlapping_windows():
    snippets = [
        TranscriptSnippet("you rock", 20.0, 1.0),
        TranscriptSnippet("thank you", 21.0, 1.0),
        TranscriptSnippet("you rock", 25.0, 1.0),
    ]
    matches = find_candidates(
        snippets,
        (r"\byou rock\b",),
        window_snippets=2,
        context_before=0,
        context_after=0,
        dedupe_seconds=20,
    )
    assert len(matches) == 1


def test_parses_banner_name():
    assert parse_name_from_ocr("BEN WYROSDICK- YOU ROCK!!!!") == "Ben Wyrosdick"


def test_ocr_without_phrase_returns_blank():
    assert parse_name_from_ocr("UNRELATED LOWER THIRD") == ""
