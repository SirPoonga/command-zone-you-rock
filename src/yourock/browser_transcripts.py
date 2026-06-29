from __future__ import annotations

import html
import json
import re
import time
from typing import Any

from .browser_capture import _dismiss_consent, _get_runtime, _wait_for_video
from .config import ProjectConfig
from .transcripts import TranscriptResult, TranscriptSnippet


def fetch_browser_transcript(
    config: ProjectConfig,
    video_id: str,
) -> TranscriptResult:
    runtime = _get_runtime(config)
    page = runtime.page
    timeout_ms = max(30, config.browser_timeout_seconds) * 1000
    page.set_default_timeout(timeout_ms)

    url = f"https://www.youtube.com/watch?v={video_id}&autoplay=1"
    page.goto(url, wait_until="domcontentloaded", timeout=timeout_ms)
    _dismiss_consent(page)
    _wait_for_video(page, timeout_ms, required_seconds=60)
    page.wait_for_timeout(1200)

    tracks = _wait_for_caption_tracks(page, timeout_ms, video_id)
    track_errors: list[str] = []

    for track in _ordered_english_tracks(tracks):
        try:
            snippets = _fetch_track_json3(page, str(track["baseUrl"]))
        except Exception as exc:
            label = track.get("name") or track.get("languageCode") or "unknown"
            track_errors.append(f"{label}: {exc}")
            continue

        if snippets:
            kind = "generated" if track.get("kind") == "asr" else "manual"
            language = track.get("languageCode") or "en"
            source_root = track.get("source") or "player-response"
            return TranscriptResult(
                snippets=snippets,
                source=f"browser-caption-track:{kind}:{language}:{source_root}",
            )

    snippets = _fetch_visible_transcript_panel(page, timeout_ms)
    if snippets:
        return TranscriptResult(snippets=snippets, source="browser-transcript-panel")

    languages = sorted(
        {
            str(track.get("languageCode") or "unknown")
            for track in tracks
        }
    )
    details = [
        f"recursive player-data scan found {len(tracks)} caption track(s)",
        f"languages={','.join(languages) if languages else 'none'}",
    ]
    if track_errors:
        details.append("track fetch errors=" + " | ".join(track_errors[:3]))

    raise RuntimeError(
        "The browser opened the video, but no usable English transcript was retrieved; "
        + "; ".join(details)
    )


def _wait_for_caption_tracks(
    page: Any,
    timeout_ms: int,
    video_id: str,
) -> list[dict[str, Any]]:
    deadline = time.monotonic() + timeout_ms / 1000
    best: list[dict[str, Any]] = []

    while time.monotonic() < deadline:
        _dismiss_consent(page)
        try:
            tracks = page.evaluate(
                r'''(videoId) => {
                    function parseMaybe(value) {
                        if (!value) return null;
                        if (typeof value === 'string') {
                            try { return JSON.parse(value); } catch (_) { return null; }
                        }
                        return value;
                    }

                    function labelText(value) {
                        if (!value) return '';
                        if (typeof value === 'string') return value;
                        if (value.simpleText) return value.simpleText;
                        if (Array.isArray(value.runs)) {
                            return value.runs.map(run => run.text || '').join('');
                        }
                        return '';
                    }

                    function collect(root, source, output, seen) {
                        root = parseMaybe(root);
                        if (!root || typeof root !== 'object' || seen.has(root)) return;
                        seen.add(root);

                        if (Array.isArray(root.captionTracks)) {
                            for (const track of root.captionTracks) {
                                const baseUrl = track?.baseUrl || '';
                                if (!baseUrl) continue;
                                output.push({
                                    baseUrl,
                                    languageCode: track.languageCode || '',
                                    kind: track.kind || '',
                                    name: labelText(track.name),
                                    source,
                                    matchesVideo: baseUrl.includes(`v=${videoId}`)
                                        || baseUrl.includes(`video_id=${videoId}`)
                                });
                            }
                        }

                        if (Array.isArray(root)) {
                            for (const item of root) collect(item, source, output, seen);
                            return;
                        }

                        for (const value of Object.values(root)) {
                            collect(value, source, output, seen);
                        }
                    }

                    const roots = [];
                    const player = document.getElementById('movie_player');
                    if (player && typeof player.getPlayerResponse === 'function') {
                        try { roots.push(['movie_player', player.getPlayerResponse()]); } catch (_) {}
                    }
                    roots.push(['ytInitialPlayerResponse', window.ytInitialPlayerResponse]);
                    roots.push(['ytplayer.player_response', window.ytplayer?.config?.args?.player_response]);
                    roots.push(['ytplayer.raw_player_response', window.ytplayer?.config?.args?.raw_player_response]);
                    roots.push(['ytInitialData', window.ytInitialData]);

                    const found = [];
                    for (const [source, root] of roots) {
                        collect(root, source, found, new WeakSet());
                    }

                    const deduped = [];
                    const seenUrls = new Set();
                    for (const track of found) {
                        if (seenUrls.has(track.baseUrl)) continue;
                        seenUrls.add(track.baseUrl);
                        deduped.push(track);
                    }

                    const matching = deduped.filter(track => track.matchesVideo);
                    return matching.length ? matching : deduped;
                }''',
                video_id,
            )
            if tracks:
                best = list(tracks)
                if any(
                    str(track.get("languageCode") or "").lower().startswith("en")
                    for track in best
                ):
                    return best
        except Exception:
            pass
        page.wait_for_timeout(500)

    return best


