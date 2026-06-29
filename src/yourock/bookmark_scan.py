from __future__ import annotations

from dataclasses import dataclass
from io import BytesIO
from pathlib import Path
import re
from typing import Any

from PIL import Image

from .browser_capture import (
    _dismiss_consent,
    _get_runtime,
    _seek_video,
    _wait_for_video,
)
from .capture import _ocr, _prepare_for_ocr
from .config import ProjectConfig
from .detection import parse_name_from_ocr
from .utils import format_timestamp


# The You Rock segment normally appears just before one of the first three
# non-zero description chapters. The Patreon lower-third appears shortly
# before the You Rock lower-third and acts as a sequence marker.
MAX_EARLY_BOOKMARKS = 3
PATREON_SCAN_BEFORE_SECONDS = 45
PATREON_TO_YOU_ROCK_MAX_SECONDS = 45


@dataclass(frozen=True)
class DescriptionBookmark:
    timestamp_seconds: int
    label: str


@dataclass(frozen=True)
class BookmarkMatch:
    timestamp_seconds: int
    bookmark_seconds: int
    bookmark_label: str
    name: str
    confidence: float
    ocr_text: str
    screenshot: Path


@dataclass(frozen=True)
class _FrameAnalysis:
    timestamp_seconds: int
    bookmark: DescriptionBookmark
    name: str
    confidence: float
    ocr_text: str
    crop: Image.Image
    has_patreon_url: bool
    has_you_rock: bool


