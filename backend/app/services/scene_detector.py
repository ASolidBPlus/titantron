from __future__ import annotations

import io
import logging
import math
from typing import Callable

import numpy as np
from PIL import Image

from app.services.jellyfin_client import JellyfinClient

logger = logging.getLogger(__name__)

HISTOGRAM_BINS = 32
SCENE_CHANGE_THRESHOLD = 0.70  # correlation below this = scene change
MERGE_WINDOW_TICKS = 300_000_000  # 30 seconds in ticks


def _compute_histogram(img: Image.Image) -> np.ndarray:
    """Compute normalized HSV histogram for an image."""
    hsv = img.convert("HSV")
    channels = hsv.split()
    histograms = []
    for ch in channels:
        hist = ch.histogram()
        # Bin down from 256 to HISTOGRAM_BINS
        bin_size = 256 // HISTOGRAM_BINS
        binned = [sum(hist[i : i + bin_size]) for i in range(0, 256, bin_size)]
        histograms.extend(binned)
    arr = np.array(histograms, dtype=np.float64)
    total = arr.sum()
    if total > 0:
        arr /= total
    return arr


def _histogram_correlation(h1: np.ndarray, h2: np.ndarray) -> float:
    """Compute Pearson correlation between two histograms."""
    if h1.std() == 0 or h2.std() == 0:
        return 0.0
    return float(np.corrcoef(h1, h2)[0, 1])


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
    compare adjacent frames using color histogram correlation.
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
    prev_hist: np.ndarray | None = None
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
            hist = _compute_histogram(thumb)

            if prev_hist is not None:
                corr = _histogram_correlation(prev_hist, hist)
                if corr < SCENE_CHANGE_THRESHOLD:
                    confidence = min(1.0, max(0.0, 1.0 - corr))
                    detections.append({
                        "timestamp_ticks": thumb_index * interval,
                        "confidence": round(confidence, 3),
                        "type": "scene_change",
                    })

            prev_hist = hist
            thumb_index += 1

        # Release the sheet image from memory
        sheet_img.close()

        if on_progress:
            on_progress(sheet_idx + 1, total_sheets)

    # Cluster nearby detections
    detections = _cluster_detections(detections, MERGE_WINDOW_TICKS)

    logger.info(f"Visual analysis complete: {len(detections)} scene changes detected")
    return detections
