from __future__ import annotations

import atexit
from dataclasses import dataclass
import os
from pathlib import Path
import shutil
import socket
import subprocess
import time
from typing import Any
from urllib.request import urlopen

from .config import ProjectConfig


@dataclass
class _BrowserRuntime:
    playwright: Any
    browser: Any
    context: Any
    page: Any
    process: subprocess.Popen[Any]
    profile_dir: Path
    channel: str
    port: int


_RUNTIME: _BrowserRuntime | None = None


def capture_browser_frames(
    config: ProjectConfig,
    video_id: str,
    timestamp_seconds: float,
    frames_dir: Path,
) -> list[Path]:
    """Capture rendered YouTube frames from a persistent, interactive Chrome session."""
    runtime = _get_runtime(config)
    page = runtime.page
    timeout_ms = max(30, config.browser_timeout_seconds) * 1000
    page.set_default_timeout(timeout_ms)

    start = max(0, int(timestamp_seconds) - config.seconds_before)
    end = int(timestamp_seconds) + config.seconds_after

    # Open at the beginning of the capture window. Waiting for a duration longer
    # than the requested timestamp prevents a pre-roll ad from being mistaken for
    # the actual podcast video.
    url = f"https://www.youtube.com/watch?v={video_id}&t={start}s&autoplay=1"
    page.goto(url, wait_until="domcontentloaded", timeout=timeout_ms)
    _dismiss_consent(page)
    _wait_for_video(page, timeout_ms, required_seconds=end)
    video = page.locator("video").first
    video.scroll_into_view_if_needed()
    step = max(1, config.sample_every_seconds)
    frame_paths: list[Path] = []

    print(
        f"  Browser capture: {start}s through {end}s "
        f"using {runtime.channel} profile {runtime.profile_dir}"
    )
    for index, second in enumerate(range(start, end + 1, step), start=1):
        _seek_video(page, float(second), timeout_ms=min(timeout_ms, 30_000))
        page.wait_for_timeout(350)
        frame_path = frames_dir / f"frame-{index:04d}-{second}s.jpg"
        video.screenshot(path=str(frame_path), type="jpeg", quality=92)
        frame_paths.append(frame_path)

    return frame_paths


def _get_runtime(config: ProjectConfig) -> _BrowserRuntime:
    global _RUNTIME
    profile_dir = config.browser_profile_dir.resolve()
    channel = (config.browser_channel or "chrome").strip().lower()

    if _RUNTIME is not None:
        if (
            _RUNTIME.profile_dir == profile_dir
            and _RUNTIME.channel == channel
            and _RUNTIME.process.poll() is None
        ):
            return _RUNTIME
        _close_runtime()

    try:
        from playwright.sync_api import sync_playwright
    except ImportError as exc:
        raise RuntimeError(
            "Playwright is not installed. Run: "
            ".\\.venv\\Scripts\\python.exe -m pip install playwright"
        ) from exc

    executable = _find_browser_executable(channel)
    profile_dir.mkdir(parents=True, exist_ok=True)
    port = _unused_local_port()
    command = [
        str(executable),
        f"--remote-debugging-port={port}",
        f"--user-data-dir={profile_dir}",
        "--no-first-run",
        "--no-default-browser-check",
        "--window-size=1600,1000",
        "about:blank",
    ]
    process = subprocess.Popen(command)
    endpoint = f"http://127.0.0.1:{port}"
    playwright = None
    try:
        _wait_for_debug_endpoint(endpoint, process, timeout_seconds=30)
        playwright = sync_playwright().start()
        browser = playwright.chromium.connect_over_cdp(endpoint)
        if not browser.contexts:
            raise RuntimeError("Chrome opened without an accessible browser context")
        context = browser.contexts[0]
        page = context.pages[0] if context.pages else context.new_page()
        try:
            page.set_viewport_size({"width": 1600, "height": 900})
        except Exception:
            pass
    except Exception:
        if playwright is not None:
            try:
                playwright.stop()
            except Exception:
                pass
        if process.poll() is None:
            process.terminate()
        raise

    _RUNTIME = _BrowserRuntime(
        playwright=playwright,
        browser=browser,
        context=context,
        page=page,
        process=process,
        profile_dir=profile_dir,
        channel=channel,
        port=port,
    )
    return _RUNTIME


