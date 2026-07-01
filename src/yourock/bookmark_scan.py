from __future__ import annotations

from dataclasses import dataclass
from io import BytesIO
from pathlib import Path
import re
import time
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
VIDEO_STARTUP_TIMEOUT_SECONDS = 60
VIDEO_SCAN_TIMEOUT_SECONDS = 10_800


EARLY_SWEEP_START_SECONDS = 60
EARLY_SWEEP_END_SECONDS = 480
REFINE_RADIUS_SECONDS = 5

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



def _remaining_video_timeout_ms(
    deadline: float,
    *,
    stage: str,
) -> int:
    remaining_ms = int((deadline - time.monotonic()) * 1000)
    if remaining_ms <= 0:
        raise TimeoutError(
            f"Video scan exceeded {VIDEO_SCAN_TIMEOUT_SECONDS} seconds "
            f"while {stage}."
        )
    return max(1, remaining_ms)


def scan_description_bookmarks(
    config: ProjectConfig,
    video_id: str,
) -> tuple[list[DescriptionBookmark], list[BookmarkMatch]]:
    """Search an early-show sweep, then every eligible chapter window."""
    deadline = time.monotonic() + VIDEO_SCAN_TIMEOUT_SECONDS
    runtime = _get_runtime(config)
    page = runtime.page
    timeout_ms = max(30, config.browser_timeout_seconds) * 1000
    page.set_default_timeout(timeout_ms)

    page.goto(
        f"https://www.youtube.com/watch?v={video_id}&autoplay=1",
        wait_until="domcontentloaded",
        timeout=min(
            timeout_ms,
            _remaining_video_timeout_ms(
                deadline,
                stage="opening the video",
            ),
        ),
    )
    _dismiss_consent(page)
    _wait_for_video(
        page,
        min(
            timeout_ms,
            VIDEO_STARTUP_TIMEOUT_SECONDS * 1000,
            _remaining_video_timeout_ms(
                deadline,
                stage="waiting for the main podcast video",
            ),
        ),
        required_seconds=60,
    )
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

    video = page.locator("video").first
    early_bookmark = DescriptionBookmark(
        timestamp_seconds=0,
        label="Early-show sweep",
    )
    early_entries = [
        (second, early_bookmark)
        for second in _early_sweep_seconds(
            duration,
            config.bookmark_sample_every_seconds,
        )
    ]

    print(
        "  Early-show sweep: "
        f"{format_timestamp(EARLY_SWEEP_START_SECONDS)} through "
        f"{format_timestamp(min(EARLY_SWEEP_END_SECONDS, int(duration)))}; "
        f"{len(early_entries)} frame(s)"
    )
    early_hit = _scan_entries_for_match(
        config,
        page,
        video,
        early_entries,
        deadline=deadline,
        timeout_ms=timeout_ms,
        duration=duration,
        scan_label="early-show sweep",
        coarse_mode="full",
    )
    if early_hit is not None:
        print(
            "  YOU ROCK found during early-show sweep; "
            "moving to next video"
        )
        return bookmarks, _save_match(
            config,
            video_id,
            early_hit,
        )

    eligible_bookmarks = [
        bookmark
        for bookmark in bookmarks
        if bookmark.timestamp_seconds >= 60
    ]
    if not eligible_bookmarks:
        print(
            "  No eligible description chapters remained after "
            "the early-show sweep."
        )
        return bookmarks, []

    you_rock_before = max(1, config.bookmark_scan_before_seconds)
    seconds_to_bookmark = _seconds_to_scan(
        eligible_bookmarks,
        before_seconds=you_rock_before,
        sample_every_seconds=config.bookmark_sample_every_seconds,
    )
    early_seconds = {second for second, _ in early_entries}
    chapter_entries = [
        (second, bookmark)
        for second, bookmark in seconds_to_bookmark.items()
        if second not in early_seconds
    ]

    print(
        f"  Description bookmarks: {len(bookmarks)}; "
        f"checking all {len(eligible_bookmarks)} eligible chapter(s); "
        f"scanning {len(chapter_entries)} additional frame(s)"
    )
    chapter_hit = _scan_entries_for_match(
        config,
        page,
        video,
        chapter_entries,
        deadline=deadline,
        timeout_ms=timeout_ms,
        duration=duration,
        scan_label="chapter sweep",
        coarse_mode="standard",
    )
    if chapter_hit is not None:
        print(
            "  YOU ROCK found during chapter sweep; "
            "moving to next video"
        )
        return bookmarks, _save_match(
            config,
            video_id,
            chapter_hit,
        )

    return bookmarks, []


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
@dataclass
class _RawHit:
    timestamp_seconds: int
    bookmark: DescriptionBookmark
    name: str
    confidence: float
    ocr_text: str
    crop: Image.Image

    @property
    def score(self) -> float:
        return self.confidence + (0.25 if self.name else 0.0)


