from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from werkzeug.datastructures import MultiDict

from yourock.config import load_config
import yourock.review as review_module
from yourock.storage import SHOUTOUT_FIELDS, read_rows, write_rows


def _row(candidate_id: str, status: str = "pending") -> dict[str, str]:
    row = {field: "" for field in SHOUTOUT_FIELDS}
    row.update(
        {
            "candidate_id": candidate_id,
            "video_id": f"video-{candidate_id}",
            "episode_number": "745",
            "episode_title": "Example episode",
            "timestamp_seconds": "878",
            "timestamp_display": "14:38",
            "name": f"Original {candidate_id}",
            "status": status,
        }
    )
    return row


def test_review_page_uses_one_bulk_form(tmp_path: Path):
    config = replace(
        load_config("config.toml"),
        data_dir=tmp_path / "data",
        screenshots_dir=tmp_path / "screenshots",
        markdown_file=tmp_path / "YOU_ROCK.md",
    )
    write_rows(config.shoutouts_csv, SHOUTOUT_FIELDS, [_row("one"), _row("two")])

    app = review_module.create_app(config)
    response = app.test_client().get("/?status=pending")

    assert response.status_code == 200
    assert response.data.count(b"<form") == 1
    assert b"Save all changes" in response.data
    assert response.data.count(b'name="candidate_id"') == 2


def test_save_all_updates_every_visible_candidate_once(tmp_path: Path, monkeypatch):
    config = replace(
        load_config("config.toml"),
        data_dir=tmp_path / "data",
        screenshots_dir=tmp_path / "screenshots",
        markdown_file=tmp_path / "YOU_ROCK.md",
    )
    write_rows(config.shoutouts_csv, SHOUTOUT_FIELDS, [_row("one"), _row("two")])

    markdown_calls: list[tuple[Path, Path]] = []

    def fake_generate_markdown(csv_path: Path, output_path: Path) -> None:
        markdown_calls.append((csv_path, output_path))
        output_path.write_text("rebuilt", encoding="utf-8")

    monkeypatch.setattr(review_module, "generate_markdown", fake_generate_markdown)

    app = review_module.create_app(config)
    payload = MultiDict(
        [
            ("return_status", "pending"),
            ("candidate_id", "one"),
            ("name", "Alice Example"),
            ("status", "verified"),
            ("notes", "Confirmed"),
            ("candidate_id", "two"),
            ("name", "False Positive"),
            ("status", "rejected"),
            ("notes", "Not a shout-out"),
        ]
    )

    response = app.test_client().post("/save-all", data=payload)

    assert response.status_code == 302
    rows = {row["candidate_id"]: row for row in read_rows(config.shoutouts_csv)}
    assert rows["one"]["name"] == "Alice Example"
    assert rows["one"]["status"] == "verified"
    assert rows["one"]["notes"] == "Confirmed"
    assert rows["two"]["status"] == "rejected"
    assert rows["two"]["notes"] == "Not a shout-out"
    assert len(markdown_calls) == 1
    assert config.markdown_file.read_text(encoding="utf-8") == "rebuilt"
