from __future__ import annotations

import asyncio
import io
import logging
import math
from typing import Callable

import numpy as np
from PIL import Image, ImageFilter

from app.services.jellyfin_client import JellyfinClient

logger = logging.getLogger(__name__)

# Frame extraction parameters
FRAME_RATE = 0.5  # frames per second (1 frame every 2 seconds)
FRAME_SIZE = (160, 90)  # analysis resolution (w, h)
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
VISUAL_TIMEOUT_SECONDS = 600  # 10 minutes


# ---------- numpy-only frame analysis (used by ffmpeg pipeline) ----------

def _gray_from_rgb(rgb: np.ndarray) -> np.ndarray:
    """Convert HxWx3 float32 RGB array to HxW float64 grayscale."""
    return (0.299 * rgb[:, :, 0] + 0.587 * rgb[:, :, 1] + 0.114 * rgb[:, :, 2]).astype(np.float64)


def _edge_density_np(gray: np.ndarray) -> float:
    """Compute edge density using numpy gradients (replaces PIL FIND_EDGES)."""
    gx = np.diff(gray, axis=1)
    gy = np.diff(gray, axis=0)
    min_h = min(gx.shape[0], gy.shape[0])
    min_w = min(gx.shape[1], gy.shape[1])
    magnitude = np.sqrt(gx[:min_h, :min_w] ** 2 + gy[:min_h, :min_w] ** 2)
    return float(np.mean(magnitude > 30))


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


def _compute_frame_data(raw: bytes, w: int, h: int) -> tuple[np.ndarray, np.ndarray, float, float]:
    """
    Compute all per-frame data from raw RGB bytes.
    Returns (rgb_f32, gray_f64, brightness, edge_density).
    """
    rgb = np.frombuffer(raw, dtype=np.uint8).reshape(h, w, 3).astype(np.float32)
    gray = _gray_from_rgb(rgb)
    brightness = float(np.mean(gray))
    edge_dens = _edge_density_np(gray)
    return rgb, gray, brightness, edge_dens


def _compare_frames(
    prev_rgb: np.ndarray, prev_gray: np.ndarray, prev_brightness: float, prev_edge: float,
    curr_rgb: np.ndarray, curr_gray: np.ndarray, curr_brightness: float, curr_edge: float,
) -> dict:
    """Compare two frames using cached per-frame data. Returns detection info."""
    mad = float(np.mean(np.abs(curr_rgb - prev_rgb)) / 255.0)

    ssim_val = _ssim(prev_gray, curr_gray)
    ssim_change = 1.0 - max(0.0, ssim_val)

    edge_change = abs(curr_edge - prev_edge)
    edge_change_norm = min(1.0, edge_change / 0.3)

    brightness_change = abs(curr_brightness - prev_brightness) / 255.0

    composite = (
        W_MAD * mad
        + W_SSIM * ssim_change
        + W_EDGE * edge_change_norm
        + W_BRIGHTNESS * brightness_change
    )

    is_dark = curr_brightness < DARK_FRAME_BRIGHTNESS

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


# ---------- PIL-based frame analysis (used by trickplay fallback) ----------

