from __future__ import annotations

from dataclasses import replace
import hashlib
import time

from .bookmark_scan import BookmarkMatch, scan_description_bookmarks
from .config import ProjectConfig
from .detection import Candidate, find_candidates
from .markdown import generate_markdown
from .storage import (
    SHOUTOUT_FIELDS,
    VIDEO_FIELDS,
    ensure_data_files,
    read_rows,
    upsert,
    utc_now,
    write_rows,
)
from .transcripts import fetch_transcript
from .utils import extract_episode_number, format_timestamp
from .youtube import PlaylistVideo, fetch_video_metadata, list_playlist


def scan_playlist(
    config: ProjectConfig,
    *,
    limit: int = 10,
    retry_errors: bool = False,
    rescan_complete: bool = False,
    video_id: str | None = None,
    sleep_seconds: float = 1.0,
    transcript_backend: str = "browser",
) -> tuple[int, int]:
    ensure_data_files(config.videos_csv, config.shoutouts_csv)
    videos = read_rows(config.videos_csv)
    shoutouts = read_rows(config.shoutouts_csv)
    video_by_id = {row.get("video_id", ""): row for row in videos}

    if video_id:
        playlist = [
            PlaylistVideo(
                video_id=video_id,
                playlist_index=0,
                title="",
                webpage_url=f"https://www.youtube.com/watch?v={video_id}",
            )
        ]
    else:
        playlist = list_playlist(config.playlist_url)

    selected: list[PlaylistVideo] = []
    for item in playlist:
        existing = video_by_id.get(item.video_id)
        if existing is None:
            selected.append(item)
            continue
        status = existing.get("status", "")
        if rescan_complete:
            selected.append(item)
        elif retry_errors and status in {"error", "retry"}:
            selected.append(item)

    if limit > 0:
        selected = selected[:limit]

    processed = 0
    candidates_added = 0
    backend = transcript_backend.strip().lower()
    for index, flat_item in enumerate(selected, start=1):
        prior = video_by_id.get(flat_item.video_id)
        if prior:
            flat_item = _merge_existing_row(flat_item, prior)
        print(f"[{index}/{len(selected)}] {flat_item.video_id} {flat_item.title}")
        now = utc_now()
        if backend == "browser":
            metadata = flat_item
        else:
            try:
                metadata = _merge_metadata(flat_item, fetch_video_metadata(flat_item.video_id))
            except Exception as exc:
                metadata = flat_item
                print(f"  Metadata warning: {exc}")

        episode_number = extract_episode_number(metadata.title)
        try:
            if backend == "browser":
                bookmarks, matches = scan_description_bookmarks(config, metadata.video_id)
                added_for_video = _store_bookmark_matches(
                    shoutouts,
                    metadata,
                    episode_number,
                    matches,
                    now,
                    config.dedupe_seconds,
                    config.root,
                )
                source = "description-bookmarks+browser+rapidocr"
                candidate_count = len(matches)
                print(
                    f"  Bookmark scan: {len(bookmarks)} bookmark(s); "
                    f"YOU ROCK matches: {candidate_count}"
                )
            else:
                transcript = fetch_transcript(
                    metadata.video_id,
                    config=config,
                    backend=backend,
                )
                found = find_candidates(
                    transcript.snippets,
                    config.patterns,
                    window_snippets=config.window_snippets,
                    context_before=config.context_before,
                    context_after=config.context_after,
                    dedupe_seconds=config.dedupe_seconds,
                )
                added_for_video = _store_candidates(
                    shoutouts,
                    metadata,
                    episode_number,
                    found,
                    now,
                    config.dedupe_seconds,
                )
                source = transcript.source
                candidate_count = len(found)
                print(f"  Transcript: {source}; candidates: {candidate_count}")

            candidates_added += added_for_video
            _upsert_video(
                videos,
                metadata,
                episode_number,
                status="complete",
                transcript_source=source,
                candidate_count=str(candidate_count),
                error="",
                processed_at=now,
            )
        except Exception as exc:
            _upsert_video(
                videos,
                metadata,
                episode_number,
                status="retry",
                transcript_source="",
                candidate_count="0",
                error=f"{exc.__class__.__name__}: {exc}",
                processed_at=now,
            )
            label = "Bookmark scan" if backend == "browser" else "Transcript"
            print(f"  {label} error: {exc}")

        write_rows(config.videos_csv, VIDEO_FIELDS, videos)
        write_rows(config.shoutouts_csv, SHOUTOUT_FIELDS, shoutouts)
        processed += 1
        if sleep_seconds > 0 and index < len(selected):
            time.sleep(sleep_seconds)

    generate_markdown(config.shoutouts_csv, config.markdown_file)
    return processed, candidates_added


def _merge_existing_row(item: PlaylistVideo, row: dict[str, str]) -> PlaylistVideo:
    try:
        duration = int(float(row.get("duration_seconds") or 0)) or item.duration_seconds
    except ValueError:
        duration = item.duration_seconds
    try:
        playlist_index = int(row.get("playlist_index") or 0) or item.playlist_index
    except ValueError:
        playlist_index = item.playlist_index
    return replace(
        item,
        playlist_index=playlist_index,
        title=item.title or row.get("title", ""),
        webpage_url=item.webpage_url or row.get("webpage_url", ""),
        duration_seconds=item.duration_seconds or duration,
        published_date=item.published_date or row.get("published_date", ""),
    )