def _early_sweep_seconds(
    duration: float,
    sample_every_seconds: int,
) -> list[int]:
    """Return coarse early-show sample times from 1:00 through 8:00."""
    last_second = min(
        EARLY_SWEEP_END_SECONDS,
        max(0, int(duration) - 1),
    )
    if last_second < EARLY_SWEEP_START_SECONDS:
        return []

    step = max(1, sample_every_seconds)
    return list(
        range(
            EARLY_SWEEP_START_SECONDS,
            last_second + 1,
            step,
        )
    )


def _scan_entries_for_match(
    config: ProjectConfig,
    page: Any,
    video: Any,
    entries: list[tuple[int, DescriptionBookmark]],
    *,
    deadline: float,
    timeout_ms: int,
    duration: float,
    scan_label: str,
    coarse_mode: str,
) -> _FrameAnalysis | None:
    """Return the first refined YOU ROCK match from the supplied entries."""
    for index, (second, bookmark) in enumerate(entries, start=1):
        remaining_ms = _remaining_video_timeout_ms(
            deadline,
            stage=(
                f"{scan_label} at "
                f"{format_timestamp(second)}"
            ),
        )
        _seek_video(
            page,
            float(second),
            timeout_ms=min(timeout_ms, 30_000, remaining_ms),
        )
        page.wait_for_timeout(125)
        image_bytes = video.screenshot(type="jpeg", quality=88)
        analysis = _analyze_frame(
            config,
            image_bytes,
            second,
            bookmark,
            mode=coarse_mode,
        )

        if analysis.has_you_rock:
            refined = _refine_or_use_coarse(
                config,
                page,
                video,
                analysis,
                deadline=deadline,
                timeout_ms=timeout_ms,
                duration=duration,
            )
            print(
                "  YOU ROCK candidate at "
                f"{format_timestamp(refined.timestamp_seconds)}: "
                f"{refined.name or '(name not detected)'} "
                f"({refined.confidence:.3f})"
            )
            return refined

        if index % 60 == 0:
            print(
                f"  Scanned {index}/{len(entries)} "
                f"{scan_label} frame(s)..."
            )

    return None


def _refine_or_use_coarse(
    config: ProjectConfig,
    page: Any,
    video: Any,
    coarse: _FrameAnalysis,
    *,
    deadline: float,
    timeout_ms: int,
    duration: float,
) -> _FrameAnalysis:
    """Refine a hit when time remains, otherwise preserve the coarse hit."""
    try:
        return _refine_you_rock_candidate(
            config,
            page,
            video,
            coarse,
            deadline=deadline,
            timeout_ms=timeout_ms,
            duration=duration,
        )
    except TimeoutError:
        print(
            "  Refinement timed out; saving the detected "
            f"{format_timestamp(coarse.timestamp_seconds)} frame."
        )
        return coarse


def _refine_you_rock_candidate(
    config: ProjectConfig,
    page: Any,
    video: Any,
    coarse: _FrameAnalysis,
    *,
    deadline: float,
    timeout_ms: int,
    duration: float,
) -> _FrameAnalysis:
    """Search plus or minus five seconds and keep the clearest OCR frame."""
    candidates = [coarse]
    start = max(
        1,
        coarse.timestamp_seconds - REFINE_RADIUS_SECONDS,
    )
    end = min(
        max(1, int(duration) - 1),
        coarse.timestamp_seconds + REFINE_RADIUS_SECONDS,
    )

    for second in range(start, end + 1):
        if second == coarse.timestamp_seconds:
            continue

        remaining_ms = _remaining_video_timeout_ms(
            deadline,
            stage=(
                "refining YOU ROCK near "
                f"{format_timestamp(coarse.timestamp_seconds)}"
            ),
        )
        _seek_video(
            page,
            float(second),
            timeout_ms=min(timeout_ms, 30_000, remaining_ms),
        )
        page.wait_for_timeout(125)
        image_bytes = video.screenshot(type="jpeg", quality=92)
        analysis = _analyze_frame(
            config,
            image_bytes,
            second,
            coarse.bookmark,
            mode="multi",
        )
        if analysis.has_you_rock:
            candidates.append(analysis)

    return max(candidates, key=_analysis_score)


