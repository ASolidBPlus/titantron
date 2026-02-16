"""HTTP client for the titantron-ml sidecar container."""

from __future__ import annotations

import logging
from typing import Callable

import aiohttp

from app.config import get_setting

logger = logging.getLogger(__name__)

ML_CLASSIFY_TIMEOUT = 1800  # 30 min for ML inference (long videos)


def _get_ml_url() -> str:
    return get_setting("ml_service_url") or ""


async def check_ml_available(url: str | None = None) -> dict:
    """Check if ML container is reachable and model is loaded.

    Returns dict with 'available' and 'model_loaded' keys.
    """
    url = url or _get_ml_url()
    if not url:
        return {"available": False, "model_loaded": False}

    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(
                f"{url}/health",
                timeout=aiohttp.ClientTimeout(total=5),
            ) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    return {
                        "available": data.get("status") == "ready",
                        "model_loaded": data.get("model_loaded", False),
                        "device": data.get("device", "unknown"),
                    }
    except Exception as e:
        logger.debug(f"ML health check failed: {e}")

    return {"available": False, "model_loaded": False}


async def classify_audio(
    ml_file_path: str,
    on_progress: Callable[..., None] | None = None,
) -> dict:
    """Send file path to ML container for audio extraction + classification.

    The ML container handles ffmpeg extraction locally.
    Returns dict with keys: spectrum, detections, window_secs.
    """
    url = _get_ml_url()
    if not url:
        raise RuntimeError("ML service URL not configured")

    window_secs = get_setting("ml_window_secs") or 30

    # Step 1: Send to ML container (it handles extraction + inference)
    if on_progress:
        on_progress(1, 2, "Running audio extraction + ML classification...")

    logger.info(f"Sending classify request to ML service: {ml_file_path}")

    async with aiohttp.ClientSession() as session:
        async with session.post(
            f"{url}/classify",
            json={"file_path": ml_file_path, "window_secs": window_secs},
            timeout=aiohttp.ClientTimeout(total=ML_CLASSIFY_TIMEOUT, sock_read=ML_CLASSIFY_TIMEOUT, sock_connect=30),
        ) as resp:
            if resp.status != 200:
                text = await resp.text()
                raise RuntimeError(f"ML classification failed: HTTP {resp.status} — {text}")
            result = await resp.json()

    # Step 2: Done
    spectrum = result.get("spectrum", [])
    detections = result.get("detections", [])
    window_secs = result.get("window_secs", 30)
    if on_progress:
        on_progress(2, 2, f"ML classification complete: {len(spectrum)} windows, {len(detections)} bell detections")

    logger.info(f"ML classification returned {len(spectrum)} spectrum windows, {len(detections)} bell detections")
    return {"spectrum": spectrum, "detections": detections, "window_secs": window_secs}
