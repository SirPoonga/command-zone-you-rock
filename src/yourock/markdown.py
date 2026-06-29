from __future__ import annotations

from datetime import date
from html import escape
from pathlib import Path
import re

from .storage import read_rows
from .utils import youtube_url


def generate_markdown(shoutouts_csv: Path, output_path: Path) -> None:
    rows = [row for row in read_rows(shoutouts_csv) if row.get("status") == "verified"]
    rows.sort(key=_sort_key)

    count = len(rows)
    episode_count = len({row.get("video_id", "") for row in rows if row.get("video_id", "")})

    lines = [
        "# The Command Zone ‘You Rock’ Shout-Outs",
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
                "<table>",
                "  <thead>",
                "    <tr>",
                "      <th>Shout-out</th>",
                "      <th>Episode</th>",
                "      <th>Watch</th>",
                "      <th>Proof</th>",
                "    </tr>",
                "  </thead>",
                "  <tbody>",
            ]
        )

        for row in rows:
            video_id = row.get("video_id", "").strip()
            timestamp_seconds = row.get("timestamp_seconds", "0").strip() or "0"
            watch_url = escape(youtube_url(video_id, timestamp_seconds), quote=True)

            name = escape(row.get("name", "").strip() or "Unknown")
            episode_number = row.get("episode_number", "").strip()
            title = escape(_display_title(row.get("episode_title", "").strip()) or video_id)
            episode_label = f"#{escape(episode_number)} — {title}" if episode_number else title
            published = escape(_display_date(row.get("published_date", "").strip()))
            timestamp_display = escape(row.get("timestamp_display", "").strip() or "Watch")

            screenshot = row.get("screenshot", "").strip().replace("\\", "/")
            if screenshot:
                screenshot_attr = escape(screenshot, quote=True)
                alt = escape(f"{row.get('name', '').strip() or 'You Rock'} shout-out", quote=True)
                proof = (
                    f'<a href="{screenshot_attr}">'
                    f'<img src="{screenshot_attr}" alt="{alt}" width="300">'
                    "</a>"
                )
            else:
                proof = "—"

            lines.extend(
                [
                    "    <tr>",
                    f"      <td><strong>{name}</strong></td>",
                    (
                        f'      <td><a href="{watch_url}">{episode_label}</a>'
                        f"<br><sub>{published}</sub></td>"
                    ),
                    f'      <td><a href="{watch_url}"><strong>{timestamp_display}</strong></a></td>',
                    f"      <td>{proof}</td>",
                    "    </tr>",
                ]
            )

        lines.extend(["  </tbody>", "</table>", ""])

    lines.extend(
        [
            "## Data",
            "",
            "The CSV file is the canonical dataset. This page is rebuilt from verified rows after each review change or by running `yourock build`.",
            "",
        ]
    )
    output_path.write_text("\n".join(lines), encoding="utf-8")


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
    if not value:
        return "Date unavailable"
    try:
        parsed = date.fromisoformat(value[:10])
    except ValueError:
        return value
    return f"{parsed.strftime('%b')} {parsed.day}, {parsed.year}"


def _plural(word: str, count: int) -> str:
    return word if count == 1 else f"{word}s"


def _episode_number(row: dict[str, str]) -> int | None:
    """Return a numeric show number, including titles with a blank CSV field."""
    raw = row.get("episode_number", "").strip()
    if raw:
        try:
            return int(raw)
        except ValueError:
            pass

    title = row.get("episode_title", "")
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
    """Sort newest show number first, then timestamp, then name."""
    episode = _episode_number(row)
    episode_rank = -episode if episode is not None else 1_000_000_000
    try:
        timestamp = float(row.get("timestamp_seconds") or 0)
    except ValueError:
        timestamp = 0.0
    return episode_rank, timestamp, row.get("name", "").casefold()
