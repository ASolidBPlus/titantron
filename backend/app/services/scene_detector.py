from __future__ import annotations

import io
import logging
import math
from typing import Callable

import numpy as np
from PIL import Image, ImageFilter

from app.services.jellyfin_client import JellyfinClient

logger = logging.getLogger(__name__)

# Analysis parameters
THUMB_SIZE = (80, 45)
SCENE_CHANGE_THRESHOLD = 0.15
DARK_FRAME_BRIGHTNESS = 15  # grayscale mean below this = dark frame
MERGE_WINDOW_TICKS = 300_000_000  # 30 seconds in ticks

# Composite weights
W_MAD = 0.40
W_SSIM = 0.30
W_EDGE = 0.20
W_BRIGHTNESS = 0.10


def _to_rgb_array(img: Image.Image) -> np.ndarray:
    """Resize image to THUMB_SIZE and return as float32 RGB array (0-255)."""
    return np.array(img.convert("RGB").resize(THUMB_SIZE, Image.BILINEAR), dtype=np.float32)


def _to_gray_array(img: Image.Image) -> np.ndarray:
    """Resize image to THUMB_SIZE and return as float64 grayscale array (0-255)."""
    return np.array(img.convert("L").resize(THUMB_SIZE, Image.BILINEAR), dtype=np.float64)


def _mean_absolute_difference(a: np.ndarray, b: np.ndarray) -> float:
    """Pixel-level mean absolute difference, normalized to 0.0-1.0."""
    return float(np.mean(np.abs(a - b)) / 255.0)


def _ssim(a: np.ndarray, b: np.ndarray) -> float:
    """Compute SSIM between two grayscale arrays using numpy.

    Returns a value in [-1, 1], typically [0, 1] for natural images.
    """
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
    """Compute edge pixel density using PIL edge filter."""
    gray = img.convert("L").resize(THUMB_SIZE, Image.BILINEAR)
    edges = gray.filter(ImageFilter.FIND_EDGES)
    arr = np.array(edges, dtype=np.float32)
    # Fraction of pixels above edge threshold (50)
    return float(np.mean(arr > 50))


def _analyze_pair(
    prev_img: Image.Image, curr_img: Image.Image
) -> dict:
    """Analyze a pair of adjacent thumbnails and return detection info."""
    # Signal 1: Mean Absolute Difference
    rgb_prev = _to_rgb_array(prev_img)
    rgb_curr = _to_rgb_array(curr_img)
    mad = _mean_absolute_difference(rgb_prev, rgb_curr)

    # Signal 2: SSIM change
    gray_prev = _to_gray_array(prev_img)
    gray_curr = _to_gray_array(curr_img)
    ssim_val = _ssim(gray_prev, gray_curr)
    ssim_change = 1.0 - max(0.0, ssim_val)

    # Signal 3: Dark frame detection
    brightness = float(np.mean(gray_curr))
    is_dark = brightness < DARK_FRAME_BRIGHTNESS

    # Signal 4: Edge density change
    edge_prev = _edge_density(prev_img)
    edge_curr = _edge_density(curr_img)
    edge_change = abs(edge_curr - edge_prev)
    # Normalize edge change (typical range 0-0.3)
    edge_change_norm = min(1.0, edge_change / 0.3)

    # Brightness change (normalized)
    brightness_prev = float(np.mean(gray_prev))
    brightness_change = abs(brightness - brightness_prev) / 255.0

    # Composite score
    composite = (
        W_MAD * mad
        + W_SSIM * ssim_change
        + W_EDGE * edge_change_norm
        + W_BRIGHTNESS * brightness_change
    )

    # Classify detection type
    if is_dark:
        det_type = "dark_frame"
        confidence = 0.9
    elif edge_change_norm > 0.5 and mad < 0.08:
        det_type = "graphics_change"
        confidence = min(1.0, composite / 0.3)
    else:
        det_type = "scene_change"
        confidence = min(1.0, composite / 0.3)

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
    client: JellyfinClient,
    jellyfin_item_id: str,
    trickplay_meta: dict,
    on_progress: Callable[[int, int], None] | None = None,
) -> list[dict]:
    """
    Download trickplay sprite sheets, split into thumbnails,
    compare adjacent frames using multi-signal composite analysis.
    Returns list of detected transitions with timestamps and confidence.
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

        # Extract each thumbnail from the sprite sheet
        thumbs_in_sheet = min(tiles_per_sheet, total_thumbs - sheet_idx * tiles_per_sheet)
        for tile_idx in range(thumbs_in_sheet):
            col = tile_idx % tile_w
            row = tile_idx // tile_w
            x1 = col * thumb_pixel_w
            y1 = row * thumb_pixel_h
            x2 = x1 + thumb_pixel_w
            y2 = y1 + thumb_pixel_h

            thumb = sheet_img.crop((x1, y1, x2, y2))

            if prev_thumb is not None:
                result = _analyze_pair(prev_thumb, thumb)
                if result["is_detection"]:
                    detections.append({
                        "timestamp_ticks": thumb_index * interval * 10_000,
                        "confidence": result["confidence"],
                        "type": result["type"],
                    })

            prev_thumb = thumb
            thumb_index += 1

        # Release the sheet image from memory
        sheet_img.close()

        if on_progress:
            on_progress(sheet_idx + 1, total_sheets)

    # Cluster nearby detections
    detections = _cluster_detections(detections, MERGE_WINDOW_TICKS)

    logger.info(f"Visual analysis complete: {len(detections)} detections found")
    return detections
