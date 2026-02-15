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

# Bell detection params — narrower band centered on wrestling bell fundamentals
BELL_LOW_HZ = 2500
BELL_HIGH_HZ = 4000
BELL_ENERGY_THRESHOLD = 2.0  # multiplier over rolling baseline
BELL_SPECTRAL_RATIO = 0.06  # bell band fraction of total FFT energy
BELL_ONSET_RATIO = 3.0  # energy rise between adjacent micro-windows
BELL_CLUSTER_WINDOW_SECS = 30
BELL_MIN_CLUSTER = 2

# Music detection params
MUSIC_SUB_WINDOW_SECS = 2  # sub-window size for comparisons
MUSIC_ENERGY_THRESHOLD = 1.4  # multiplier over rolling baseline
MUSIC_SPECTRAL_FLUX_THRESHOLD = 0.3  # normalized spectral flux threshold
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


def _spectral_flux(prev_spectrum: np.ndarray, curr_spectrum: np.ndarray) -> float:
    """
    Compute spectral flux — sum of positive differences in magnitude spectrum.
    High flux = new frequency content appeared (e.g. music started).
    Normalized by number of bins.
    """
    diff = curr_spectrum - prev_spectrum
    positive_diff = np.maximum(diff, 0)
    norm = np.sum(curr_spectrum) + 1e-10
    return float(np.sum(positive_diff) / norm)


def _has_spectral_peaks(fft_vals: np.ndarray, freqs: np.ndarray,
                         low_hz: float, high_hz: float) -> tuple[bool, float]:
    """
    Check for distinct spectral peaks in a frequency band.
    Returns (has_peaks, peak_prominence).
    A bell produces clear narrow peaks; broadband noise doesn't.
    """
    mask = (freqs >= low_hz) & (freqs <= high_hz)
    if not mask.any():
        return False, 0.0

    band_vals = fft_vals[mask]
    if len(band_vals) < 5:
        return False, 0.0

    # Find local maxima
    band_mean = np.mean(band_vals)
    if band_mean == 0:
        return False, 0.0

    # Peak = any bin that's 2x the band mean
    peaks = band_vals > (band_mean * 2.0)
    if not peaks.any():
        return False, 0.0

    # Prominence: ratio of max peak to band mean
    prominence = float(np.max(band_vals) / band_mean)
    return True, prominence


def _detect_bells_in_chunk(
    samples: np.ndarray, sos: np.ndarray, chunk_offset_secs: float,
    rolling_baseline: float,
) -> tuple[list[dict], int, int]:
    """
    Detect bell-like sounds using:
    1. Bandpass energy spike over rolling baseline
    2. Onset detection (sharp energy rise in micro-windows)
    3. Spectral peak verification (narrow peaks, not broadband noise)
    """
    filtered = scipy_signal.sosfilt(sos, samples.astype(np.float64))

    # Compute energy in 0.5-second sub-windows
    sub_window = SAMPLE_RATE // 2  # 0.5 seconds = 8000 samples
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

    # Also compute micro-window energies (50ms) for onset detection
    micro_window = SAMPLE_RATE // 20  # 50ms = 800 samples
    micro_energies = []
    for i in range(0, len(filtered), micro_window):
        window = filtered[i : i + micro_window]
        if len(window) >= micro_window // 2:
            micro_energies.append(_rms(window))

    detections = []
    candidates = 0
    passed_spectral = 0

    for i, energy in enumerate(energies):
        ratio = energy / baseline
        if ratio > BELL_ENERGY_THRESHOLD:
            candidates += 1
            sub_time_secs = chunk_offset_secs + i * 0.5

            # Onset check: look at micro-windows within this sub-window
            # A bell has a sharp attack — energy rises quickly in <100ms
            micro_start = i * 10  # 0.5s / 0.05s = 10 micro-windows per sub-window
            has_onset = False
            for j in range(micro_start + 1, min(micro_start + 10, len(micro_energies))):
                if micro_energies[j - 1] > 0:
                    onset_ratio = micro_energies[j] / micro_energies[j - 1]
                    if onset_ratio > BELL_ONSET_RATIO:
                        has_onset = True
                        break
                elif micro_energies[j] > baseline * 0.5:
                    # Previous micro-window was near-silent, current has energy
                    has_onset = True
                    break

            # FFT spectral verification
            start = i * sub_window
            end = min(start + sub_window, len(samples))
            segment = samples[start:end].astype(np.float64)
            if len(segment) < 256:
                continue

            fft_vals = np.abs(rfft(segment))
            freqs = rfftfreq(len(segment), 1.0 / SAMPLE_RATE)

            # Check bell band energy ratio
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

            # Check for distinct spectral peaks (not just broadband energy)
            has_peaks, prominence = _has_spectral_peaks(
                fft_vals, freqs, BELL_LOW_HZ, BELL_HIGH_HZ
            )

            # Score: combine energy ratio, onset, peak prominence
            score = ratio / 8.0  # base score from energy
            if has_onset:
                score *= 1.5  # boost for sharp transient
            if has_peaks and prominence > 3.0:
                score *= 1.3  # boost for clear spectral peaks

            # Require at least one of: onset or spectral peaks
            if not has_onset and not has_peaks:
                continue

            passed_spectral += 1
            ticks = int(sub_time_secs * TICKS_PER_SECOND)
            confidence = min(0.9, score * bell_ratio * 4)
            confidence = max(0.1, confidence)
            detections.append({
                "timestamp_ticks": ticks,
                "confidence": round(confidence, 3),
                "type": "bell",
            })

    return detections, candidates, passed_spectral