def _find_browser_executable(channel: str) -> Path:
    normalized = channel.lower()
    if normalized in {"edge", "msedge"}:
        names = ("msedge.exe", "msedge")
        windows_rel = Path("Microsoft/Edge/Application/msedge.exe")
    else:
        names = ("chrome.exe", "chrome", "google-chrome")
        windows_rel = Path("Google/Chrome/Application/chrome.exe")

    for name in names:
        found = shutil.which(name)
        if found:
            return Path(found)

    if os.name == "nt":
        roots = [
            os.environ.get("PROGRAMFILES"),
            os.environ.get("PROGRAMFILES(X86)"),
            os.environ.get("LOCALAPPDATA"),
        ]
        for root in roots:
            if not root:
                continue
            candidate = Path(root) / windows_rel
            if candidate.exists():
                return candidate

    raise RuntimeError(
        f"Could not find the {channel} browser executable. Install Google Chrome "
        "or set browser_channel = \"msedge\" in config.toml."
    )


def _unused_local_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _wait_for_debug_endpoint(
    endpoint: str,
    process: subprocess.Popen[Any],
    *,
    timeout_seconds: int,
) -> None:
    deadline = time.monotonic() + timeout_seconds
    url = f"{endpoint}/json/version"
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise RuntimeError("Chrome exited before remote debugging became available")
        try:
            with urlopen(url, timeout=1) as response:
                if response.status == 200:
                    return
        except Exception:
            time.sleep(0.25)
    raise RuntimeError("Timed out while waiting for Chrome remote debugging")


def _wait_for_video(
    page: Any,
    timeout_ms: int,
    *,
    required_seconds: float,
) -> None:
    deadline = time.monotonic() + timeout_ms / 1000
    prompt_printed = False
    last_state: dict[str, Any] | None = None

    while time.monotonic() < deadline:
        _dismiss_consent(page)
        _skip_visible_ad(page)
        try:
            state = _video_state(page)
            last_state = state
            if state:
                duration = float(state.get("duration", 0) or 0)
                ready_state = int(state.get("readyState", 0) or 0)
                ad_showing = bool(state.get("adShowing", False))

                # A pre-roll ad also uses YouTube's <video> element. Do not accept
                # it as the main video; the real podcast must be long enough to
                # contain the requested timestamp.
                if (
                    not ad_showing
                    and ready_state >= 1
                    and duration > required_seconds + 1
                ):
                    page.locator("video").first.evaluate(
                        """video => {
                            video.muted = true;
                            video.volume = 0;
                        }"""
                    )
                    return

                # Muted playback lets ads finish and helps YouTube initialize the
                # main media stream without triggering autoplay restrictions.
                try:
                    page.locator("video").first.evaluate(
                        """async video => {
                            video.muted = true;
                            video.volume = 0;
                            try { await video.play(); } catch (_) {}
                        }"""
                    )
                except Exception:
                    pass
        except Exception:
            pass

        if not prompt_printed:
            print(
                "  Chrome is open. If YouTube asks for consent, sign-in, or a bot check, "
                "complete it in that window. Pre-roll ads will be allowed to finish."
            )
            prompt_printed = True
        page.wait_for_timeout(1000)

    title = ""
    try:
        title = page.title()
    except Exception:
        pass
    raise RuntimeError(
        "YouTube did not expose the main podcast video before the browser timeout. "
        f"Last page title: {title or '(unknown)'}; video state: {last_state or '(none)'}. "
        "Complete any prompt in Chrome and retry."
    )


