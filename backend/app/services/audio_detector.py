from __future__ import annotations

import asyncio
import logging
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
BELL_ENERGY_THRESHOLD = 2.0  # multiplier over rolling baseline
BELL_SPECTRAL_RATIO = 0.08  # bell band must be this fraction of total FFT energy
BELL_CLUSTER_WINDOW_SECS = 30
BELL_MIN_CLUSTER = 2

# Music detection params
MUSIC_SUB_WINDOW_SECS = 2  # sub-window size for music energy comparison
MUSIC_ENERGY_THRESHOLD = 1.5  # multiplier over rolling baseline
MUSIC_MERGE_WINDOW_TICKS = 300_000_000  # 30 seconds

# Timeout for entire audio analysis pipeline
AUDIO_TIMEOUT_SECONDS = 300  # 5 minutes


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
    samples: np.ndarray, sos: np.ndarray, chunk_offset_secs: float,
    rolling_baseline: float,
) -> tuple[list[dict], int, int]:
    """
    Detect bell-like sounds in a chunk of audio.
    Returns (detections, candidates_found, candidates_passed_spectral).
    """
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
        return [], 0, 0

    baseline = rolling_baseline if rolling_baseline > 0 else float(np.median(energies))
    if baseline == 0:
        return [], 0, 0

    detections = []
    candidates = 0
    passed_spectral = 0

    for i, energy in enumerate(energies):
        ratio = energy / baseline
        if ratio > BELL_ENERGY_THRESHOLD:
            candidates += 1
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

            bell_mask = (freqs >= BELL_LOW_HZ) & (freqs <= BELL_HIGH_HZ)
            if not bell_mask.any():
                continue

            bell_energy = fft_vals[bell_mask].sum()
            total_energy = fft_vals.sum()
            if total_energy == 0:
                continue

            bell_ratio = bell_energy / total_energy
            if bell_ratio < BELL_SPECTRAL_RATIO:
                continue

            passed_spectral += 1
            confidence = min(0.9, (ratio / 8.0) * bell_ratio * 4)
            confidence = max(0.1, confidence)
            detections.append({
                "timestamp_ticks": ticks,
                "confidence": round(confidence, 3),
                "type": "bell",
            })

    return detections, candidates, passed_spectral


def _detect_music_in_chunk(
    samples: np.ndarray, music_baseline: float, chunk_offset_secs: float
) -> tuple[list[dict], float]:
    """
    Detect music starts using 2-second sub-windows compared against a
    rolling baseline. Returns (detections, updated_baseline).
    Timestamps pinpoint the sub-window where energy first spikes.
    """
    sub_window_samples = SAMPLE_RATE * MUSIC_SUB_WINDOW_SECS
    detections = []
    updated_baseline = music_baseline

    for i in range(0, len(samples), sub_window_samples):
        window = samples[i : i + sub_window_samples]
        if len(window) < SAMPLE_RATE:  # skip < 1 second
            break

        window_energy = _rms(window)
        sub_offset_secs = chunk_offset_secs + (i / SAMPLE_RATE)

        if updated_baseline > 0:
            ratio = window_energy / updated_baseline
            if ratio > MUSIC_ENERGY_THRESHOLD:
                # Spectral flatness check on this sub-window
                fft_vals = np.abs(rfft(window.astype(np.float64)))
                if len(fft_vals) > 0:
                    geo_mean = np.exp(np.mean(np.log(fft_vals + 1e-10)))
                    arith_mean = np.mean(fft_vals)
                    flatness = geo_mean / arith_mean if arith_mean > 0 else 0

                    if flatness < 0.6:
                        ticks = int(sub_offset_secs * TICKS_PER_SECOND)
                        confidence = min(0.85, (ratio - MUSIC_ENERGY_THRESHOLD) * 0.3)
                        confidence = max(0.1, confidence)
                        detections.append({
                            "timestamp_ticks": ticks,
                            "confidence": round(confidence, 3),
                            "type": "music_start",
                        })

        # Update rolling baseline (EMA, slow adaptation so music doesn't
        # become the new baseline immediately)
        if updated_baseline == 0:
            updated_baseline = window_energy
        else:
            updated_baseline = 0.05 * window_energy + 0.95 * updated_baseline

    return detections, updated_baseline


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


