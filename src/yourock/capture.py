from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
from typing import Any

from PIL import Image, ImageEnhance, ImageOps

from .browser_capture import capture_browser_frames
from .browser_capture import capture_browser_frames
from .browser_capture import capture_browser_frames
from .config import ProjectConfig
from .detection import parse_name_from_ocr


@dataclass(frozen=True)
class CaptureResult:
    screenshot: Path
    name: str
    confidence: float
    ocr_text: str


_OCR_ENGINE: Any | None = None


def capture_candidate(
    config: ProjectConfig,
    video_id: str,
    timestamp_seconds: float,
    candidate_id: str,
    *,
    cookies_from_browser: str | None = None,
    cookies_file: str | None = None,
    backend: str | None = None,
) -> CaptureResult:
    selected_backend = (backend or config.capture_backend or "browser").strip().lower()
    if selected_backend not in {"browser", "yt-dlp"}:
        raise RuntimeError(f"Unknown capture backend: {selected_backend}")
    if selected_backend == "yt-dlp":
        _require_program("ffmpeg")

    config.screenshots_dir.mkdir(parents=True, exist_ok=True)
    start = max(0, int(timestamp_seconds) - config.seconds_before)
    end = int(timestamp_seconds) + config.seconds_after

    with tempfile.TemporaryDirectory(prefix="yourock-capture-") as temp_dir_text:
        temp_dir = Path(temp_dir_text)
        frames_dir = temp_dir / "frames"
        frames_dir.mkdir()
        if selected_backend == "browser":
            frame_paths = capture_browser_frames(
                config,
                video_id,
                timestamp_seconds,
                frames_dir,
            )
        else:
            clip_path = _download_clip(
                config,
                video_id,
                start,
                end,
                temp_dir,
                cookies_from_browser=cookies_from_browser,
                cookies_file=cookies_file,
            )
            _extract_frames(clip_path, frames_dir, config.sample_every_seconds)
            frame_paths = sorted(frames_dir.glob("*.jpg"))

        best = _choose_best_ocr_frame(config, frame_paths)
        if best is None:
            raise RuntimeError("Capture produced no readable frames")

        frame_path, crop, name, confidence, ocr_text = best
        suffix = frame_path.suffix.lower() if frame_path.suffix else ".jpg"
        output_path = config.screenshots_dir / f"{candidate_id}{suffix}"
        crop.save(output_path, quality=90)
        return CaptureResult(
            screenshot=output_path,
            name=name,
            confidence=confidence,
            ocr_text=ocr_text,
        )


def _download_clip(
    config: ProjectConfig,
    video_id: str,
    start: int,
    end: int,
    temp_dir: Path,
    *,
    cookies_from_browser: str | None = None,
    cookies_file: str | None = None,
) -> Path:
    output_template = str(temp_dir / "clip.%(ext)s")
    format_selector = f"best[height<={config.max_height}]/best"
    command = [
        sys.executable,
        "-m",
        "yt_dlp",
        "--no-playlist",
        "--download-sections",
        f"*{start}-{end}",
        "--force-keyframes-at-cuts",
        "-f",
        format_selector,
        "--merge-output-format",
        "mp4",
        "--no-warnings",
        "-o",
        output_template,
    ]

    browser = (cookies_from_browser or config.cookies_from_browser).strip()
    cookie_path_text = (cookies_file or config.cookies_file).strip()
    if browser and cookie_path_text:
        raise RuntimeError(
            "Choose either cookies_from_browser or cookies_file, not both."
        )
    if browser:
        command.extend(["--cookies-from-browser", browser])
    elif cookie_path_text:
        cookie_path = Path(cookie_path_text).expanduser()
        if not cookie_path.is_absolute():
            cookie_path = config.root / cookie_path
        command.extend(["--cookies", str(cookie_path.resolve())])

    command.append(f"https://www.youtube.com/watch?v={video_id}")
    completed = subprocess.run(command, capture_output=True, text=True, check=False)
    candidates = [path for path in temp_dir.glob("clip.*") if path.is_file()]
    if completed.returncode != 0 or not candidates:
        detail = completed.stderr.strip() or completed.stdout.strip()
        raise RuntimeError(detail or "yt-dlp could not download the short review clip")
    return sorted(candidates, key=lambda path: path.stat().st_size, reverse=True)[0]


def _extract_frames(clip_path: Path, frames_dir: Path, every_seconds: int) -> None:
    fps = 1 / max(1, every_seconds)
    command = [
        "ffmpeg",
        "-hide_banner",
        "-loglevel",
        "error",
        "-i",
        str(clip_path),
        "-vf",
        f"fps={fps}",
        "-q:v",
        "2",
        str(frames_dir / "frame-%04d.jpg"),
    ]
    completed = subprocess.run(command, capture_output=True, text=True, check=False)
    if completed.returncode != 0:
        raise RuntimeError(completed.stderr.strip() or "FFmpeg frame extraction failed")


def _choose_best_ocr_frame(
    config: ProjectConfig,
    frame_paths: list[Path],
) -> tuple[Path, Image.Image, str, float, str] | None:
    best: tuple[Path, Image.Image, str, float, str] | None = None
    best_score = -1.0

    for frame_path in frame_paths:
        with Image.open(frame_path) as image:
            image = image.convert("RGB")
            top = int(image.height * config.crop_top_fraction)
            crop = image.crop((0, top, image.width, image.height))
            processed = _prepare_for_ocr(crop)
            ocr_text, confidence = _ocr(processed)
            name = parse_name_from_ocr(ocr_text)
            upper_text = ocr_text.upper()
            phrase_bonus = 1.0 if "YOU" in upper_text and "ROCK" in upper_text else 0.0
            name_bonus = 0.5 if name else 0.0
            score = phrase_bonus + name_bonus + confidence
            if score > best_score:
                best_score = score
                best = (frame_path, crop.copy(), name, confidence, ocr_text)

    return best


def _prepare_for_ocr(image: Image.Image) -> Image.Image:
    width = max(1, image.width * 2)
    height = max(1, image.height * 2)
    enlarged = image.resize((width, height), Image.Resampling.LANCZOS)
    enlarged = ImageOps.autocontrast(enlarged)
    return ImageEnhance.Sharpness(enlarged).enhance(1.5)


def _ocr(image: Image.Image) -> tuple[str, float]:
    import numpy as np

    engine = _get_ocr_engine()
    result = engine(
        np.asarray(image.convert("RGB")),
        use_det=True,
        use_cls=False,
        use_rec=True,
    )
    texts = tuple(getattr(result, "txts", ()) or ())
    scores = tuple(float(value) for value in (getattr(result, "scores", ()) or ()))
    text = " ".join(str(value).strip() for value in texts if str(value).strip())
    confidence = sum(scores) / len(scores) if scores else 0.0
    return text, confidence


def _get_ocr_engine() -> Any:
    global _OCR_ENGINE
    if _OCR_ENGINE is None:
        try:
            from rapidocr import RapidOCR
        except ImportError as exc:
            raise RuntimeError(
                "RapidOCR is not installed. Run: "
                ".\\.venv\\Scripts\\python.exe -m pip install rapidocr onnxruntime"
            ) from exc
        _OCR_ENGINE = RapidOCR(params={"Global.log_level": "error"})
    return _OCR_ENGINE


def _require_program(program: str) -> None:
    if shutil.which(program) is None:
        raise RuntimeError(f"Required program not found on PATH: {program}")