def _merge_metadata(flat: PlaylistVideo, full: PlaylistVideo) -> PlaylistVideo:
    return replace(
        full,
        playlist_index=flat.playlist_index or full.playlist_index,
        title=full.title or flat.title,
        webpage_url=full.webpage_url or flat.webpage_url,
        duration_seconds=full.duration_seconds or flat.duration_seconds,
        published_date=full.published_date or flat.published_date,
    )


def _upsert_video(
    rows: list[dict[str, str]],
    item: PlaylistVideo,
    episode_number: str,
    *,
    status: str,
    transcript_source: str,
    candidate_count: str,
    error: str,
    processed_at: str,
) -> None:
    upsert(
        rows,
        "video_id",
        {
            "video_id": item.video_id,
            "playlist_index": item.playlist_index,
            "title": item.title,
            "episode_number": episode_number,
            "published_date": item.published_date,
            "duration_seconds": item.duration_seconds or "",
            "webpage_url": item.webpage_url,
            "status": status,
            "transcript_source": transcript_source,
            "processed_at": processed_at,
            "candidate_count": candidate_count,
            "last_error": error,
        },
    )


def _store_bookmark_matches(
    rows: list[dict[str, str]],
    video: PlaylistVideo,
    episode_number: str,
    matches: list[BookmarkMatch],
    now: str,
    dedupe_seconds: int,
    root,
) -> int:
    added = 0
    for match in matches:
        bookmark_text = format_timestamp(match.bookmark_seconds)
        label = f" — {match.bookmark_label}" if match.bookmark_label else ""
        context = (
            f"Visual YOU ROCK banner detected at {format_timestamp(match.timestamp_seconds)}, "
            f"before description bookmark {bookmark_text}{label}. "
            f"OCR: {match.ocr_text}"
        )
        screenshot = match.screenshot.relative_to(root).as_posix()
        existing = _find_nearby(
            rows,
            video.video_id,
            match.timestamp_seconds,
            dedupe_seconds,
        )
        if existing:
            existing.update(
                {
                    "episode_number": episode_number,
                    "episode_title": video.title,
                    "published_date": video.published_date,
                    "timestamp_seconds": str(match.timestamp_seconds),
                    "timestamp_display": format_timestamp(match.timestamp_seconds),
                    "matched_phrase": "YOU ROCK",
                    "context": context,
                    "confidence": f"{match.confidence:.3f}",
                    "screenshot": screenshot,
                    "source": "description-bookmark+browser+rapidocr",
                    "updated_at": now,
                }
            )
            if match.name and existing.get("status") != "verified":
                existing["name"] = match.name
            continue

        candidate_id = _candidate_id(video.video_id, match.timestamp_seconds)
        rows.append(
            {
                "candidate_id": candidate_id,
                "video_id": video.video_id,
                "episode_number": episode_number,
                "episode_title": video.title,
                "published_date": video.published_date,
                "timestamp_seconds": str(match.timestamp_seconds),
                "timestamp_display": format_timestamp(match.timestamp_seconds),
                "matched_phrase": "YOU ROCK",
                "context": context,
                "name": match.name,
                "status": "pending",
                "confidence": f"{match.confidence:.3f}",
                "screenshot": screenshot,
                "source": "description-bookmark+browser+rapidocr",
                "created_at": now,
                "updated_at": now,
                "notes": "",
            }
        )
        added += 1
    return added


def _store_candidates(
    rows: list[dict[str, str]],
    video: PlaylistVideo,
    episode_number: str,
    candidates: list[Candidate],
    now: str,
    dedupe_seconds: int,
) -> int:
    added = 0
    for candidate in candidates:
        existing = _find_nearby(rows, video.video_id, candidate.timestamp_seconds, dedupe_seconds)
        if existing:
            existing.update(
                {
                    "episode_number": episode_number,
                    "episode_title": video.title,
                    "published_date": video.published_date,
                    "timestamp_display": format_timestamp(candidate.timestamp_seconds),
                    "matched_phrase": candidate.matched_phrase,
                    "context": candidate.context,
                    "updated_at": now,
                }
            )
            continue

        candidate_id = _candidate_id(video.video_id, candidate.timestamp_seconds)
        rows.append(
            {
                "candidate_id": candidate_id,
                "video_id": video.video_id,
                "episode_number": episode_number,
                "episode_title": video.title,
                "published_date": video.published_date,
                "timestamp_seconds": str(int(candidate.timestamp_seconds)),
                "timestamp_display": format_timestamp(candidate.timestamp_seconds),
                "matched_phrase": candidate.matched_phrase,
                "context": candidate.context,
                "name": "",
                "status": "pending",
                "confidence": "",
                "screenshot": "",
                "source": "transcript",
                "created_at": now,
                "updated_at": now,
                "notes": "",
            }
        )
        added += 1
    return added


def _find_nearby(
    rows: list[dict[str, str]],
    video_id: str,
    timestamp_seconds: float,
    tolerance: int,
) -> dict[str, str] | None:
    for row in rows:
        if row.get("video_id") != video_id:
            continue
        try:
            existing = float(row.get("timestamp_seconds") or 0)
        except ValueError:
            continue
        if abs(existing - timestamp_seconds) <= tolerance:
            return row
    return None


def _candidate_id(video_id: str, timestamp_seconds: float) -> str:
    raw = f"{video_id}:{int(timestamp_seconds)}".encode("utf-8")
    digest = hashlib.sha1(raw).hexdigest()[:8]
    return f"{video_id}-{int(timestamp_seconds)}-{digest}"
