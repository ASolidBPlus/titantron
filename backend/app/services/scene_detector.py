from __future__ import annotations

import asyncio
import io
import logging
import math
import traceback
from typing import Callable

import numpy as np
from PIL import Image, ImageFilter

from app.services.jellyfin_client import JellyfinClient

logger = logging.getLogger(__name__)

# Frame extraction parameters
FRAME_RATE = 0.5  # frames per second (1 frame every 2 seconds)
FRAME_SIZE = (160, 90)  # analysis resolution
TICKS_PER_SECOND = 10_000_000

# Detection thresholds (calibrated for 2-second frame intervals)
SCENE_CHANGE_THRESHOLD = 0.12  # composite score above this = scene change
DARK_FRAME_BRIGHTNESS = 15  # grayscale mean below this = dark frame
MERGE_WINDOW_TICKS = 50_000_000  # 5 seconds — merge detections within this window

# Composite weights
W_MAD = 0.45
W_SSIM = 0.35
W_EDGE = 0.10
W_BRIGHTNESS = 0.10

# Timeout for ffmpeg frame extraction
VISUAL_TIMEOUT_SECONDS = 300  # 5 minutes


def _to_rgb_array(img: Image.Image) -> np.ndarray:
    return np.array(img.convert("RGB").resize(FRAME_SIZE, Image.BILINEAR), dtype=np.float32)


def _to_gray_array(img: Image.Image) -> np.ndarray:
    return np.array(img.convert("L").resize(FRAME_SIZE, Image.BILINEAR), dtype=np.float64)


def _mean_absolute_difference(a: np.ndarray, b: np.ndarray) -> float:
    return float(np.mean(np.abs(a - b)) / 255.0)


def _ssim(a: np.ndarray, b: np.ndarray) -> float:
    C1 = (0.01 * 255) ** 2
    C2 = (0.03 * 255) ** 2
    mu_x = np.mean(a)
    mu_y = np.mean(b)
    sig_x_sq = np.var(a)
    sig_y_sq = np.var(b)
    sig_xy = np.mean((a - mu_x) * (b - mu_y))
    numerator = (2 * mu_x * mu_y + C1) * (2 * sig_xy + C2)
    denominator = (mu_x ** 2 + mu_y ** 2 + C1) * (sig_x_sq + sig_y_sq + C2)
    return float(numerator / denominator)


def _edge_density(img: Image.Image) -> float:
    gray = img.convert("L").resize(FRAME_SIZE, Image.BILINEAR)
    edges = gray.filter(ImageFilter.FIND_EDGES)
    arr = np.array(edges, dtype=np.float32)
    return float(np.mean(arr > 50))


def _analyze_pair(prev_img: Image.Image, curr_img: Image.Image) -> dict:
    """Analyze a pair of adjacent frames and return detection info."""
    rgb_prev = _to_rgb_array(prev_img)
    rgb_curr = _to_rgb_array(curr_img)
    mad = _mean_absolute_difference(rgb_prev, rgb_curr)

    gray_prev = _to_gray_array(prev_img)
    gray_curr = _to_gray_array(curr_img)
    ssim_val = _ssim(gray_prev, gray_curr)
    ssim_change = 1.0 - max(0.0, ssim_val)

    brightness = float(np.mean(gray_curr))
    is_dark = brightness < DARK_FRAME_BRIGHTNESS

    edge_prev = _edge_density(prev_img)
    edge_curr = _edge_density(curr_img)
    edge_change = abs(edge_curr - edge_prev)
    edge_change_norm = min(1.0, edge_change / 0.3)

    brightness_prev = float(np.mean(gray_prev))
    brightness_change = abs(brightness - brightness_prev) / 255.0

    composite = (
        W_MAD * mad
        + W_SSIM * ssim_change
        + W_EDGE * edge_change_norm
        + W_BRIGHTNESS * brightness_change
    )

    if is_dark:
        det_type = "dark_frame"
        confidence = 0.9
    elif edge_change_norm > 0.5 and mad < 0.05:
        det_type = "graphics_change"
        confidence = min(1.0, composite / 0.25)
    else:
        det_type = "scene_change"
        confidence = min(1.0, composite / 0.25)

    return {
        "composite": composite,
        "type": det_type,
        "confidence": round(confidence, 3),
        "is_detection": is_dark or composite > SCENE_CHANGE_THRESHOLD,
    }


def _cluster_detections(detections: list[dict], window_ticks: int) -> list[dict]:
    """Merge nearby detections within a time window, keeping the strongest."""
    if not detections:
        return []
    sorted_d = sorted(detections, key=lambda d: d["timestamp_ticks"])
    clusters: list[list[dict]] = [[sorted_d[0]]]
    for d in sorted_d[1:]:
        if d["timestamp_ticks"] - clusters[-1][-1]["timestamp_ticks"] <= window_ticks:
            clusters[-1].append(d)
        else:
            clusters.append([d])
    result = []
    for cluster in clusters:
        best = max(cluster, key=lambda d: d["confidence"])
        result.append(best)
    return result


