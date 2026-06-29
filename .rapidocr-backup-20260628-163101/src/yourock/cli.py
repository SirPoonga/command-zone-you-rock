from __future__ import annotations

import argparse
from pathlib import Path
import shutil
import sys

from .capture import capture_candidate
from .config import load_config
from .markdown import generate_markdown
from .review import create_app
from .scanner import scan_playlist
from .storage import SHOUTOUT_FIELDS, ensure_data_files, read_rows, utc_now, write_rows


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="yourock",
        description="Find and catalog The Command Zone You Rock shout-outs.",
    )
    parser.add_argument("--config", default="config.toml", help="Path to config.toml")
    subparsers = parser.add_subparsers(dest="command", required=True)

    scan = subparsers.add_parser("scan", help="Scan unprocessed playlist videos for transcript matches")
    scan.add_argument("--limit", type=int, default=10, help="Maximum videos; 0 means no limit")
    scan.add_argument("--retry-errors", action="store_true", help="Retry videos with prior errors")
    scan.add_argument("--rescan-complete", action="store_true", help="Rescan completed videos")
    scan.add_argument("--video", help="Scan one video ID, including one not currently in the playlist")
    scan.add_argument("--sleep", type=float, default=1.0, help="Delay between videos")

    capture = subparsers.add_parser("capture", help="Capture and OCR pending transcript candidates")
    capture.add_argument("--limit", type=int, default=10, help="Maximum candidates; 0 means no limit")
    capture.add_argument("--candidate", help="Capture one candidate ID")
    capture.add_argument("--all", action="store_true", help="Recapture candidates that already have images")

    subparsers.add_parser("build", help="Regenerate YOU_ROCK.md from verified CSV rows")

    review = subparsers.add_parser("review", help="Open the local browser review application")
    review.add_argument("--host", default="127.0.0.1")
    review.add_argument("--port", type=int, default=5000)
    review.add_argument("--debug", action="store_true")

    subparsers.add_parser("doctor", help="Check required programs and project files")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    config = load_config(args.config)
    ensure_data_files(config.videos_csv, config.shoutouts_csv)

    if args.command == "scan":
        processed, added = scan_playlist(
            config,
            limit=args.limit,
            retry_errors=args.retry_errors,
            rescan_complete=args.rescan_complete,
            video_id=args.video,
            sleep_seconds=args.sleep,
        )
        print(f"Processed {processed} video(s); added {added} candidate(s).")
        return 0

    if args.command == "capture":
        return _capture(config, limit=args.limit, candidate_id=args.candidate, recapture=args.all)

    if args.command == "build":
        generate_markdown(config.shoutouts_csv, config.markdown_file)
        print(f"Wrote {config.markdown_file}")
        return 0

    if args.command == "review":
        app = create_app(config)
        print(f"Review app: http://{args.host}:{args.port}")
        app.run(host=args.host, port=args.port, debug=args.debug)
        return 0

    if args.command == "doctor":
        return _doctor(config)

    return 2


def _capture(config, *, limit: int, candidate_id: str | None, recapture: bool) -> int:
    rows = read_rows(config.shoutouts_csv)
    selected = []
    for row in rows:
        if candidate_id and row.get("candidate_id") != candidate_id:
            continue
        if not candidate_id and row.get("status") != "pending":
            continue
        if not recapture and row.get("screenshot"):
            continue
        selected.append(row)

    if limit > 0:
        selected = selected[:limit]

    failures = 0
    for index, row in enumerate(selected, start=1):
        candidate = row.get("candidate_id", "")
        print(f"[{index}/{len(selected)}] Capturing {candidate}")
        try:
            result = capture_candidate(
                config,
                video_id=row["video_id"],
                timestamp_seconds=float(row["timestamp_seconds"]),
                candidate_id=candidate,
            )
            row["screenshot"] = result.screenshot.relative_to(config.root).as_posix()
            if result.name:
                row["name"] = result.name
            row["confidence"] = f"{result.confidence:.3f}"
            row["source"] = "transcript+ocr"
            row["updated_at"] = utc_now()
            print(f"  OCR name: {result.name or '(not detected)'}; confidence: {result.confidence:.3f}")
        except Exception as exc:
            failures += 1
            print(f"  Capture error: {exc}", file=sys.stderr)
        write_rows(config.shoutouts_csv, SHOUTOUT_FIELDS, rows)

    generate_markdown(config.shoutouts_csv, config.markdown_file)
    print(f"Captured {len(selected) - failures} candidate(s); {failures} failed.")
    return 1 if failures else 0


def _doctor(config) -> int:
    checks = [
        ("ffmpeg", shutil.which("ffmpeg")),
        ("tesseract", shutil.which("tesseract")),
        ("config", Path(config.root / "config.toml") if (config.root / "config.toml").exists() else None),
        ("videos.csv", config.videos_csv if config.videos_csv.exists() else None),
        ("shoutouts.csv", config.shoutouts_csv if config.shoutouts_csv.exists() else None),
    ]
    failed = False
    for name, value in checks:
        status = "OK" if value else "MISSING"
        print(f"{name:14} {status:8} {value or ''}")
        failed = failed or not bool(value)
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
