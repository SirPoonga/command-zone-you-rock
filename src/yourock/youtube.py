from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from yt_dlp import YoutubeDL


@dataclass(frozen=True)
class PlaylistVideo:
    video_id: str
    playlist_index: int
    title: str
    webpage_url: str
    duration_seconds: int | None = None
    published_date: str = ""


def _quiet_options() -> dict[str, Any]:
    return {
        "quiet": True,
        "no_warnings": True,
        "ignoreerrors": True,
        "skip_download": True,
    }


def list_playlist(playlist_url: str) -> list[PlaylistVideo]:
    options = _quiet_options() | {
        "extract_flat": "in_playlist",
        "playlistend": None,
    }
    with YoutubeDL(options) as downloader:
        info = downloader.extract_info(playlist_url, download=False)

    if not info:
        raise RuntimeError("yt-dlp did not return playlist information")

    videos: list[PlaylistVideo] = []
    for fallback_index, entry in enumerate(info.get("entries") or [], start=1):
        if not entry or not entry.get("id"):
            continue
        video_id = str(entry["id"])
        playlist_index = int(entry.get("playlist_index") or fallback_index)
        videos.append(
            PlaylistVideo(
                video_id=video_id,
                playlist_index=playlist_index,
                title=str(entry.get("title") or ""),
                webpage_url=f"https://www.youtube.com/watch?v={video_id}",
                duration_seconds=_to_int(entry.get("duration")),
                published_date=_normalize_upload_date(entry.get("upload_date")),
            )
        )
    return videos


def fetch_video_metadata(video_id: str) -> PlaylistVideo:
    url = f"https://www.youtube.com/watch?v={video_id}"
    with YoutubeDL(_quiet_options() | {"noplaylist": True}) as downloader:
        info = downloader.extract_info(url, download=False)
    if not info:
        raise RuntimeError(f"yt-dlp did not return metadata for {video_id}")
    return PlaylistVideo(
        video_id=video_id,
        playlist_index=int(info.get("playlist_index") or 0),
        title=str(info.get("title") or ""),
        webpage_url=str(info.get("webpage_url") or url),
        duration_seconds=_to_int(info.get("duration")),
        published_date=_normalize_upload_date(info.get("upload_date")),
    )


def _to_int(value: object) -> int | None:
    try:
        return int(float(value))  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None


def _normalize_upload_date(value: object) -> str:
    text = str(value or "")
    if len(text) == 8 and text.isdigit():
        return f"{text[:4]}-{text[4:6]}-{text[6:]}"
    return text
