from __future__ import annotations

from datetime import date
from html import escape
from pathlib import Path
import re

from .storage import read_rows
from .utils import extract_episode_number, format_timestamp, markdown_escape, youtube_url


def generate_markdown(
    shoutouts_csv: Path,
    output_path: Path,
    videos_csv: Path | None = None,
) -> None:
    """Regenerate YOU_ROCK.md from verified shout-out rows."""
    video_metadata = _video_metadata_by_id(videos_csv)

    rows = [
        _with_video_fallbacks(row, video_metadata)
        for row in read_rows(shoutouts_csv)
        if row.get("status") == "verified"
    ]
    rows.sort(key=_sort_key)

    count = len(rows)
    episode_count = len({row.get("video_id", "") for row in rows if row.get("video_id", "")})

    lines = [
        "# The Command Zone ?You Rock? Shout-Outs",
        "",
        (
            f"**{count} verified {_plural('shout-out', count)}** across "
            f"**{episode_count} {_plural('episode', episode_count)}**."
        ),
        "",
        "This page is generated from [`data/shoutouts.csv`](data/shoutouts.csv).",
        "",
    ]

    if not rows:
        lines.extend(["> No verified shout-outs yet.", ""])
    else:
        lines.extend(
            [
                "| Shout-out | Episode | Date | Watch | Proof |",
                "|---|---|---|---|---|",
            ]
        )

        for row in rows:
            video_id = row.get("video_id", "").strip()
            timestamp_seconds = row.get("timestamp_seconds", "").strip()
            watch_url = escape(youtube_url(video_id, timestamp_seconds), quote=True)

            name = markdown_escape(row.get("name", "").strip() or "Unknown")
            episode_label = markdown_escape(_episode_label(row, video_id))
            published = markdown_escape(_display_date(row.get("published_date", "").strip()))
            timestamp_display = markdown_escape(_timestamp_display(row))

            screenshot = row.get("screenshot", "").strip().replace("\\", "/")
            if screenshot:
                screenshot_url = escape(screenshot, quote=True)
                alt = escape(f"{row.get('name', '').strip() or 'You Rock'} shout-out", quote=True)
                proof = f"[![{alt}]({screenshot_url})]({watch_url})"
            else:
                proof = "?"

            lines.append(
                f"| {name} | {episode_label} | {published} | "
                f"[{timestamp_display}]({watch_url}) | {proof} |"
            )

        lines.append("")

    lines.extend(
        [
            "## Data",
            "",
            "The CSV file is the canonical dataset.",
            "This page is rebuilt from verified rows after each review change or by running `yourock build`.",
            "",
        ]
    )

    output_path.write_text("\n".join(lines), encoding="utf-8")


def _video_metadata_by_id(videos_csv: Path | None) -> dict[str, dict[str, str]]:
    if not videos_csv or not videos_csv.exists():
        return {}

    return {
        row.get("video_id", "").strip(): row
        for row in read_rows(videos_csv)
        if row.get("video_id", "").strip()
    }


def _with_video_fallbacks(
    row: dict[str, str],
    videos: dict[str, dict[str, str]],
) -> dict[str, str]:
    enriched = dict(row)
    video_id = enriched.get("video_id", "").strip()
    video = videos.get(video_id, {})

    if not enriched.get("published_date", "").strip():
        for field in ("published_date", "upload_date", "published_at", "release_date", "date"):
            value = _normalize_date(video.get(field, ""))
            if value:
                enriched["published_date"] = value
                break

    if not enriched.get("episode_title", "").strip():
        enriched["episode_title"] = video.get("title", "").strip()

    if not enriched.get("episode_number", "").strip():
        enriched["episode_number"] = (
            video.get("episode_number", "").strip()
            or extract_episode_number(enriched.get("episode_title", ""))
        )

    if not enriched.get("timestamp_display", "").strip():
        timestamp_seconds = enriched.get("timestamp_seconds", "").strip()
        if timestamp_seconds:
            try:
                enriched["timestamp_display"] = format_timestamp(timestamp_seconds)
            except (TypeError, ValueError):
                pass

    return enriched


def _episode_label(row: dict[str, str], video_id: str) -> str:
    episode_number = row.get("episode_number", "").strip()
    title = _display_title(row.get("episode_title", "").strip()) or video_id

    if episode_number:
        return f"#{episode_number} ? {title}"

    return title


def _display_title(title: str) -> str:
    if not title:
        return ""

    parts = [part.strip() for part in title.split("|") if part.strip()]
    kept: list[str] = []

    for part in parts:
        if re.search(r"\bthe\s+command\s+zone\b", part, flags=re.IGNORECASE):
            break
        kept.append(part)

    return " | ".join(kept) if kept else parts[0]


def _display_date(value: str) -> str:
    normalized = _normalize_date(value)
    if not normalized:
        return "Date unavailable"

    try:
        parsed = date.fromisoformat(normalized[:10])
    except ValueError:
        return value

    return f"{parsed.strftime('%b')} {parsed.day}, {parsed.year}"


def _normalize_date(value: str) -> str:
    value = str(value or "").strip()

    if not value:
        return ""

    if len(value) == 8 and value.isdigit():
        return f"{value[:4]}-{value[4:6]}-{value[6:8]}"

    if "T" in value:
        value = value.split("T", 1)[0]

    if len(value) >= 10 and re.fullmatch(r"\d{4}-\d{2}-\d{2}", value[:10]):
        return value[:10]

    return ""


def _timestamp_display(row: dict[str, str]) -> str:
    display = row.get("timestamp_display", "").strip()
    if display:
        return display

    timestamp_seconds = row.get("timestamp_seconds", "").strip()
    if timestamp_seconds:
        try:
            return format_timestamp(timestamp_seconds)
        except (TypeError, ValueError):
            pass

    timestamp = row.get("timestamp", "").strip()
    if timestamp:
        return timestamp

    return "Watch"


def _plural(word: str, count: int) -> str:
    return word if count == 1 else f"{word}s"


def _episode_number(row: dict[str, str]) -> int | None:
    raw = row.get("episode_number", "").strip()
    if raw:
        try:
            return int(raw)
        except ValueError:
            pass

    title = row.get("episode_title", "")
    episode = extract_episode_number(title)
    if episode:
        return int(episode)

    for pattern in (
        r"\bThe\s+Command\s+Zone\s*#?\s*(\d{1,4})\b",
        r"\bCommand\s+Zone\s*#?\s*(\d{1,4})\b",
        r"\bEpisode\s*#?\s*(\d{1,4})\b",
    ):
        match = re.search(pattern, title, flags=re.IGNORECASE)
        if match:
            return int(match.group(1))

    return None


def _sort_key(row: dict[str, str]) -> tuple[int, float, str]:
    episode = _episode_number(row)
    episode_rank = -episode if episode is not None else 1_000_000_000

    try:
        timestamp = float(row.get("timestamp_seconds") or 0)
    except ValueError:
        timestamp = 0.0

    return episode_rank, timestamp, row.get("name", "").casefold()