def _detect_music_in_chunk(
    samples: np.ndarray, music_baseline: float, prev_spectrum: np.ndarray | None,
    chunk_offset_secs: float,
) -> tuple[list[dict], float, np.ndarray | None]:
    """
    Detect music starts using:
    1. Energy spike over rolling baseline (2-second sub-windows)
    2. Spectral flux (new frequency content appearing)
    3. Spectral flatness (music is more tonal than noise)

    Returns (detections, updated_baseline, last_spectrum).
    """
    sub_window_samples = SAMPLE_RATE * MUSIC_SUB_WINDOW_SECS
    detections = []
    updated_baseline = music_baseline
    last_spectrum = prev_spectrum

    for i in range(0, len(samples), sub_window_samples):
        window = samples[i : i + sub_window_samples]
        if len(window) < SAMPLE_RATE:  # skip < 1 second
            break

        window_f64 = window.astype(np.float64)
        window_energy = _rms(window)
        sub_offset_secs = chunk_offset_secs + (i / SAMPLE_RATE)

        # Compute magnitude spectrum for this sub-window
        curr_spectrum = np.abs(rfft(window_f64))

        energy_spike = False
        flux_spike = False

        # Check 1: Energy ratio over baseline
        if updated_baseline > 0:
            energy_ratio = window_energy / updated_baseline
            if energy_ratio > MUSIC_ENERGY_THRESHOLD:
                energy_spike = True
        else:
            energy_ratio = 0.0

        # Check 2: Spectral flux (new frequency content)
        if last_spectrum is not None and len(last_spectrum) == len(curr_spectrum):
            flux = _spectral_flux(last_spectrum, curr_spectrum)
            if flux > MUSIC_SPECTRAL_FLUX_THRESHOLD:
                flux_spike = True
        else:
            flux = 0.0

        # Need at least one trigger
        if energy_spike or flux_spike:
            # Check 3: Spectral flatness — music is more tonal
            geo_mean = np.exp(np.mean(np.log(curr_spectrum + 1e-10)))
            arith_mean = np.mean(curr_spectrum)
            flatness = geo_mean / arith_mean if arith_mean > 0 else 1.0

            # Also check spectral centroid shift — music often shifts the
            # frequency center compared to crowd noise
            if flatness < 0.6:
                ticks = int(sub_offset_secs * TICKS_PER_SECOND)
                # Confidence from combined signals
                conf = 0.1
                if energy_spike:
                    conf += min(0.4, (energy_ratio - MUSIC_ENERGY_THRESHOLD) * 0.3)
                if flux_spike:
                    conf += min(0.35, flux * 0.5)
                confidence = min(0.85, conf)
                detections.append({
                    "timestamp_ticks": ticks,
                    "confidence": round(confidence, 3),
                    "type": "music_start",
                })

        last_spectrum = curr_spectrum

        # Update rolling baseline (slow EMA)
        if updated_baseline == 0:
            updated_baseline = window_energy
        else:
            updated_baseline = 0.05 * window_energy + 0.95 * updated_baseline

    return detections, updated_baseline, last_spectrum


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
        "-nostdin",
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
    prev_spectrum: np.ndarray | None = None
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

            # Music start detection (2-second sub-windows with spectral flux)
            music_hits, music_baseline, prev_spectrum = _detect_music_in_chunk(
                samples, music_baseline, prev_spectrum, chunk_offset_secs
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
    1. Bell sounds (2.5-4kHz transients with onset detection)
    2. Music starts (energy + spectral flux)

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
