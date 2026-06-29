from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import tomllib


@dataclass(frozen=True)
class ProjectConfig:
    root: Path
    playlist_url: str
    data_dir: Path
    screenshots_dir: Path
    markdown_file: Path
    patterns: tuple[str, ...]
    window_snippets: int
    context_before: int
    context_after: int
    dedupe_seconds: int
    seconds_before: int
    seconds_after: int
    sample_every_seconds: int
    max_height: int
    crop_top_fraction: float
    ocr_language: str
    cookies_from_browser: str
    cookies_file: str
    capture_backend: str
    browser_channel: str
    browser_profile_dir: Path
    browser_timeout_seconds: int
    bookmark_scan_before_seconds: int
    bookmark_sample_every_seconds: int

    @property
    def videos_csv(self) -> Path:
        return self.data_dir / "videos.csv"

    @property
    def shoutouts_csv(self) -> Path:
        return self.data_dir / "shoutouts.csv"


def load_config(path: str | Path = "config.toml") -> ProjectConfig:
    config_path = Path(path).resolve()
    with config_path.open("rb") as handle:
        raw = tomllib.load(handle)

    root = config_path.parent
    project = raw["project"]
    detection = raw["detection"]
    capture = raw["capture"]

    return ProjectConfig(
        root=root,
        playlist_url=str(project["playlist_url"]),
        data_dir=root / str(project["data_dir"]),
        screenshots_dir=root / str(project["screenshots_dir"]),
        markdown_file=root / str(project["markdown_file"]),
        patterns=tuple(str(value) for value in detection["patterns"]),
        window_snippets=int(detection["window_snippets"]),
        context_before=int(detection["context_before"]),
        context_after=int(detection["context_after"]),
        dedupe_seconds=int(detection["dedupe_seconds"]),
        seconds_before=int(capture["seconds_before"]),
        seconds_after=int(capture["seconds_after"]),
        sample_every_seconds=int(capture["sample_every_seconds"]),
        max_height=int(capture["max_height"]),
        crop_top_fraction=float(capture["crop_top_fraction"]),
        ocr_language=str(capture["ocr_language"]),
        cookies_from_browser=str(capture.get("cookies_from_browser", "")).strip(),
        cookies_file=str(capture.get("cookies_file", "")).strip(),
        capture_backend=str(capture.get("backend", "browser")).strip().lower(),
        browser_channel=str(capture.get("browser_channel", "chrome")).strip(),
        browser_profile_dir=root / str(capture.get("browser_profile_dir", ".browser-profile")),
        browser_timeout_seconds=int(capture.get("browser_timeout_seconds", 180)),
        bookmark_scan_before_seconds=int(capture.get("bookmark_scan_before_seconds", 30)),
        bookmark_sample_every_seconds=int(capture.get("bookmark_sample_every_seconds", 5)),
    )
