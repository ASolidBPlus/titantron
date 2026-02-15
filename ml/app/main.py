"""Titantron ML sidecar — PANNs CNN14 music detection service."""

from __future__ import annotations

import logging
import sys
import time

import numpy as np
import torch
from fastapi import FastAPI, Request

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

# AudioSet music classes — used for continuous spectrum (no threshold filtering).
MUSIC_CLASSES = {
    "Music",
    "Musical instrument",
    "Singing",
    "Song",
    "Theme music",
}

# Bell classes — discrete events, only emitted above threshold.
BELL_CLASSES = {
    "Bell": 0.30,
    "Cowbell": 0.35,
    "Chime": 0.40,
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


# ── Endpoints ────────────────────────────────────────────────────────────────


@app.get("/health")
async def health():
    return {"status": "ready", "model_loaded": _model_loaded, "device": DEVICE}


@app.post("/classify")
async def classify(request: Request, window_secs: int = DEFAULT_WINDOW_SECS):
    """Classify music events from raw PCM audio data.

    Expects raw PCM float32, mono, 32kHz as the request body.
    Query params:
        window_secs: analysis window size (default 30, use 2-10 for GPU)
    Returns JSON with spectrum (every window) + bell detections.
    """
    # Stream the body in chunks to handle large files (1GB+)
    chunks = []
    async for chunk in request.stream():
        chunks.append(chunk)
    body = b"".join(chunks)

    if len(body) < 4:
        return {"spectrum": [], "detections": [], "window_secs": window_secs}

    window_secs = max(2, min(window_secs, 60))

    audio = np.frombuffer(body, dtype=np.float32)
    total_samples = len(audio)
    total_secs = total_samples / SAMPLE_RATE

    logger.info(f"Classifying {total_secs:.1f}s of audio ({len(body) / 1024 / 1024:.1f}MB, {window_secs}s windows)")

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