async def _run_audio_pipeline(
    local_file_path: str,
    duration_ticks: int,
    on_progress: Callable[[int, int], None] | None = None,
) -> list[dict]:
    """Internal pipeline that processes audio from ffmpeg stdout."""
    total_seconds = duration_ticks // TICKS_PER_SECOND
    chunk_bytes = CHUNK_SAMPLES * 2  # 16-bit = 2 bytes per sample

    print(f"[AUDIO] Starting ffmpeg audio extraction: {local_file_path}, {total_seconds}s", flush=True)

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

    # Drain stderr in background to prevent pipe deadlock
    stderr_lines: list[str] = []

    async def _drain_stderr():
        async for line in process.stderr:
            stderr_lines.append(line.decode("utf-8", errors="replace").rstrip())

    stderr_task = asyncio.create_task(_drain_stderr())

    sos = _design_bandpass(BELL_LOW_HZ, BELL_HIGH_HZ, SAMPLE_RATE)
    all_detections: list[dict] = []
    music_baseline = 0.0
    chunk_idx = 0

    # Rolling baseline for bell detection (exponential moving average of bandpass RMS)
    rolling_bell_baseline = 0.0
    ema_alpha = 0.1  # smoothing factor

    total_bell_candidates = 0
    total_bell_passed = 0

    try:
        while True:
            try:
                raw = await process.stdout.readexactly(chunk_bytes)
            except asyncio.IncompleteReadError as e:
                raw = e.partial
                if len(raw) < SAMPLE_RATE * 2:  # less than 1 second
                    break

            samples = np.frombuffer(raw, dtype=np.int16)
            chunk_offset_secs = chunk_idx * CHUNK_SECONDS

            # Update rolling baseline with this chunk's bandpass energy
            filtered = scipy_signal.sosfilt(sos, samples.astype(np.float64))
            chunk_bell_rms = _rms(filtered)
            if rolling_bell_baseline == 0:
                rolling_bell_baseline = chunk_bell_rms
            else:
                rolling_bell_baseline = (
                    ema_alpha * chunk_bell_rms + (1 - ema_alpha) * rolling_bell_baseline
                )

            # Bell detection
            bell_hits, candidates, passed = _detect_bells_in_chunk(
                samples, sos, chunk_offset_secs, rolling_bell_baseline,
            )
            all_detections.extend(bell_hits)
            total_bell_candidates += candidates
            total_bell_passed += passed

            # Music start detection (2-second sub-windows with rolling baseline)
            music_hits, music_baseline = _detect_music_in_chunk(
                samples, music_baseline, chunk_offset_secs
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
        await stderr_task

    print(
        f"[AUDIO] Processed {chunk_idx} chunks ({chunk_idx * CHUNK_SECONDS}s). "
        f"Bell candidates: {total_bell_candidates}, passed spectral: {total_bell_passed}. "
        f"Raw detections: {len(all_detections)}",
        flush=True,
    )

    if process.returncode != 0:
        last_lines = stderr_lines[-5:] if stderr_lines else ["(no stderr)"]
        print(f"[AUDIO] ffmpeg exited with code {process.returncode}: {' | '.join(last_lines)}", flush=True)

    # Cluster and merge detections
    all_detections = _cluster_bell_hits(all_detections)
    all_detections = _cluster_music_detections(all_detections)

    return all_detections


async def detect_audio_events(
    local_file_path: str,
    duration_ticks: int,
    on_progress: Callable[[int, int], None] | None = None,
) -> list[dict]:
    """
    Extract audio from a local video file via ffmpeg and analyze for:
    1. Bell sounds (2-4.5kHz transients)
    2. Music starts (energy spikes)

    Includes a 5-minute timeout to prevent hanging.
    """
    try:
        all_detections = await asyncio.wait_for(
            _run_audio_pipeline(local_file_path, duration_ticks, on_progress),
            timeout=AUDIO_TIMEOUT_SECONDS,
        )
    except asyncio.TimeoutError:
        print(f"[AUDIO] Timed out after {AUDIO_TIMEOUT_SECONDS}s for {local_file_path}", flush=True)
        raise TimeoutError(f"Audio analysis timed out after {AUDIO_TIMEOUT_SECONDS} seconds")

    bells = sum(1 for d in all_detections if d["type"] == "bell")
    music = sum(1 for d in all_detections if d["type"] == "music_start")
    print(f"[AUDIO] Complete: {bells} bells, {music} music starts (after clustering)", flush=True)
    return all_detections
