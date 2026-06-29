from pathlib import Path

from yourock.markdown import generate_markdown
from yourock.storage import SHOUTOUT_FIELDS, write_rows


def test_markdown_includes_only_verified(tmp_path: Path):
    csv_path = tmp_path / "shoutouts.csv"
    output_path = tmp_path / "YOU_ROCK.md"
    base = {field: "" for field in SHOUTOUT_FIELDS}
    verified = base | {
        "candidate_id": "one",
        "video_id": "abc",
        "episode_number": "745",
        "episode_title": "Example | The Command Zone 745 | MTG EDH",
        "published_date": "2026-06-28",
        "timestamp_seconds": "65",
        "timestamp_display": "1:05",
        "name": "A Person",
        "status": "verified",
        "screenshot": "screenshots/example.jpg",
    }
    pending = base | {
        "candidate_id": "two",
        "video_id": "def",
        "name": "Pending Person",
        "status": "pending",
    }
    write_rows(csv_path, SHOUTOUT_FIELDS, [verified, pending])
    generate_markdown(csv_path, output_path)
    text = output_path.read_text(encoding="utf-8")

    assert "**1 verified shout-out** across **1 episode**." in text
    assert "<table>" in text
    assert "A Person" in text
    assert "Pending Person" not in text
    assert "#745 — Example" in text
    assert "The Command Zone 745" not in text
    assert "Jun 28, 2026" in text
    assert '<img src="screenshots/example.jpg"' in text
    assert "width=\"300\"" in text
    assert "https://www.youtube.com/watch?v=abc&amp;t=65s" in text