def _analyze_pair_pil(prev_img: Image.Image, curr_img: Image.Image) -> dict:
    """Analyze a pair of PIL images. Used by trickplay fallback."""
    w, h = FRAME_SIZE
    rgb_prev = np.array(prev_img.convert("RGB").resize(FRAME_SIZE, Image.BILINEAR), dtype=np.float32)
    rgb_curr = np.array(curr_img.convert("RGB").resize(FRAME_SIZE, Image.BILINEAR), dtype=np.float32)
    mad = float(np.mean(np.abs(rgb_prev - rgb_curr)) / 255.0)

    gray_prev = np.array(prev_img.convert("L").resize(FRAME_SIZE, Image.BILINEAR), dtype=np.float64)
    gray_curr = np.array(curr_img.convert("L").resize(FRAME_SIZE, Image.BILINEAR), dtype=np.float64)
    ssim_val = _ssim(gray_prev, gray_curr)
    ssim_change = 1.0 - max(0.0, ssim_val)

    brightness = float(np.mean(gray_curr))
    is_dark = brightness < DARK_FRAME_BRIGHTNESS

    edge_prev_img = prev_img.convert("L").resize(FRAME_SIZE, Image.BILINEAR).filter(ImageFilter.FIND_EDGES)
    edge_curr_img = curr_img.convert("L").resize(FRAME_SIZE, Image.BILINEAR).filter(ImageFilter.FIND_EDGES)
    edge_prev = float(np.mean(np.array(edge_prev_img, dtype=np.float32) > 50))
    edge_curr = float(np.mean(np.array(edge_curr_img, dtype=np.float32) > 50))
    edge_change_norm = min(1.0, abs(edge_curr - edge_prev) / 0.3)

    brightness_prev = float(np.mean(gray_prev))
    brightness_change = abs(brightness - brightness_prev) / 255.0

    composite = (
        W_MAD * mad + W_SSIM * ssim_change
        + W_EDGE * edge_change_norm + W_BRIGHTNESS * brightness_change
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


# ---------- clustering ----------

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


# ---------- ffmpeg pipeline (primary) ----------

async def detect_visual_transitions(
    local_file_path: str,
    duration_ticks: int,
    on_progress: Callable[[int, int], None] | None = None,
) -> list[dict]:
    """
    Extract frames from video via ffmpeg at 0.5fps and compare adjacent
    frames using multi-signal composite analysis.
    """
    total_seconds = duration_ticks // TICKS_PER_SECOND
    expected_frames = int(total_seconds * FRAME_RATE)

    print(
        f"[VISUAL] Starting: {total_seconds}s video, "
        f"~{expected_frames} frames at {FRAME_RATE}fps",
        flush=True,
    )

    try:
        detections = await asyncio.wait_for(
            _run_visual_pipeline(local_file_path, total_seconds, on_progress),
            timeout=VISUAL_TIMEOUT_SECONDS,
        )
    except asyncio.TimeoutError:
        print(f"[VISUAL] Timed out after {VISUAL_TIMEOUT_SECONDS}s", flush=True)
        raise TimeoutError(f"Visual analysis timed out after {VISUAL_TIMEOUT_SECONDS}s")

    detections = _cluster_detections(detections, MERGE_WINDOW_TICKS)
    print(f"[VISUAL] Complete: {len(detections)} detections (after clustering)", flush=True)
    return detections


async def _run_visual_pipeline(
    local_file_path: str,
    total_seconds: int,
    on_progress: Callable[[int, int], None] | None = None,
) -> list[dict]:
    """Extract frames via ffmpeg and analyze adjacent pairs."""
    w, h = FRAME_SIZE
    frame_bytes = w * h * 3  # RGB24

    print(f"[VISUAL] Launching ffmpeg: {local_file_path}", flush=True)

    process = await asyncio.create_subprocess_exec(
        "ffmpeg",
        "-nostdin",
        "-threads", "0",
        "-i", local_file_path,
        "-vf", f"fps={FRAME_RATE},scale={w}:{h}",
        "-pix_fmt", "rgb24",
        "-f", "rawvideo",
        "-nostats",
        "pipe:1",
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )

    # Drain stderr in background to prevent pipe deadlock
    stderr_lines: list[str] = []

    async def _drain_stderr():
        async for line in process.stderr:
            stderr_lines.append(line.decode("utf-8", errors="replace").rstrip())

    stderr_task = asyncio.create_task(_drain_stderr())

    detections: list[dict] = []
    # Cached data for the previous frame: (rgb_f32, gray_f64, brightness, edge_density)
    prev_data: tuple[np.ndarray, np.ndarray, float, float] | None = None
    frame_idx = 0
    seconds_per_frame = 1.0 / FRAME_RATE

    try:
        while True:
            try:
                raw = await process.stdout.readexactly(frame_bytes)
            except asyncio.IncompleteReadError:
                break

            # Compute all per-frame data once (no PIL involved)
            curr_data = _compute_frame_data(raw, w, h)

            if prev_data is not None:
                result = _compare_frames(
                    prev_data[0], prev_data[1], prev_data[2], prev_data[3],
                    curr_data[0], curr_data[1], curr_data[2], curr_data[3],
                )
                if result["is_detection"]:
                    timestamp_secs = frame_idx * seconds_per_frame
                    detections.append({
                        "timestamp_ticks": int(timestamp_secs * TICKS_PER_SECOND),
                        "confidence": result["confidence"],
                        "type": result["type"],
                    })

            prev_data = curr_data
            frame_idx += 1

            if on_progress and total_seconds > 0:
                current_secs = int(frame_idx * seconds_per_frame)
                on_progress(current_secs, total_seconds)
    finally:
        if process.returncode is None:
            process.kill()
        await process.wait()
        await stderr_task

    print(f"[VISUAL] Processed {frame_idx} frames, {len(detections)} raw detections", flush=True)

    if process.returncode != 0:
        last_lines = stderr_lines[-5:] if stderr_lines else ["(no stderr)"]
        print(f"[VISUAL] ffmpeg exit code {process.returncode}: {' | '.join(last_lines)}", flush=True)

    return detections


# ---------- trickplay fallback ----------

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
                result = _analyze_pair_pil(prev_thumb, thumb)
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