def _seek_video(page: Any, seconds: float, timeout_ms: int) -> None:
    video = page.locator("video").first
    state = _video_state(page)
    if not state:
        raise RuntimeError("YouTube video element not found")
    duration = float(state.get("duration", 0) or 0)
    if duration <= seconds:
        raise RuntimeError(
            f"The active video is only {duration:.1f}s long, so it cannot seek to "
            f"{seconds:.1f}s. A pre-roll ad may still be active."
        )

    video.evaluate(
        """async (video, seconds) => {
            video.muted = true;
            video.volume = 0;
            if (typeof video.fastSeek === 'function') {
                try { video.fastSeek(seconds); }
                catch (_) { video.currentTime = seconds; }
            } else {
                video.currentTime = seconds;
            }
            try { await video.play(); } catch (_) {}
        }""",
        seconds,
    )

    deadline = time.monotonic() + timeout_ms / 1000
    last_state: dict[str, Any] | None = None
    while time.monotonic() < deadline:
        state = _video_state(page)
        last_state = state
        if state:
            current = float(state.get("currentTime", -9999) or 0)
            ready_state = int(state.get("readyState", 0) or 0)
            seeking = bool(state.get("seeking", False))
            ad_showing = bool(state.get("adShowing", False))
            if (
                not ad_showing
                and not seeking
                and abs(current - seconds) <= 0.8
                and ready_state >= 2
            ):
                video.evaluate("video => video.pause()")
                return

            # Some YouTube player states pause while data is being fetched. Resume
            # muted playback so the requested frame can become available.
            if bool(state.get("paused", False)):
                try:
                    video.evaluate(
                        """async video => {
                            video.muted = true;
                            try { await video.play(); } catch (_) {}
                        }"""
                    )
                except Exception:
                    pass
        page.wait_for_timeout(150)

    raise RuntimeError(
        f"Timed out while seeking YouTube video to {seconds:.1f}s; "
        f"last video state: {last_state or '(none)'}"
    )


def _video_state(page: Any) -> dict[str, Any] | None:
    return page.evaluate(
        """() => {
            const video = document.querySelector('video');
            if (!video) return null;
            const player = document.querySelector('.html5-video-player');
            return {
                currentTime: Number.isFinite(video.currentTime) ? video.currentTime : 0,
                duration: Number.isFinite(video.duration) ? video.duration : 0,
                readyState: video.readyState,
                networkState: video.networkState,
                paused: video.paused,
                seeking: video.seeking,
                ended: video.ended,
                src: video.currentSrc || '',
                adShowing: Boolean(player && player.classList.contains('ad-showing'))
            };
        }"""
    )


def _skip_visible_ad(page: Any) -> None:
    selectors = (
        "button.ytp-skip-ad-button",
        "button.ytp-ad-skip-button",
        "button.ytp-ad-skip-button-modern",
        ".ytp-ad-skip-button",
    )
    for selector in selectors:
        try:
            button = page.locator(selector).first
            if button.count() and button.is_visible():
                button.click(timeout=1500)
                page.wait_for_timeout(300)
                return
        except Exception:
            continue


def _dismiss_consent(page: Any) -> None:
    for label in ("Accept all", "Reject all", "I agree"):
        try:
            button = page.get_by_role("button", name=label, exact=True)
            if button.count() and button.first.is_visible():
                button.first.click(timeout=2000)
                page.wait_for_timeout(500)
                return
        except Exception:
            continue


def _close_runtime() -> None:
    global _RUNTIME
    runtime = _RUNTIME
    _RUNTIME = None
    if runtime is None:
        return
    try:
        runtime.browser.close()
    except Exception:
        pass
    try:
        runtime.playwright.stop()
    except Exception:
        pass
    if runtime.process.poll() is None:
        try:
            runtime.process.terminate()
            runtime.process.wait(timeout=5)
        except Exception:
            try:
                runtime.process.kill()
            except Exception:
                pass


atexit.register(_close_runtime)