def scan_description_bookmarks(
    config: ProjectConfig,
    video_id: str,
) -> tuple[list[DescriptionBookmark], list[BookmarkMatch]]:
    """Find YOU ROCK lower-thirds near the first chapters, after Patreon URL."""
    runtime = _get_runtime(config)
    page = runtime.page
    timeout_ms = max(30, config.browser_timeout_seconds) * 1000
    page.set_default_timeout(timeout_ms)

    page.goto(
        f"https://www.youtube.com/watch?v={video_id}&autoplay=1",
        wait_until="domcontentloaded",
        timeout=timeout_ms,
    )
    _dismiss_consent(page)
    _wait_for_video(page, timeout_ms, required_seconds=60)
    page.wait_for_timeout(750)

    description_text, anchor_rows = _read_description(page)
    bookmarks = merge_description_bookmarks(
        parse_description_bookmarks(description_text),
        _bookmarks_from_anchor_rows(anchor_rows),
    )

    duration = _video_duration(page)
    bookmarks = [
        bookmark
        for bookmark in bookmarks
        if 0 < bookmark.timestamp_seconds < max(1, int(duration))
    ]
    if not bookmarks:
        raise RuntimeError(
            "No timestamp bookmarks were found in the expanded YouTube description."
        )

    # Intro chapters are not useful for the shout-out search. Ignore every
    # description bookmark before 1:00, then inspect only the first configured
    # number of remaining chapters.
    eligible_bookmarks = [
        bookmark
        for bookmark in bookmarks
        if bookmark.timestamp_seconds >= 60
    ]
    candidate_bookmarks = select_early_bookmarks(
        eligible_bookmarks,
        MAX_EARLY_BOOKMARKS,
    )
    if not candidate_bookmarks:
        raise RuntimeError(
            "No description bookmarks at or after 1:00 were available to scan."
        )

    you_rock_before = max(1, config.bookmark_scan_before_seconds)
    scan_before = max(you_rock_before, PATREON_SCAN_BEFORE_SECONDS)
    seconds_to_bookmark = _seconds_to_scan(
        candidate_bookmarks,
        before_seconds=scan_before,
        sample_every_seconds=config.bookmark_sample_every_seconds,
    )
    print(
        f"  Description bookmarks: {len(bookmarks)}; "
        f"checking first {len(candidate_bookmarks)} chapter(s); "
        f"scanning {len(seconds_to_bookmark)} unique second(s)"
    )

    video = page.locator("video").first
    analyses: list[_FrameAnalysis] = []
    patreon_seconds: dict[int, list[int]] = {
        bookmark.timestamp_seconds: [] for bookmark in candidate_bookmarks
    }

    for index, (second, bookmark) in enumerate(seconds_to_bookmark.items(), start=1):
        _seek_video(page, float(second), timeout_ms=min(timeout_ms, 30_000))
        page.wait_for_timeout(125)
        image_bytes = video.screenshot(type="jpeg", quality=88)
        analysis = _analyze_frame(config, image_bytes, second, bookmark)
        analyses.append(analysis)

        if analysis.has_patreon_url:
            markers = patreon_seconds[bookmark.timestamp_seconds]
            first_marker_for_bookmark = not markers
            markers.append(second)
            if first_marker_for_bookmark:
                print(
                    f"  Patreon URL at {format_timestamp(second)} "
                    f"before {format_timestamp(bookmark.timestamp_seconds)}"
                )

        if analysis.has_you_rock:
            seconds_before_bookmark = (
                bookmark.timestamp_seconds - analysis.timestamp_seconds
            )
            marker = most_recent_prior_marker(
                patreon_seconds.get(bookmark.timestamp_seconds, []),
                analysis.timestamp_seconds,
                max_gap_seconds=PATREON_TO_YOU_ROCK_MAX_SECONDS,
            )
            if (
                0 <= seconds_before_bookmark <= you_rock_before
                and marker is not None
            ):
                print(
                    f"  YOU ROCK candidate at {format_timestamp(second)}: "
                    f"{analysis.name or '(name not detected)'} "
                    f"({analysis.confidence:.3f}); moving to next video"
                )
                break
        elif index % 60 == 0:
            print(f"  Scanned {index}/{len(seconds_to_bookmark)} frame(s)...")

    raw_hits: list[_RawHit] = []
    for analysis in analyses:
        if not analysis.has_you_rock:
            continue

        # The shout-out should be close to the upcoming chapter.
        seconds_before_bookmark = (
            analysis.bookmark.timestamp_seconds - analysis.timestamp_seconds
        )
        if not 0 <= seconds_before_bookmark <= you_rock_before:
            continue

        markers = patreon_seconds.get(analysis.bookmark.timestamp_seconds, [])
        marker = most_recent_prior_marker(
            markers,
            analysis.timestamp_seconds,
            max_gap_seconds=PATREON_TO_YOU_ROCK_MAX_SECONDS,
        )
        if marker is None:
            print(
                f"  Ignoring YOU ROCK at {format_timestamp(analysis.timestamp_seconds)}: "
                "no Patreon URL was detected shortly before it."
            )
            continue

        raw_hits.append(
            _RawHit(
                timestamp_seconds=analysis.timestamp_seconds,
                bookmark=analysis.bookmark,
                name=analysis.name,
                confidence=analysis.confidence,
                ocr_text=analysis.ocr_text,
                crop=analysis.crop,
                patreon_timestamp_seconds=marker,
            )
        )

    grouped = _dedupe_hits(raw_hits, config.dedupe_seconds)
    config.screenshots_dir.mkdir(parents=True, exist_ok=True)
    matches: list[BookmarkMatch] = []
    for hit in grouped:
        output_path = (
            config.screenshots_dir
            / f"{video_id}-{hit.timestamp_seconds}-bookmark.jpg"
        )
        hit.crop.save(output_path, format="JPEG", quality=92)
        matches.append(
            BookmarkMatch(
                timestamp_seconds=hit.timestamp_seconds,
                bookmark_seconds=hit.bookmark.timestamp_seconds,
                bookmark_label=hit.bookmark.label,
                name=hit.name,
                confidence=hit.confidence,
                ocr_text=hit.ocr_text,
                screenshot=output_path,
            )
        )
        print(
            f"  Confirmed sequence: Patreon at "
            f"{format_timestamp(hit.patreon_timestamp_seconds)} -> YOU ROCK at "
            f"{format_timestamp(hit.timestamp_seconds)}"
        )

    return bookmarks, matches


def select_early_bookmarks(
    bookmarks: list[DescriptionBookmark],
    maximum: int = MAX_EARLY_BOOKMARKS,
) -> list[DescriptionBookmark]:
    """Return the first non-zero description chapters in chronological order."""
    return [
        bookmark
        for bookmark in sorted(bookmarks, key=lambda value: value.timestamp_seconds)
        if bookmark.timestamp_seconds > 0
    ][: max(1, maximum)]


