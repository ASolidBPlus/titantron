"""Audio event detection using MIR-standard algorithms.

Bell: spectral-flux onset detection on 2-5kHz bandpass signal.
Music: sustained energy increase with tonal character (low spectral flatness).

Uses only numpy/scipy — no additional dependencies, keeping Docker image small.
The onset detection algorithm is the same as librosa's (mel-spectrogram spectral
flux with peak picking), implemented directly with scipy.signal and numpy.fft.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Callable

import numpy as np
from scipy import signal as scipy_signal

logger = logging.getLogger(__name__)

SR = 22050  # sample rate (MIR standard, matches librosa default)
TICKS = 10_000_000

# ── Bell detection ──
BELL_LOW_HZ = 2000
BELL_HIGH_HZ = 5000
BELL_N_FFT = 1024  # ~46ms analysis window
BELL_HOP = 256  # ~11.6ms hop — fine time resolution for transients
BELL_PEAK_DELTA = 0.15  # minimum normalized onset strength to count as peak
BELL_PEAK_DISTANCE = 20  # min frames between peaks (~230ms)
BELL_CLUSTER_SECS = 30
BELL_MIN_CLUSTER = 2

# ── Music detection ──
MUSIC_HISTORY_SECS = 15
MUSIC_SUSTAIN_SECS = 3
MUSIC_SCORE_THRESHOLD = 0.9  # energy_ratio * (1 - flatness) must exceed this
MUSIC_COOLDOWN_SECS = 30.0

AUDIO_TIMEOUT_SECS = 300


# ─── Core DSP ────────────────────────────────────────────────────────────────


def _spectral_flux_envelope(y: np.ndarray, n_fft: int, hop: int) -> np.ndarray:
    """Compute spectral-flux onset strength envelope.

    Standard MIR onset detection: for each pair of consecutive STFT frames,
    compute the sum of positive differences in log-power magnitude. This
    captures spectral *shape* changes (not just energy), making it effective
    for detecting transients like bell strikes against noisy backgrounds.

    Processes frame-by-frame so memory usage is O(n_fft), not O(signal_length).
    """
    y_pad = np.pad(y, n_fft // 2, mode="reflect")
    window = scipy_signal.windows.hann(n_fft, sym=False).astype(np.float32)

    n_frames = 1 + (len(y_pad) - n_fft) // hop
    if n_frames < 2:
        return np.array([], dtype=np.float32)

    onset_env = np.empty(n_frames - 1, dtype=np.float32)
    prev_db = None

    for i in range(n_frames):
        start = i * hop
        frame = y_pad[start : start + n_fft].astype(np.float32) * window
        mag = np.abs(np.fft.rfft(frame))
        db = 10.0 * np.log10(np.maximum(mag, 1e-10))

        if prev_db is not None:
            onset_env[i - 1] = np.sum(np.maximum(0, db - prev_db))

        prev_db = db

    return onset_env


# ─── Bell Detection ──────────────────────────────────────────────────────────


def _detect_bells(y: np.ndarray) -> list[dict]:
    """Detect bell sounds using spectral-flux onset detection on bandpass signal.

    1. Bandpass filter (2-5kHz) isolates bell frequency range
    2. Spectral flux onset envelope captures transient spectral changes
    3. scipy find_peaks detects prominent onsets
    4. Cluster nearby hits (ding-ding-ding pattern)
    """
    sos = scipy_signal.butter(
        4, [BELL_LOW_HZ / (SR / 2), BELL_HIGH_HZ / (SR / 2)],
        btype="band", output="sos",
    )
    y_bell = scipy_signal.sosfilt(sos, y).astype(np.float32)

    onset_env = _spectral_flux_envelope(y_bell, BELL_N_FFT, BELL_HOP)
    del y_bell

    if len(onset_env) == 0:
        print("[BELL] No onset data", flush=True)
        return []

    # Normalize to [0, 1]
    env_max = np.max(onset_env)
    if env_max > 0:
        onset_env = onset_env / env_max

    # Find peaks
    peaks, props = scipy_signal.find_peaks(
        onset_env, height=BELL_PEAK_DELTA, distance=BELL_PEAK_DISTANCE,
    )
    heights = props["peak_heights"]

    # Convert frame indices to seconds (+1 offset because flux is between frames)
    times = (peaks + 1) * BELL_HOP / SR

    detections = []
    for t, h in zip(times, heights):
        conf = min(0.85, max(0.1, float(h)))
        detections.append({
            "timestamp_ticks": int(t * TICKS),
            "confidence": round(conf, 3),
            "type": "bell",
        })

    # Diagnostics
    print(
        f"[BELL] Onset env: max={env_max:.1f}, "
        f"peaks found: {len(detections)}",
        flush=True,
    )
    if detections:
        top = sorted(detections, key=lambda d: -d["confidence"])[:5]
        print(
            "[BELL] Top 5: "
            + ", ".join(
                f"{d['timestamp_ticks']/TICKS:.1f}s conf={d['confidence']}"
                for d in top
            ),
            flush=True,
        )

    return _cluster_bells(detections)


# ─── Music Detection ─────────────────────────────────────────────────────────


def _detect_music(
    y: np.ndarray,
    on_progress: Callable[[int, int], None] | None,
) -> list[dict]:
    """Detect music starts via sustained energy increase with tonal character.

    Per-second analysis:
    - RMS energy: detect loudness changes vs recent baseline
    - Spectral flatness: distinguish tonal (music) from noise-like (crowd)
    - Combined score: energy_ratio * (1 - flatness)
    - Must stay elevated for 3+ consecutive seconds to filter out crowd pops
    """
    n_frames = len(y) // SR
    min_frames = int(MUSIC_HISTORY_SECS) + int(MUSIC_SUSTAIN_SECS)
    if n_frames < min_frames:
        print("[MUSIC] Audio too short for music detection", flush=True)
        return []

    energies = np.empty(n_frames, dtype=np.float32)
    flatnesses = np.empty(n_frames, dtype=np.float32)

    # Hann window for proper spectral analysis
    hann = np.hanning(SR).astype(np.float32)

    for i in range(n_frames):
        chunk = y[i * SR : (i + 1) * SR]
        energies[i] = float(np.sqrt(np.mean(chunk ** 2)))

        # Spectral flatness: exp(mean(log(S))) / mean(S)
        # Low = tonal (music), high = noise-like (crowd)
        S = np.abs(np.fft.rfft(chunk * hann))
        S = np.maximum(S, 1e-10)
        flatnesses[i] = float(np.exp(np.mean(np.log(S))) / np.mean(S))

    # Detect sustained music regions
    history_n = int(MUSIC_HISTORY_SECS)
    sustain_n = int(MUSIC_SUSTAIN_SECS)

    detections: list[dict] = []
    elevated_count = 0
    elevated_start = 0
    cooldown_until = 0
    top_scores: list[tuple[int, float, float, float]] = []

    for i in range(history_n, n_frames):
        if i < cooldown_until:
            elevated_count = 0
            continue

        baseline = float(np.median(energies[i - history_n : i]))
        ratio = float(energies[i]) / baseline if baseline > 0 else 0.0

        # Combined score: louder than baseline AND tonal
        score = float(ratio * (1.0 - float(flatnesses[i])))

        # Track top scores for diagnostics
        if len(top_scores) < 20 or score > top_scores[-1][1]:
            top_scores.append((i, score, ratio, float(flatnesses[i])))
            top_scores.sort(key=lambda x: -x[1])
            top_scores = top_scores[:20]

        if score > MUSIC_SCORE_THRESHOLD:
            if elevated_count == 0:
                elevated_start = i
            elevated_count += 1

            if elevated_count >= sustain_n:
                ticks = int(elevated_start * TICKS)
                conf = float(min(0.85, 0.3 + (score - MUSIC_SCORE_THRESHOLD) * 0.2))
                conf = float(max(0.2, conf))
                detections.append({
                    "timestamp_ticks": ticks,
                    "confidence": round(conf, 3),
                    "type": "music_start",
                })
                cooldown_until = i + int(MUSIC_COOLDOWN_SECS)
                elevated_count = 0
        else:
            elevated_count = 0

        if on_progress and i % 30 == 0:
            on_progress(i, n_frames)

    # Diagnostics
    print(
        f"[MUSIC] Analyzed {n_frames}s, detections: {len(detections)}",
        flush=True,
    )
    print(
        f"[MUSIC] Energy: median={np.median(energies):.5f}, max={energies.max():.5f}",
        flush=True,
    )
    print(
        f"[MUSIC] Flatness: median={np.median(flatnesses):.3f}, "
        f"min={flatnesses.min():.3f}, max={flatnesses.max():.3f}",
        flush=True,
    )
    if top_scores:
        top5 = top_scores[:5]
        print(
            "[MUSIC] Top 5 scores: "
            + ", ".join(
                f"{x[0]}s score={x[1]:.2f} (ratio={x[2]:.2f} flat={x[3]:.3f})"
                for x in top5
            ),
            flush=True,
        )

    return detections


# ─── Clustering ──────────────────────────────────────────────────────────────


def _cluster_bells(detections: list[dict]) -> list[dict]:
    """Cluster bell hits within 30s, boost confidence for ding-ding-ding."""
    bells = sorted(
        [d for d in detections if d["type"] == "bell"],
        key=lambda d: d["timestamp_ticks"],
    )
    others = [d for d in detections if d["type"] != "bell"]
    if not bells:
        return others

    clusters: list[list[dict]] = [[bells[0]]]
    for b in bells[1:]:
        if (
            b["timestamp_ticks"] - clusters[-1][-1]["timestamp_ticks"]
            <= BELL_CLUSTER_SECS * TICKS
        ):
            clusters[-1].append(b)
        else:
            clusters.append([b])

    result = []
    for cluster in clusters:
        best = max(cluster, key=lambda d: d["confidence"])
        if len(cluster) >= BELL_MIN_CLUSTER:
            best["confidence"] = min(0.95, best["confidence"] + 0.1 * len(cluster))
            best["confidence"] = round(best["confidence"], 3)
        result.append(best)

    return result + others


# ─── Pipeline ────────────────────────────────────────────────────────────────


async def _extract_audio(
    path: str,
    total_secs: int,
    on_progress: Callable[[int, int], None] | None,
) -> np.ndarray:
    """Extract mono audio at 22050Hz via ffmpeg with progress reporting."""
    process = await asyncio.create_subprocess_exec(
        "ffmpeg", "-nostdin", "-i", path, "-vn",
        "-acodec", "pcm_s16le", "-ar", str(SR), "-ac", "1",
        "-f", "s16le", "-nostats", "pipe:1",
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )

    # Drain stderr in background to prevent pipe deadlock
    async def _drain_stderr():
        async for _ in process.stderr:
            pass

    stderr_task = asyncio.create_task(_drain_stderr())

    # Read in 10-second chunks for progress reporting, accumulate into list
    chunk_bytes = SR * 2 * 10  # 10 seconds of 16-bit mono
    chunks: list[bytes] = []
    bytes_read = 0

    try:
        while True:
            try:
                data = await process.stdout.readexactly(chunk_bytes)
            except asyncio.IncompleteReadError as e:
                data = e.partial
                if data:
                    chunks.append(data)
                break
            chunks.append(data)
            bytes_read += len(data)

            if on_progress and total_secs > 0:
                secs_read = bytes_read // (SR * 2)
                on_progress(secs_read, total_secs)
    finally:
        if process.returncode is None:
            process.kill()
        await process.wait()
        await stderr_task

    raw = b"".join(chunks)
    if process.returncode != 0:
        print(f"[AUDIO] ffmpeg exited with code {process.returncode}", flush=True)
    return np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0


async def _pipeline(
    path: str,
    total_secs: int,
    on_progress: Callable[[int, int], None] | None,
) -> list[dict]:
    print(f"[AUDIO] Starting analysis: {path} ({total_secs}s)", flush=True)

    y = await _extract_audio(path, total_secs, on_progress)
    duration = len(y) / SR
    print(f"[AUDIO] Loaded {duration:.1f}s ({len(y)} samples at {SR}Hz)", flush=True)

    bells = _detect_bells(y)

    music = _detect_music(y, on_progress)

    n_b = sum(1 for d in bells if d["type"] == "bell")
    n_m = len(music)
    print(f"[AUDIO] Final: {n_b} bells, {n_m} music starts", flush=True)

    return bells + music


async def detect_audio_events(
    local_file_path: str,
    duration_ticks: int,
    on_progress: Callable[[int, int], None] | None = None,
) -> list[dict]:
    """Extract audio from a video file and detect bells + music starts.

    Bell detection: spectral-flux onset detection on 2-5kHz bandpass signal.
    Music detection: sustained broadband energy increase with tonal character.

    Includes a 5-minute timeout to prevent hanging.
    """
    try:
        return await asyncio.wait_for(
            _pipeline(local_file_path, duration_ticks // TICKS, on_progress),
            timeout=AUDIO_TIMEOUT_SECS,
        )
    except asyncio.TimeoutError:
        print(
            f"[AUDIO] Timed out after {AUDIO_TIMEOUT_SECS}s for {local_file_path}",
            flush=True,
        )
        raise TimeoutError(f"Audio analysis timed out after {AUDIO_TIMEOUT_SECS}s")
