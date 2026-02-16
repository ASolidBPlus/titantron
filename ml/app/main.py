"""Titantron ML sidecar — PANNs CNN14 music detection service."""

from __future__ import annotations

import asyncio
import logging
import os
import sys
import time

import numpy as np
import torch
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

logging.basicConfig(
    level=logging.INFO,
    format="%(levelname)-5s [%(name)s] %(message)s",
    stream=sys.stderr,
    force=True,
)
logger = logging.getLogger(__name__)

app = FastAPI(title="Titantron ML", version="0.1.0")

# ── Global model state ──────────────────────────────────────────────────────

_model = None
_model_loaded = False

SAMPLE_RATE = 32000  # PANNs expects 32kHz
TICKS = 10_000_000
AUDIO_EXTRACT_TIMEOUT = 300  # 5 min for ffmpeg extraction

# AudioSet music classes — used for continuous spectrum (no threshold filtering).
MUSIC_CLASSES = {
    "Music",
    "Musical instrument",
    "Singing",
    "Song",
    "Theme music",
}

# Bell/ring classes — anything that could be a wrestling ring bell.
# All detected as type "bell" in the output.
BELL_CLASSES = {
    "Bell": 0.20,
    "Church bell": 0.25,
    "Jingle bell": 0.25,
    "Bicycle bell": 0.25,
    "Cowbell": 0.20,
    "Tubular bells": 0.25,
    "Chime": 0.25,
    "Wind chime": 0.30,
    "Gong": 0.20,
    "Cymbal": 0.30,
    "Ding-dong": 0.20,
    "Ding": 0.20,
    "Clang": 0.20,
    "Doorbell": 0.25,
    "Telephone bell ringing": 0.25,
}

DEFAULT_WINDOW_SECS = 30


DEVICE = "cuda" if torch.cuda.is_available() else "cpu"


def _get_model():
    """Lazy-load PANNs AudioTagging model."""
    global _model, _model_loaded
    if _model is None:
        logger.info(f"Loading PANNs CNN14 model on {DEVICE} (first request — may download ~327MB)...")
        t0 = time.time()
        from panns_inference import AudioTagging

        _model = AudioTagging(checkpoint_path=None, device=DEVICE)
        _model_loaded = True
        logger.info(f"Model loaded in {time.time() - t0:.1f}s")
    return _model


async def _extract_audio(file_path: str) -> bytes:
    """Extract audio from video file as raw PCM float32 mono 32kHz."""
    cmd = [
        "ffmpeg",
        "-i", file_path,
        "-vn",                  # no video
        "-ac", "1",             # mono
        "-ar", str(SAMPLE_RATE),  # 32kHz
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


# ── Request models ──────────────────────────────────────────────────────────


class ClassifyRequest(BaseModel):
    file_path: str
    window_secs: int = DEFAULT_WINDOW_SECS


# ── Endpoints ────────────────────────────────────────────────────────────────


@app.get("/health")
async def health():
    return {"status": "ready", "model_loaded": _model_loaded, "device": DEVICE}


@app.post("/classify")
async def classify(body: ClassifyRequest):
    """Classify music events from a video file.

    Extracts audio via ffmpeg, then runs PANNs CNN14 inference.
    Returns JSON with spectrum (every window) + bell detections.
    """
    file_path = body.file_path
    window_secs = max(2, min(body.window_secs, 60))

    # Validate file exists
    if not os.path.isfile(file_path):
        raise HTTPException(status_code=422, detail=f"File not found: {file_path}")

    # Extract audio via ffmpeg
    logger.info(f"Extracting audio from {file_path} (PCM float32 {SAMPLE_RATE}Hz mono)")
    try:
        pcm_data = await _extract_audio(file_path)
    except Exception as e:
        raise HTTPException(status_code=422, detail=f"Audio extraction failed: {e}")

    audio = np.frombuffer(pcm_data, dtype=np.float32)
    total_samples = len(audio)
    total_secs = total_samples / SAMPLE_RATE

    logger.info(f"Classifying {total_secs:.1f}s of audio ({len(pcm_data) / 1024 / 1024:.1f}MB, {window_secs}s windows)")

    model = _get_model()

    window_samples = window_secs * SAMPLE_RATE

    # Build label indices once
    music_indices: list[int] = []
    bell_indices: dict[int, tuple[str, float]] = {}
    for i, label in enumerate(model.labels):
        if label in MUSIC_CLASSES:
            music_indices.append(i)
        if label in BELL_CLASSES:
            bell_indices[i] = (label, BELL_CLASSES[label])

    spectrum: list[dict] = []
    detections: list[dict] = []
    offset = 0
    window_count = 0

    while offset < total_samples:
        end = min(offset + window_samples, total_samples)
        chunk = audio[offset:end]

        # Pad short final chunk
        if len(chunk) < window_samples:
            chunk = np.pad(chunk, (0, window_samples - len(chunk)))

        # PANNs expects (batch, samples) shape
        clipwise_output, _ = model.inference(chunk[np.newaxis, :])
        probs = clipwise_output[0]  # shape: (527,)

        window_start_secs = offset / SAMPLE_RATE

        # Spectrum: max music probability across all music classes
        max_music = float(max(probs[idx] for idx in music_indices)) if music_indices else 0.0
        spectrum.append({"t": round(window_start_secs), "music": round(max_music, 3)})

        # Bell detections: discrete events above threshold
        for idx, (label, threshold) in bell_indices.items():
            if probs[idx] > threshold:
                detections.append({
                    "timestamp_ticks": int(window_start_secs * TICKS),
                    "type": "bell",
                    "confidence": round(float(probs[idx]), 3),
                    "label": label,
                })

        offset += window_samples  # non-overlapping
        window_count += 1

    logger.info(f"Inference done: {window_count} windows, {len(detections)} bell detections")

    return {
        "spectrum": spectrum,
        "detections": detections,
        "window_secs": window_secs,
    }
