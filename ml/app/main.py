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

# AudioSet music classes we care about.
# Full AudioSet ontology: https://research.google.com/audioset/ontology/index.html
MUSIC_CLASSES = {
    "Music": 0.4,
    "Musical instrument": 0.4,
    "Singing": 0.4,
    "Song": 0.4,
    "Theme music": 0.35,
}

DEFAULT_WINDOW_SECS = 30
DEFAULT_MERGE_GAP_SECS = 60


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
    Returns JSON with detected music_start events.
    """
    # Stream the body in chunks to handle large files (1GB+)
    chunks = []
    async for chunk in request.stream():
        chunks.append(chunk)
    body = b"".join(chunks)

    if len(body) < 4:
        return {"detections": [], "error": "Empty audio data"}

    window_secs = max(2, min(window_secs, 60))
    merge_gap_secs = max(window_secs * 2, DEFAULT_MERGE_GAP_SECS)

    audio = np.frombuffer(body, dtype=np.float32)
    total_samples = len(audio)
    total_secs = total_samples / SAMPLE_RATE

    logger.info(f"Classifying {total_secs:.1f}s of audio ({len(body) / 1024 / 1024:.1f}MB, {window_secs}s windows)")

    model = _get_model()

    window_samples = window_secs * SAMPLE_RATE

    # Build label index once
    music_indices = {}
    for i, label in enumerate(model.labels):
        if label in MUSIC_CLASSES:
            music_indices[i] = (label, MUSIC_CLASSES[label])

    raw_music_windows: list[dict] = []
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

        # Find best music class above threshold
        best_prob = 0.0
        best_label = ""
        for idx, (label, threshold) in music_indices.items():
            if probs[idx] > threshold and probs[idx] > best_prob:
                best_prob = probs[idx]
                best_label = label

        if best_prob > 0:
            raw_music_windows.append({
                "timestamp_secs": window_start_secs,
                "confidence": float(best_prob),
                "label": best_label,
            })

        offset += window_samples  # non-overlapping
        window_count += 1

    logger.info(f"Inference done: {window_count} windows, {len(raw_music_windows)} music detections")

    # ── Post-processing: merge consecutive music windows ──

    detections: list[dict] = []

    if raw_music_windows:
        raw_music_windows.sort(key=lambda e: e["timestamp_secs"])
        groups: list[list[dict]] = []
        current_group: list[dict] = [raw_music_windows[0]]

        for window in raw_music_windows[1:]:
            if window["timestamp_secs"] - current_group[-1]["timestamp_secs"] <= merge_gap_secs:
                current_group.append(window)
            else:
                groups.append(current_group)
                current_group = [window]
        groups.append(current_group)

        for group in groups:
            best = max(group, key=lambda e: e["confidence"])
            detections.append({
                "timestamp_ticks": int(group[0]["timestamp_secs"] * TICKS),
                "confidence": best["confidence"],
                "type": "music_start",
                "label": best["label"],
            })

    detections.sort(key=lambda d: d["timestamp_ticks"])

    logger.info(f"Final: {len(detections)} music_start detections")

    return {"detections": detections}