async def detect_visual_transitions(
    local_file_path: str,
    duration_ticks: int,
    on_progress: Callable[[int, int], None] | None = None,
) -> list[dict]:
    """
    Extract frames from video via ffmpeg at 0.5fps and compare adjacent
    frames using multi-signal composite analysis.
    Returns list of detected transitions with timestamps and confidence.
    """
    total_seconds = duration_ticks // TICKS_PER_SECOND
    expected_frames = int(total_seconds * FRAME_RATE)

    logger.info(
        f"Starting visual analysis: {total_seconds}s video, "
        f"extracting ~{expected_frames} frames at {FRAME_RATE}fps"
    )

    try:
        detections = await asyncio.wait_for(
            _run_visual_pipeline(local_file_path, total_seconds, on_progress),
            timeout=VISUAL_TIMEOUT_SECONDS,
        )
    except asyncio.TimeoutError:
        logger.error(f"Visual analysis timed out after {VISUAL_TIMEOUT_SECONDS}s")
        raise TimeoutError(f"Visual analysis timed out after {VISUAL_TIMEOUT_SECONDS}s")

    # Cluster nearby detections
    detections = _cluster_detections(detections, MERGE_WINDOW_TICKS)

    logger.info(f"Visual analysis complete: {len(detections)} detections found")
    return detections


async def _run_visual_pipeline(
    local_file_path: str,
    total_seconds: int,
    on_progress: Callable[[int, int], None] | None = None,
) -> list[dict]:
    """Extract frames via ffmpeg and analyze adjacent pairs."""
    # ffmpeg: extract frames as JPEG images piped to stdout
    # -vf fps=0.5 extracts 1 frame every 2 seconds
    # Output as raw RGB frames at FRAME_SIZE resolution
    w, h = FRAME_SIZE
    process = await asyncio.create_subprocess_exec(
        "ffmpeg",
        "-i", local_file_path,
        "-vf", f"fps={FRAME_RATE},scale={w}:{h}",
        "-pix_fmt", "rgb24",
        "-f", "rawvideo",
        "pipe:1",
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.DEVNULL,
    )

    frame_bytes = w * h * 3  # RGB24
    detections: list[dict] = []
    prev_img: Image.Image | None = None
    frame_idx = 0
    seconds_per_frame = 1.0 / FRAME_RATE

    try:
        while True:
            raw = await process.stdout.read(frame_bytes)
            if len(raw) < frame_bytes:
                break

            # Convert raw RGB bytes to PIL Image
            img = Image.frombytes("RGB", (w, h), raw)

            if prev_img is not None:
                result = _analyze_pair(prev_img, img)
                if result["is_detection"]:
                    timestamp_secs = frame_idx * seconds_per_frame
                    detections.append({
                        "timestamp_ticks": int(timestamp_secs * TICKS_PER_SECOND),
                        "confidence": result["confidence"],
                        "type": result["type"],
                    })

            prev_img = img
            frame_idx += 1

            if on_progress and total_seconds > 0:
                current_secs = int(frame_idx * seconds_per_frame)
                on_progress(current_secs, total_seconds)
    finally:
        if process.returncode is None:
            process.kill()
        await process.wait()

    logger.info(f"Processed {frame_idx} frames, found {len(detections)} raw detections")
    return detections


async def detect_visual_transitions_trickplay(
    client: JellyfinClient,
    jellyfin_item_id: str,
    trickplay_meta: dict,
    on_progress: Callable[[int, int], None] | None = None,
) -> list[dict]:
    """
    Fallback: use trickplay thumbnails when local file path is not available.
    Less accurate due to 10-second intervals between frames.
    """
    tile_w = trickplay_meta["tile_width"]
    tile_h = trickplay_meta["tile_height"]
    tiles_per_sheet = tile_w * tile_h
    total_thumbs = trickplay_meta["thumbnail_count"]
    interval = trickplay_meta["interval"]
    resolution = trickplay_meta["resolution"]
    sheet_pixel_w = trickplay_meta["width"]
    sheet_pixel_h = trickplay_meta["height"]
    thumb_pixel_w = sheet_pixel_w // tile_w
    thumb_pixel_h = sheet_pixel_h // tile_h

    total_sheets = math.ceil(total_thumbs / tiles_per_sheet)
    detections: list[dict] = []
    prev_thumb: Image.Image | None = None
    thumb_index = 0

    # Use a much higher threshold for trickplay (10-second intervals have high baseline change)
    trickplay_threshold = 0.42

    for sheet_idx in range(total_sheets):
        try:
            data = await client._request_bytes(
                f"/Videos/{jellyfin_item_id}/Trickplay/{resolution}/{sheet_idx}.jpg"
            )
            sheet_img = Image.open(io.BytesIO(data))
        except Exception as e:
            logger.warning(f"Failed to download trickplay sheet {sheet_idx}: {e}")
            thumb_index += tiles_per_sheet
            prev_thumb = None
            continue

        thumbs_in_sheet = min(tiles_per_sheet, total_thumbs - sheet_idx * tiles_per_sheet)
        for tile_idx in range(thumbs_in_sheet):
            col = tile_idx % tile_w
            row = tile_idx // tile_w
            x1 = col * thumb_pixel_w
            y1 = row * thumb_pixel_h

            thumb = sheet_img.crop((x1, y1, x1 + thumb_pixel_w, y1 + thumb_pixel_h))

            if prev_thumb is not None:
                result = _analyze_pair(prev_thumb, thumb)
                if result["is_detection"] or result["composite"] > trickplay_threshold:
                    detections.append({
                        "timestamp_ticks": thumb_index * interval * 10_000,
                        "confidence": result["confidence"],
                        "type": result["type"],
                    })

            prev_thumb = thumb
            thumb_index += 1

        sheet_img.close()

        if on_progress:
            on_progress(sheet_idx + 1, total_sheets)

    detections = _cluster_detections(detections, 300_000_000)  # 30-second window for trickplay

    logger.info(f"Trickplay analysis complete: {len(detections)} detections found")
    return detections