def _ordered_english_tracks(
    tracks: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    english = [
        track
        for track in tracks
        if str(track.get("languageCode") or "").lower().startswith("en")
    ]

    def score(track: dict[str, Any]) -> tuple[int, int, int, str]:
        language = str(track.get("languageCode") or "").lower()
        generated = str(track.get("kind") or "").lower() == "asr"
        return (
            0 if track.get("matchesVideo") else 1,
            1 if generated else 0,
            0 if language == "en" else 1,
            str(track.get("name") or ""),
        )

    return sorted(english, key=score)


def _fetch_track_json3(page: Any, base_url: str) -> list[TranscriptSnippet]:
    response = page.evaluate(
        r'''async (baseUrl) => {
            const url = new URL(baseUrl);
            url.searchParams.set('fmt', 'json3');
            const response = await fetch(url.toString(), {
                credentials: 'include',
                cache: 'no-store'
            });
            return {
                ok: response.ok,
                status: response.status,
                contentType: response.headers.get('content-type') || '',
                body: await response.text()
            };
        }''',
        base_url,
    )
    if not response or not response.get("ok"):
        status = response.get("status") if response else "unknown"
        raise RuntimeError(f"caption request failed with HTTP {status}")

    body = response.get("body") or ""
    try:
        data = json.loads(body)
    except json.JSONDecodeError as exc:
        prefix = re.sub(r"\s+", " ", body[:120]).strip()
        raise RuntimeError(f"caption response was not JSON3: {prefix!r}") from exc

    snippets: list[TranscriptSnippet] = []
    for event in data.get("events") or []:
        segments = event.get("segs") or []
        text = "".join(str(segment.get("utf8") or "") for segment in segments)
        text = html.unescape(text).replace("\n", " ")
        text = re.sub(r"\s+", " ", text).strip()
        if not text:
            continue
        start = float(event.get("tStartMs") or 0) / 1000.0
        duration = float(event.get("dDurationMs") or 0) / 1000.0
        snippets.append(
            TranscriptSnippet(text=text, start=start, duration=duration)
        )
    return snippets


def _fetch_visible_transcript_panel(
    page: Any,
    timeout_ms: int,
) -> list[TranscriptSnippet]:
    for selector in (
        "#description-inline-expander #expand",
        "#description #expand",
        "ytd-text-inline-expander #expand",
        "#expand",
    ):
        try:
            expand = page.locator(selector).first
            if expand.count() and expand.is_visible():
                expand.click(timeout=2000)
                page.wait_for_timeout(300)
                break
        except Exception:
            pass

    clicked = False
    selectors = (
        "button[aria-label*='transcript' i]",
        "ytd-video-description-transcript-section-renderer button",
        "yt-button-shape button:has-text('Show transcript')",
        "tp-yt-paper-button:has-text('Show transcript')",
        "button:has-text('Show transcript')",
        "text=/^Show transcript$/i",
    )
    for selector in selectors:
        try:
            button = page.locator(selector).first
            if button.count() and button.is_visible():
                button.click(timeout=3000)
                clicked = True
                page.wait_for_timeout(1000)
                break
        except Exception:
            continue

    if not clicked:
        return []

    try:
        page.locator("ytd-transcript-segment-renderer").first.wait_for(
            state="visible",
            timeout=timeout_ms,
        )
    except Exception:
        return []

    rows = page.evaluate(
        r'''() => Array.from(
            document.querySelectorAll('ytd-transcript-segment-renderer')
        ).map(segment => ({
            timestamp: (segment.querySelector('.segment-timestamp')?.textContent || '').trim(),
            text: (segment.querySelector('.segment-text')?.textContent || '').trim()
        })).filter(row => row.timestamp && row.text)'''
    )

    snippets: list[TranscriptSnippet] = []
    for row in rows or []:
        start = _timestamp_to_seconds(str(row.get("timestamp") or ""))
        text = re.sub(r"\s+", " ", str(row.get("text") or "")).strip()
        if start is None or not text:
            continue
        snippets.append(TranscriptSnippet(text=text, start=start, duration=0.0))
    return snippets


def _timestamp_to_seconds(value: str) -> float | None:
    parts = value.strip().split(":")
    if not parts or not all(part.isdigit() for part in parts):
        return None
    numbers = [int(part) for part in parts]
    if len(numbers) == 2:
        minutes, seconds = numbers
        return float(minutes * 60 + seconds)
    if len(numbers) == 3:
        hours, minutes, seconds = numbers
        return float(hours * 3600 + minutes * 60 + seconds)
    return None
