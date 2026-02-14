from __future__ import annotations

import asyncio
import logging
import struct
from typing import Callable

import numpy as np
from scipy import signal as scipy_signal
from scipy.fft import rfft, rfftfreq

logger = logging.getLogger(__name__)

SAMPLE_RATE = 16000  # 16kHz mono
CHUNK_SECONDS = 10
CHUNK_SAMPLES = SAMPLE_RATE * CHUNK_SECONDS
TICKS_PER_SECOND = 10_000_000

# Bell detection params
BELL_LOW_HZ = 2000
BELL_HIGH_HZ = 4500
BELL_ENERGY_THRESHOLD = 3.0  # multiplier over median
BELL_CLUSTER_WINDOW_SECS = 30  # seconds to look for repeated bell hits
BELL_MIN_CLUSTER = 2  # minimum hits to boost confidence

# Music detection params
MUSIC_ENERGY_THRESHOLD = 2.0  # multiplier over previous window energy
MUSIC_MERGE_WINDOW_TICKS = 300_000_000  # 30 seconds


def _design_bandpass(low_hz: int, high_hz: int, fs: int, order: int = 4):
    """Design a Butterworth bandpass filter."""
    nyq = fs / 2
    low = low_hz / nyq
    high = high_hz / nyq
    return scipy_signal.butter(order, [low, high], btype="band", output="sos")


def _rms(signal_data: np.ndarray) -> float:
    """Compute RMS energy of a signal."""
    if len(signal_data) == 0:
        return 0.0
    return float(np.sqrt(np.mean(signal_data.astype(np.float64) ** 2)))


def _detect_bells_in_chunk(
    samples: np.ndarray, sos: np.ndarray, chunk_offset_secs: float
) -> list[dict]:
    """Detect bell-like sounds in a chunk of audio."""
    # Apply bandpass filter for bell frequency range
    filtered = scipy_signal.sosfilt(sos, samples.astype(np.float64))

    # Compute energy in 0.5-second sub-windows
    sub_window = SAMPLE_RATE // 2  # 0.5 seconds
    energies = []
    for i in range(0, len(filtered), sub_window):
        window = filtered[i : i + sub_window]
        if len(window) > 0:
            energies.append(_rms(window))

    if not energies:
        return []

    median_energy = float(np.median(energies))
    if median_energy == 0:
        return []

    detections = []
    for i, energy in enumerate(energies):
        ratio = energy / median_energy
        if ratio > BELL_ENERGY_THRESHOLD:
            sub_time_secs = chunk_offset_secs + i * 0.5
            ticks = int(sub_time_secs * TICKS_PER_SECOND)

            # Verify spectral peak is in bell range via FFT
            start = i * sub_window
            end = min(start + sub_window, len(samples))
            segment = samples[start:end].astype(np.float64)
            if len(segment) < 256:
                continue

            fft_vals = np.abs(rfft(segment))
            freqs = rfftfreq(len(segment), 1.0 / SAMPLE_RATE)

            # Find peak frequency
            bell_mask = (freqs >= BELL_LOW_HZ) & (freqs <= BELL_HIGH_HZ)
            if not bell_mask.any():
                continue

            bell_energy = fft_vals[bell_mask].sum()
            total_energy = fft_vals.sum()
            if total_energy == 0:
                continue

            bell_ratio = bell_energy / total_energy
            if bell_ratio < 0.15:
                continue

            confidence = min(0.9, (ratio / 10.0) * bell_ratio * 3)
            detections.append({
                "timestamp_ticks": ticks,
                "confidence": round(confidence, 3),
                "type": "bell",
            })

    return detections


def _detect_music_in_chunk(
    samples: np.ndarray, prev_energy: float, chunk_offset_secs: float
) -> tuple[list[dict], float]:
    """Detect music starts by comparing broadband energy to previous chunk."""
    current_energy = _rms(samples)

    detections = []
    if prev_energy > 0:
        ratio = current_energy / prev_energy
        if ratio > MUSIC_ENERGY_THRESHOLD:
            ticks = int(chunk_offset_secs * TICKS_PER_SECOND)

            # Check spectral flatness (music has more harmonic structure)
            fft_vals = np.abs(rfft(samples.astype(np.float64)))
            if len(fft_vals) > 0:
                geo_mean = np.exp(np.mean(np.log(fft_vals + 1e-10)))
                arith_mean = np.mean(fft_vals)
                flatness = geo_mean / arith_mean if arith_mean > 0 else 0

                # Lower flatness = more tonal/musical (not just noise)
                if flatness < 0.5:
                    confidence = min(0.85, (ratio - MUSIC_ENERGY_THRESHOLD) * 0.3)
                    confidence = max(0.1, confidence)
                    detections.append({
                        "timestamp_ticks": ticks,
                        "confidence": round(confidence, 3),
                        "type": "music_start",
                    })

    return detections, current_energy


