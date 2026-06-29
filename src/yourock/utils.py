from __future__ import annotations

import re


def format_timestamp(value: float | int | str) -> str:
    total = max(0, int(float(value)))
    hours, remainder = divmod(total, 3600)
    minutes, seconds = divmod(remainder, 60)
    if hours:
        return f"{hours}:{minutes:02d}:{seconds:02d}"
    return f"{minutes}:{seconds:02d}"


def extract_episode_number(title: str) -> str:
    patterns = (
        r"\bthe\s+command\s+zone\s*#?\s*(\d{2,4})\b",
        r"\b(?:episode|ep\.?|command\s+zone)\s*#?\s*(\d{2,4})\b",
        r"(?:^|[\s|:-])#(\d{2,4})\b",
    )
    for pattern in patterns:
        match = re.search(pattern, title, flags=re.IGNORECASE)
        if match:
            return match.group(1)
    return ""


def youtube_url(video_id: str, timestamp_seconds: str | int | float | None = None) -> str:
    base = f"https://www.youtube.com/watch?v={video_id}"
    if timestamp_seconds in (None, ""):
        return base
    return f"{base}&t={int(float(timestamp_seconds))}s"


def markdown_escape(value: str) -> str:
    return value.replace("|", "\\|").replace("\n", " ").strip()
