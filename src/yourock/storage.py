from __future__ import annotations

import csv
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

VIDEO_FIELDS = [
    "video_id",
    "playlist_index",
    "title",
    "episode_number",
    "published_date",
    "duration_seconds",
    "webpage_url",
    "status",
    "transcript_source",
    "processed_at",
    "candidate_count",
    "last_error",
]

SHOUTOUT_FIELDS = [
    "candidate_id",
    "video_id",
    "episode_number",
    "episode_title",
    "published_date",
    "timestamp_seconds",
    "timestamp_display",
    "matched_phrase",
    "context",
    "name",
    "status",
    "confidence",
    "screenshot",
    "source",
    "created_at",
    "updated_at",
    "notes",
]


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def ensure_data_files(videos_path: Path, shoutouts_path: Path) -> None:
    videos_path.parent.mkdir(parents=True, exist_ok=True)
    shoutouts_path.parent.mkdir(parents=True, exist_ok=True)
    if not videos_path.exists():
        write_rows(videos_path, VIDEO_FIELDS, [])
    if not shoutouts_path.exists():
        write_rows(shoutouts_path, SHOUTOUT_FIELDS, [])


def read_rows(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return [dict(row) for row in csv.DictReader(handle)]


def write_rows(path: Path, fieldnames: list[str], rows: Iterable[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = path.with_suffix(path.suffix + ".tmp")
    with temp_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field, "") for field in fieldnames})
    temp_path.replace(path)


def upsert(rows: list[dict[str, str]], key: str, new_row: dict[str, object]) -> None:
    needle = str(new_row[key])
    for index, row in enumerate(rows):
        if row.get(key) == needle:
            merged = dict(row)
            merged.update({name: str(value) if value is not None else "" for name, value in new_row.items()})
            rows[index] = merged
            return
    rows.append({name: str(value) if value is not None else "" for name, value in new_row.items()})
