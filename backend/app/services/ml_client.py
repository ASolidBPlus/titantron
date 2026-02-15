"""HTTP client for the titantron-ml sidecar container."""

from __future__ import annotations

import asyncio
import logging
from typing import Callable

import aiohttp

from app.config import get_setting

logger = logging.getLogger(__name__)

TICKS = 10_000_000
ML_SAMPLE_RATE = 32000  # PANNs expects 32kHz
AUDIO_EXTRACT_TIMEOUT = 300  # 5 min for ffmpeg extraction
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
    local_path: str,
    duration_ticks: int,
    on_progress: Callable[[int, int], None] | None = None,
) -> list[dict]:
    """Extract audio via ffmpeg and send to ML container for classification.

    Returns list of detection dicts with timestamp_ticks, confidence, type.
    """
    url = _get_ml_url()
    if not url:
        raise RuntimeError("ML service URL not configured")

    # Step 1: Extract audio to raw PCM float32 mono 32kHz via ffmpeg
    duration_secs = duration_ticks / TICKS if duration_ticks else 0
    total_steps = max(1, int(duration_secs))

    if on_progress:
        on_progress(0, total_steps)

    logger.info(f"Extracting audio from {local_path} (PCM float32 32kHz mono)")

    pcm_data = await _extract_audio(local_path)

    if on_progress:
        on_progress(total_steps // 4, total_steps)

    logger.info(f"Audio extracted: {len(pcm_data) / 1024 / 1024:.1f}MB, sending to ML service")

    # Step 2: POST raw PCM to ML container
    if on_progress:
        on_progress(total_steps // 2, total_steps)

    window_secs = get_setting("ml_window_secs") or 30

    async with aiohttp.ClientSession() as session:
        async with session.post(
            f"{url}/classify?window_secs={window_secs}",
            data=pcm_data,
            headers={"Content-Type": "application/octet-stream"},
            timeout=aiohttp.ClientTimeout(total=ML_CLASSIFY_TIMEOUT, sock_read=ML_CLASSIFY_TIMEOUT, sock_connect=30),
        ) as resp:
            if resp.status != 200:
                text = await resp.text()
                raise RuntimeError(f"ML classification failed: HTTP {resp.status} — {text}")
            result = await resp.json()

    if on_progress:
        on_progress(total_steps, total_steps)

    detections = result.get("detections", [])
    logger.info(f"ML classification returned {len(detections)} detections")
    return detections


async def _extract_audio(local_path: str) -> bytes:
    """Extract audio from video file as raw PCM float32 mono 32kHz."""
    cmd = [
        "ffmpeg",
        "-i", local_path,
        "-vn",                  # no video
        "-ac", "1",             # mono
        "-ar", str(ML_SAMPLE_RATE),  # 32kHz
        "-f", "f32le",          # raw PCM float32 little-endian
        "-acodec", "pcm_f32le",
        "pipe:1",               # output to stdout
    ]

    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )

    stdout, stderr = await asyncio.wait_for(
        proc.communicate(),
        timeout=AUDIO_EXTRACT_TIMEOUT,
    )

    if proc.returncode != 0:
        err_msg = stderr.decode(errors="replace")[-500:]
        raise RuntimeError(f"ffmpeg audio extraction failed (exit {proc.returncode}): {err_msg}")

    if len(stdout) < 4:
        raise RuntimeError("ffmpeg produced no audio data")

    return stdout
