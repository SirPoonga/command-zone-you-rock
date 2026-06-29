from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
import subprocess
import sys
import tempfile

from youtube_transcript_api import YouTubeTranscriptApi

from .config import ProjectConfig


@dataclass(frozen=True)
class TranscriptSnippet:
    text: str
    start: float
    duration: float


@dataclass(frozen=True)
class TranscriptResult:
    snippets: list[TranscriptSnippet]
    source: str


def fetch_transcript(
    video_id: str,
    *,
    config: ProjectConfig | None = None,
    backend: str = "auto",
) -> TranscriptResult:
    normalized = backend.strip().lower()
    if normalized not in {"auto", "api", "browser"}:
        raise ValueError(f"Unknown transcript backend: {backend}")

    errors: list[str] = []

    if normalized in {"auto", "api"}:
        try:
            result = _fetch_with_transcript_api(video_id)
            if result.snippets:
                return result
        except Exception as exc:
            errors.append(f"youtube-transcript-api: {exc.__class__.__name__}: {exc}")

        try:
            result = _fetch_with_ytdlp(video_id)
            if result.snippets:
                return result
        except Exception as exc:
            errors.append(f"yt-dlp subtitles: {exc.__class__.__name__}: {exc}")

    if normalized in {"auto", "browser"}:
        if config is None:
            errors.append("browser transcript: project configuration was not supplied")
        else:
            try:
                from .browser_transcripts import fetch_browser_transcript

                result = fetch_browser_transcript(config, video_id)
                if result.snippets:
                    return result
            except Exception as exc:
                errors.append(f"browser transcript: {exc.__class__.__name__}: {exc}")

    detail = " | ".join(errors) if errors else "No English transcript found"
    raise RuntimeError(detail)


def _fetch_with_transcript_api(video_id: str) -> TranscriptResult:
    api = YouTubeTranscriptApi()
    transcript_list = api.list(video_id)

    transcript = None
    language_preferences = ["en", "en-US", "en-GB"]
    try:
        transcript = transcript_list.find_manually_created_transcript(language_preferences)
    except Exception:
        try:
            transcript = transcript_list.find_generated_transcript(language_preferences)
        except Exception:
            transcript = transcript_list.find_transcript(language_preferences)

    fetched = transcript.fetch()
    snippets = [
        TranscriptSnippet(text=item.text, start=float(item.start), duration=float(item.duration))
        for item in fetched
        if item.text and item.text.strip()
    ]
    kind = "generated" if transcript.is_generated else "manual"
    return TranscriptResult(snippets=snippets, source=f"youtube-transcript-api:{kind}")


def _fetch_with_ytdlp(video_id: str) -> TranscriptResult:
    url = f"https://www.youtube.com/watch?v={video_id}"
    with tempfile.TemporaryDirectory(prefix="yourock-subs-") as temp_dir:
        output_template = str(Path(temp_dir) / "%(id)s.%(language)s.%(ext)s")
        command = [
            sys.executable,
            "-m",
            "yt_dlp",
            "--no-playlist",
            "--skip-download",
            "--write-subs",
            "--write-auto-subs",
            "--sub-langs",
            "en.*,en",
            "--sub-format",
            "json3",
            "--no-warnings",
            "-o",
            output_template,
            url,
        ]
        completed = subprocess.run(command, capture_output=True, text=True, check=False)
        files = list(Path(temp_dir).glob("*.json3"))
        if not files:
            stderr = completed.stderr.strip() or completed.stdout.strip()
            raise RuntimeError(stderr or "yt-dlp did not produce an English json3 subtitle file")

        chosen = _choose_subtitle_file(files)
        snippets = _parse_json3(chosen)
        return TranscriptResult(snippets=snippets, source=f"yt-dlp:{chosen.name}")


def _choose_subtitle_file(files: list[Path]) -> Path:
    def score(path: Path) -> tuple[int, int, str]:
        name = path.name.lower()
        if ".en.json3" in name:
            priority = 0
        elif ".en-orig.json3" in name:
            priority = 1
        elif ".en-us.json3" in name or ".en-gb.json3" in name:
            priority = 2
        else:
            priority = 3
        return priority, len(name), name

    return sorted(files, key=score)[0]


def _parse_json3(path: Path) -> list[TranscriptSnippet]:
    data = json.loads(path.read_text(encoding="utf-8"))
    snippets: list[TranscriptSnippet] = []
    for event in data.get("events") or []:
        segments = event.get("segs") or []
        text = "".join(str(segment.get("utf8") or "") for segment in segments).strip()
        if not text or text == "\n":
            continue
        start = float(event.get("tStartMs") or 0) / 1000.0
        duration = float(event.get("dDurationMs") or 0) / 1000.0
        snippets.append(TranscriptSnippet(text=text, start=start, duration=duration))
    return snippets