def most_recent_prior_marker(
    marker_seconds: list[int],
    target_second: int,
    *,
    max_gap_seconds: int,
) -> int | None:
    eligible = [
        second
        for second in marker_seconds
        if 0 <= target_second - second <= max(1, max_gap_seconds)
    ]
    return max(eligible) if eligible else None


def parse_description_bookmarks(text: str) -> list[DescriptionBookmark]:
    bookmarks: list[DescriptionBookmark] = []
    for raw_line in text.splitlines():
        line = " ".join(raw_line.split()).strip()
        if not line:
            continue
        match = re.search(r"(?<!\d)(?:(\d{1,2}):)?(\d{1,2}):(\d{2})(?!\d)", line)
        if not match:
            continue
        hours = int(match.group(1) or 0)
        minutes = int(match.group(2))
        seconds = int(match.group(3))
        if seconds >= 60 or (hours > 0 and minutes >= 60):
            continue
        total = hours * 3600 + minutes * 60 + seconds
        label = (line[: match.start()] + " " + line[match.end() :]).strip(" -–—:|")
        bookmarks.append(DescriptionBookmark(total, label))
    return _dedupe_bookmarks(bookmarks)


def merge_description_bookmarks(
    *groups: list[DescriptionBookmark],
) -> list[DescriptionBookmark]:
    merged: list[DescriptionBookmark] = []
    for group in groups:
        merged.extend(group)
    return _dedupe_bookmarks(merged)


def _read_description(page: Any) -> tuple[str, list[dict[str, str]]]:
    for selector in (
        "#description-inline-expander #expand",
        "#description #expand",
        "ytd-text-inline-expander #expand",
        "#expand",
    ):
        try:
            expand = page.locator(selector).first
            if expand.count() and expand.is_visible():
                expand.click(timeout=2500)
                page.wait_for_timeout(500)
                break
        except Exception:
            continue

    return page.evaluate(
        r'''() => {
            const roots = [
                document.querySelector('ytd-watch-metadata #description'),
                document.querySelector('#description-inline-expander'),
                document.querySelector('ytd-video-description-infocards-section-renderer')
            ].filter(Boolean);
            const root = roots[0] || document.body;
            const anchors = Array.from(root.querySelectorAll('a[href]')).map(anchor => ({
                href: anchor.href || '',
                text: (anchor.textContent || '').trim(),
                line: (anchor.parentElement?.textContent || '').trim()
            }));
            return [root.innerText || root.textContent || '', anchors];
        }'''
    )


def _bookmarks_from_anchor_rows(rows: list[dict[str, str]]) -> list[DescriptionBookmark]:
    bookmarks: list[DescriptionBookmark] = []
    for row in rows or []:
        href = str(row.get("href") or "")
        text = str(row.get("text") or "")
        line = " ".join(str(row.get("line") or "").split())
        seconds = _timestamp_text_to_seconds(text)
        if seconds is None and ("youtube.com/watch" in href or "youtu.be/" in href):
            seconds = _seconds_from_href(href)
        if seconds is None:
            continue
        label = line.replace(text, "", 1).strip(" -–—:|") or text
        label = " ".join(label.split())[:160]
        bookmarks.append(DescriptionBookmark(seconds, label))
    return _dedupe_bookmarks(bookmarks)


def _seconds_from_href(href: str) -> int | None:
    match = re.search(r"[?&](?:t|start)=([^&#]+)", href)
    if not match:
        return None
    value = match.group(1)
    if value.isdigit():
        return int(value)
    total = 0
    found = False
    for number, unit in re.findall(r"(\d+)([hms])", value.lower()):
        found = True
        multiplier = {"h": 3600, "m": 60, "s": 1}[unit]
        total += int(number) * multiplier
    return total if found else None


def _timestamp_text_to_seconds(value: str) -> int | None:
    match = re.fullmatch(r"\s*(?:(\d{1,2}):)?(\d{1,2}):(\d{2})\s*", value)
    if not match:
        return None
    hours = int(match.group(1) or 0)
    minutes = int(match.group(2))
    seconds = int(match.group(3))
    if seconds >= 60 or (hours > 0 and minutes >= 60):
        return None
    return hours * 3600 + minutes * 60 + seconds