def _analysis_score(analysis: _FrameAnalysis) -> float:
    return (
        analysis.confidence
        + (0.75 if analysis.name else 0.0)
        + min(len(analysis.ocr_text), 120) / 1000
    )


def _save_match(
    config: ProjectConfig,
    video_id: str,
    hit: _FrameAnalysis,
) -> list[BookmarkMatch]:
    config.screenshots_dir.mkdir(parents=True, exist_ok=True)
    output_path = (
        config.screenshots_dir
        / f"{video_id}-{hit.timestamp_seconds}-bookmark.jpg"
    )
    hit.crop.save(output_path, format="JPEG", quality=92)

    print(
        "  Confirmed YOU ROCK at "
        f"{format_timestamp(hit.timestamp_seconds)}"
    )
    return [
        BookmarkMatch(
            timestamp_seconds=hit.timestamp_seconds,
            bookmark_seconds=hit.bookmark.timestamp_seconds,
            bookmark_label=hit.bookmark.label,
            name=hit.name,
            confidence=hit.confidence,
            ocr_text=hit.ocr_text,
            screenshot=output_path,
        )
    ]


def _region_crops(
    image: Image.Image,
    config: ProjectConfig,
    mode: str,
) -> list[tuple[str, Image.Image]]:
    """Return OCR regions focused on the lower-third shout-out banner."""
    width = image.width
    height = image.height
    configured_top = max(
        0,
        min(height - 1, int(height * config.crop_top_fraction)),
    )
    banner_top = int(height * 0.62)
    side_top = int(height * 0.50)

    configured = image.crop(
        (0, configured_top, width, height)
    )
    banner = image.crop(
        (0, banner_top, width, height)
    )
    lower_left = image.crop(
        (0, side_top, int(width * 0.72), height)
    )
    lower_right = image.crop(
        (int(width * 0.28), side_top, width, height)
    )

    if mode in {"full", "banner"}:
        return [("banner", banner)]
    if mode == "multi":
        return [
            ("banner", banner),
            ("configured", configured),
            ("lower-left", lower_left),
            ("lower-right", lower_right),
        ]
    return [
        ("configured", configured),
        ("banner", banner),
    ]


def _analyze_frame(
    config: ProjectConfig,
    image_bytes: bytes,
    timestamp_seconds: int,
    bookmark: DescriptionBookmark,
    *,
    mode: str = "standard",
) -> _FrameAnalysis:
    """OCR one or more regions and keep the best YOU ROCK reading."""
    with Image.open(BytesIO(image_bytes)) as image:
        image = image.convert("RGB")
        best: _FrameAnalysis | None = None
        best_hit: _FrameAnalysis | None = None

        for _, crop in _region_crops(image, config, mode):
            processed = _prepare_for_ocr(crop)
            ocr_text, confidence = _ocr(processed)
            has_you_rock = _contains_you_rock(ocr_text)
            analysis = _FrameAnalysis(
                timestamp_seconds=timestamp_seconds,
                bookmark=bookmark,
                name=(
                    parse_name_from_ocr(ocr_text)
                    if has_you_rock
                    else ""
                ),
                confidence=confidence,
                ocr_text=ocr_text,
                crop=crop.copy(),
                has_patreon_url=_contains_patreon_url(ocr_text),
                has_you_rock=has_you_rock,
            )

            if best is None or analysis.confidence > best.confidence:
                best = analysis

            if has_you_rock:
                if (
                    best_hit is None
                    or _analysis_score(analysis)
                    > _analysis_score(best_hit)
                ):
                    best_hit = analysis
                if analysis.name:
                    break

        if best_hit is not None:
            return best_hit
        if best is not None:
            return best

    raise RuntimeError("No OCR regions were produced for the frame.")


def _contains_you_rock(text: str) -> bool:
    """Require a name/banner separator before YOU ROCK.

    This rejects prose such as "show the world just how much YOU ROCK"
    while accepting lower-thirds such as "JEREMY DENNIS - YOU ROCK!!!".
    """
    normalized = " ".join(text.replace("\n", " ").split())
    pattern = (
        r"[A-Z0-9][A-Z0-9'’&+./ _-]{0,80}"
        r"\s*[-–—:|]\s*"
        r"Y[O0]U\s+R[O0]C[KX](?:\s*[!1I|W]*)?"
    )
    return re.search(pattern, normalized, flags=re.IGNORECASE) is not None


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
