from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

from PIL import Image, ImageEnhance, ImageOps
import pytesseract
from pytesseract import Output

from .config import ProjectConfig
from .detection import parse_name_from_ocr


@dataclass(frozen=True)
class CaptureResult:
    screenshot: Path
    name: str
    confidence: float
    ocr_text: str


def capture_candidate(
    config: ProjectConfig,
    video_id: str,
    timestamp_seconds: float,
    candidate_id: str,
) -> CaptureResult:
    _require_program("ffmpeg")
    _require_program("tesseract")

    config.screenshots_dir.mkdir(parents=True, exist_ok=True)
    start = max(0, int(timestamp_seconds) - config.seconds_before)
    end = int(timestamp_seconds) + config.seconds_after

    with tempfile.TemporaryDirectory(prefix="yourock-capture-") as temp_dir_text:
        temp_dir = Path(temp_dir_text)
        clip_path = _download_clip(config, video_id, start, end, temp_dir)
        frames_dir = temp_dir / "frames"
        frames_dir.mkdir()
        _extract_frames(clip_path, frames_dir, config.sample_every_seconds)

        best = _choose_best_ocr_frame(config, sorted(frames_dir.glob("*.jpg")))
        if best is None:
            raise RuntimeError("FFmpeg produced no readable frames")

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
        f"https://www.youtube.com/watch?v={video_id}",
    ]
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
            ocr_text, confidence = _ocr(processed, config.ocr_language)
            name = parse_name_from_ocr(ocr_text)
            phrase_bonus = 100.0 if "YOU" in ocr_text.upper() and "ROCK" in ocr_text.upper() else 0.0
            name_bonus = 50.0 if name else 0.0
            score = phrase_bonus + name_bonus + confidence
            if score > best_score:
                best_score = score
                best = (frame_path, crop.copy(), name, confidence / 100.0, ocr_text)

    return best


def _prepare_for_ocr(image: Image.Image) -> Image.Image:
    width = max(1, image.width * 2)
    height = max(1, image.height * 2)
    enlarged = image.resize((width, height), Image.Resampling.LANCZOS)
    gray = ImageOps.grayscale(enlarged)
    gray = ImageOps.autocontrast(gray)
    gray = ImageEnhance.Sharpness(gray).enhance(2.0)
    return gray.point(lambda value: 255 if value >= 115 else 0)


def _ocr(image: Image.Image, language: str) -> tuple[str, float]:
    text = pytesseract.image_to_string(image, lang=language, config="--psm 6")
    data = pytesseract.image_to_data(image, lang=language, config="--psm 6", output_type=Output.DICT)
    confidences: list[float] = []
    for value, token in zip(data.get("conf", []), data.get("text", [])):
        if not str(token).strip():
            continue
        try:
            number = float(value)
        except (TypeError, ValueError):
            continue
        if number >= 0:
            confidences.append(number)
    average = sum(confidences) / len(confidences) if confidences else 0.0
    return text.strip(), average


def _require_program(program: str) -> None:
    if shutil.which(program) is None:
        raise RuntimeError(f"Required program not found on PATH: {program}")