def _dedupe_bookmarks(
    bookmarks: list[DescriptionBookmark],
) -> list[DescriptionBookmark]:
    by_second: dict[int, DescriptionBookmark] = {}
    for bookmark in bookmarks:
        current = by_second.get(bookmark.timestamp_seconds)
        if current is None or (not current.label and bookmark.label):
            by_second[bookmark.timestamp_seconds] = bookmark
    return [by_second[second] for second in sorted(by_second)]


def _seconds_to_scan(
    bookmarks: list[DescriptionBookmark],
    *,
    before_seconds: int,
    sample_every_seconds: int,
) -> dict[int, DescriptionBookmark]:
    result: dict[int, DescriptionBookmark] = {}
    step = max(1, sample_every_seconds)
    before = max(1, before_seconds)
    for bookmark in bookmarks:
        # Never sample 0:00. With a five-second interval, the earliest
        # possible frame is 0:05; later chapters still begin at their
        # normal chapter-minus-window time.
        start = max(step, bookmark.timestamp_seconds - before)
        for second in range(start, bookmark.timestamp_seconds + 1, step):
            # If windows overlap, associate the second with the earliest upcoming bookmark.
            result.setdefault(second, bookmark)
    return dict(sorted(result.items()))


def _video_duration(page: Any) -> float:
    value = page.locator("video").first.evaluate(
        "video => Number.isFinite(video.duration) ? video.duration : 0"
    )
    return float(value or 0)


@dataclass
class _RawHit:
    timestamp_seconds: int
    bookmark: DescriptionBookmark
    name: str
    confidence: float
    ocr_text: str
    crop: Image.Image
    patreon_timestamp_seconds: int

    @property
    def score(self) -> float:
        return self.confidence + (0.25 if self.name else 0.0)


def _analyze_frame(
    config: ProjectConfig,
    image_bytes: bytes,
    timestamp_seconds: int,
    bookmark: DescriptionBookmark,
) -> _FrameAnalysis:
    with Image.open(BytesIO(image_bytes)) as image:
        image = image.convert("RGB")
        top = int(image.height * config.crop_top_fraction)
        crop = image.crop((0, top, image.width, image.height))
        processed = _prepare_for_ocr(crop)
        ocr_text, confidence = _ocr(processed)
        return _FrameAnalysis(
            timestamp_seconds=timestamp_seconds,
            bookmark=bookmark,
            name=parse_name_from_ocr(ocr_text) if _contains_you_rock(ocr_text) else "",
            confidence=confidence,
            ocr_text=ocr_text,
            crop=crop.copy(),
            has_patreon_url=_contains_patreon_url(ocr_text),
            has_you_rock=_contains_you_rock(ocr_text),
        )


def _contains_you_rock(text: str) -> bool:
    normalized = text.upper().replace("0", "O")
    normalized = re.sub(r"[^A-Z]+", " ", normalized)
    return re.search(r"\bYOU\s+ROCK\b", normalized) is not None


def _contains_patreon_url(text: str) -> bool:
    """Tolerate punctuation and common OCR spacing in the Patreon URL."""
    normalized = text.upper().replace("0", "O")
    compact = re.sub(r"[^A-Z0-9]+", "", normalized)
    if "PATREON" not in compact:
        return False
    return (
        "PATREONCOM" in compact
        or "COMMANDZONE" in compact
        or ("COMMAND" in compact and "ZONE" in compact)
    )


def _dedupe_hits(hits: list[_RawHit], tolerance_seconds: int) -> list[_RawHit]:
    if not hits:
        return []
    ordered = sorted(hits, key=lambda hit: hit.timestamp_seconds)
    groups: list[list[_RawHit]] = [[ordered[0]]]
    for hit in ordered[1:]:
        if hit.timestamp_seconds - groups[-1][-1].timestamp_seconds <= max(1, tolerance_seconds):
            groups[-1].append(hit)
        else:
            groups.append([hit])
    return [max(group, key=lambda hit: hit.score) for group in groups]