def _cluster_bell_hits(detections: list[dict]) -> list[dict]:
    """
    Cluster bell hits that occur close together (the "ding ding ding" pattern).
    Boost confidence for clusters with multiple hits.
    """
    if not detections:
        return []

    bells = [d for d in detections if d["type"] == "bell"]
    others = [d for d in detections if d["type"] != "bell"]

    if not bells:
        return others

    bells.sort(key=lambda d: d["timestamp_ticks"])
    clusters: list[list[dict]] = [[bells[0]]]
    for b in bells[1:]:
        if (
            b["timestamp_ticks"] - clusters[-1][-1]["timestamp_ticks"]
            <= BELL_CLUSTER_WINDOW_SECS * TICKS_PER_SECOND
        ):
            clusters[-1].append(b)
        else:
            clusters.append([b])

    result = []
    for cluster in clusters:
        best = max(cluster, key=lambda d: d["confidence"])
        if len(cluster) >= BELL_MIN_CLUSTER:
            # Boost confidence for repeated bell pattern
            best["confidence"] = min(0.95, best["confidence"] + 0.15 * len(cluster))
            best["confidence"] = round(best["confidence"], 3)
        result.append(best)

    return result + others


def _cluster_music_detections(detections: list[dict]) -> list[dict]:
    """Merge nearby music start detections."""
    music = [d for d in detections if d["type"] == "music_start"]
    others = [d for d in detections if d["type"] != "music_start"]

    if not music:
        return others

    music.sort(key=lambda d: d["timestamp_ticks"])
    clusters: list[list[dict]] = [[music[0]]]
    for m in music[1:]:
        if m["timestamp_ticks"] - clusters[-1][-1]["timestamp_ticks"] <= MUSIC_MERGE_WINDOW_TICKS:
            clusters[-1].append(m)
        else:
            clusters.append([m])

    result = []
    for cluster in clusters:
        best = max(cluster, key=lambda d: d["confidence"])
        result.append(best)

    return result + others


async def detect_audio_events(
    local_file_path: str,
    duration_ticks: int,
    on_progress: Callable[[int, int], None] | None = None,
) -> list[dict]:
    """
    Extract audio from a local video file via ffmpeg and analyze for:
    1. Bell sounds (2-4.5kHz transients)
    2. Music starts (energy spikes)
    """
    total_seconds = duration_ticks // TICKS_PER_SECOND

    process = await asyncio.create_subprocess_exec(
        "ffmpeg",
        "-i", local_file_path,
        "-vn",
        "-acodec", "pcm_s16le",
        "-ar", str(SAMPLE_RATE),
        "-ac", "1",
        "-f", "s16le",
        "pipe:1",
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )

    sos = _design_bandpass(BELL_LOW_HZ, BELL_HIGH_HZ, SAMPLE_RATE)
    all_detections: list[dict] = []
    prev_energy = 0.0
    chunk_idx = 0
    bytes_per_sample = 2  # 16-bit signed

    try:
        while True:
            raw = await process.stdout.read(CHUNK_SAMPLES * bytes_per_sample)
            if not raw:
                break

            # Convert raw bytes to numpy array
            n_samples = len(raw) // bytes_per_sample
            samples = np.frombuffer(raw[:n_samples * bytes_per_sample], dtype=np.int16)

            if len(samples) < SAMPLE_RATE:  # Skip very short final chunks
                break

            chunk_offset_secs = chunk_idx * CHUNK_SECONDS

            # Bell detection
            bell_hits = _detect_bells_in_chunk(samples, sos, chunk_offset_secs)
            all_detections.extend(bell_hits)

            # Music start detection
            music_hits, prev_energy = _detect_music_in_chunk(
                samples, prev_energy, chunk_offset_secs
            )
            all_detections.extend(music_hits)

            chunk_idx += 1

            if on_progress and total_seconds > 0:
                processed = min(chunk_idx * CHUNK_SECONDS, total_seconds)
                on_progress(processed, total_seconds)

    finally:
        if process.returncode is None:
            process.kill()
        await process.wait()

    # Cluster and merge detections
    all_detections = _cluster_bell_hits(all_detections)
    all_detections = _cluster_music_detections(all_detections)

    logger.info(
        f"Audio analysis complete: {sum(1 for d in all_detections if d['type'] == 'bell')} bells, "
        f"{sum(1 for d in all_detections if d['type'] == 'music_start')} music starts"
    )
    return all_detections
