from __future__ import annotations

import asyncio
import logging
from collections import deque
from typing import Callable

import numpy as np
from scipy import signal as scipy_signal
from scipy.fft import rfft, rfftfreq

logger = logging.getLogger(__name__)

SAMPLE_RATE = 16000  # 16kHz mono
CHUNK_SECONDS = 10
CHUNK_SAMPLES = SAMPLE_RATE * CHUNK_SECONDS
TICKS_PER_SECOND = 10_000_000

# ── Bell detection ──
# Wider band (2-5kHz) captures more bell varieties and harmonics
BELL_LOW_HZ = 2000
BELL_HIGH_HZ = 5000
BELL_FRAME_SAMPLES = SAMPLE_RATE * 25 // 1000  # 25ms frames = 400 samples
BELL_HISTORY_FRAMES = 40  # 1 second of history for baseline
BELL_ONSET_THRESHOLD = 3.0  # frame energy must be 3x median of recent history
BELL_SPECTRAL_MIN_RATIO = 0.03  # relaxed FFT sanity check (3% in bell band)
BELL_MIN_GAP_SECS = 0.3  # min gap between distinct bell hits
BELL_CLUSTER_WINDOW_SECS = 30
BELL_MIN_CLUSTER = 2

# ── Music detection ──
# Simple sustained energy change — no spectral flux or flatness gates
MUSIC_WINDOW_SAMPLES = SAMPLE_RATE  # 1-second windows
MUSIC_HISTORY_WINDOWS = 15  # 15 seconds of history for baseline
MUSIC_ENERGY_THRESHOLD = 1.5  # 50% above recent median
MUSIC_SUSTAIN_WINDOWS = 3  # must stay elevated for 3 consecutive seconds
MUSIC_COOLDOWN_SECS = 30.0  # skip detection for 30s after a music_start

AUDIO_TIMEOUT_SECONDS = 300


def _design_bandpass(low_hz: int, high_hz: int, fs: int, order: int = 4):
    nyq = fs / 2
    return scipy_signal.butter(order, [low_hz / nyq, high_hz / nyq], btype="band", output="sos")


def _rms(data: np.ndarray) -> float:
    if len(data) == 0:
        return 0.0
    return float(np.sqrt(np.mean(data.astype(np.float64) ** 2)))


class _BellDetector:
    """Detect bell sounds via onset detection in a bandpass-filtered signal.

    Instead of comparing energy to a rolling EMA baseline (which gets
    corrupted by the bells themselves), we compare each 25ms frame's
    energy to the *median* of the previous 1 second of frames. A bell
    creates a sharp local spike regardless of the ambient level.

    Filter state is preserved across chunks to avoid boundary artifacts.
    """

    def __init__(self):
        self.sos = _design_bandpass(BELL_LOW_HZ, BELL_HIGH_HZ, SAMPLE_RATE)
        self.zi = scipy_signal.sosfilt_zi(self.sos)
        self.zi_initialized = False
        self.frame_energies: deque[float] = deque(maxlen=BELL_HISTORY_FRAMES)
        self.detections: list[dict] = []
        self.samples_processed = 0
        self.onset_candidates = 0
        # Diagnostics: track top onset values to understand signal behavior
        self.top_onsets: list[tuple[float, float]] = []

    def process_chunk(self, samples: np.ndarray):
        samples_f64 = samples.astype(np.float64)

        # Maintain bandpass filter state across chunks to avoid transients
        if not self.zi_initialized:
            self.zi = self.zi * samples_f64[0]
            self.zi_initialized = True
        filtered, self.zi = scipy_signal.sosfilt(self.sos, samples_f64, zi=self.zi)

        n_frames = len(filtered) // BELL_FRAME_SAMPLES
        for i in range(n_frames):
            start = i * BELL_FRAME_SAMPLES
            frame = filtered[start : start + BELL_FRAME_SAMPLES]
            energy = _rms(frame)

            abs_sample = self.samples_processed + start
            abs_time = abs_sample / SAMPLE_RATE

            # Need enough history for a stable median
            if len(self.frame_energies) >= 20:
                median_e = float(np.median(list(self.frame_energies)))
                if median_e > 0:
                    onset = energy / median_e

                    # Track top onsets for diagnostics
                    if len(self.top_onsets) < 20 or onset > self.top_onsets[-1][1]:
                        self.top_onsets.append((abs_time, onset))
                        self.top_onsets.sort(key=lambda x: -x[1])
                        self.top_onsets = self.top_onsets[:20]

                    if onset > BELL_ONSET_THRESHOLD:
                        self.onset_candidates += 1

                        # Min gap from last detection
                        last_secs = self.detections[-1]["_secs"] if self.detections else -999
                        if abs_time - last_secs > BELL_MIN_GAP_SECS:
                            # Lightweight FFT sanity check on surrounding 0.5s
                            center = start + BELL_FRAME_SAMPLES // 2
                            fft_start = max(0, center - SAMPLE_RATE // 4)
                            fft_end = min(len(samples), center + SAMPLE_RATE // 4)
                            seg = samples[fft_start:fft_end].astype(np.float64)

                            passed_fft = True
                            if len(seg) >= 256:
                                fft_v = np.abs(rfft(seg))
                                freqs = rfftfreq(len(seg), 1.0 / SAMPLE_RATE)
                                bell_mask = (freqs >= BELL_LOW_HZ) & (freqs <= BELL_HIGH_HZ)
                                total = fft_v.sum()
                                bell = fft_v[bell_mask].sum() if bell_mask.any() else 0
                                passed_fft = total > 0 and bell / total >= BELL_SPECTRAL_MIN_RATIO

                            if passed_fft:
                                conf = min(0.8, onset / 10.0)
                                conf = max(0.15, conf)
                                ticks = int(abs_time * TICKS_PER_SECOND)
                                self.detections.append({
                                    "timestamp_ticks": ticks,
                                    "confidence": round(conf, 3),
                                    "type": "bell",
                                    "_secs": abs_time,
                                })

            self.frame_energies.append(energy)

        self.samples_processed += len(samples)

    def finalize(self) -> list[dict]:
        print(
            f"[BELL] Onset candidates: {self.onset_candidates}, "
            f"raw detections: {len(self.detections)}",
            flush=True,
        )
        if self.top_onsets:
            top5 = self.top_onsets[:5]
            print(
                f"[BELL] Top 5 onset strengths: "
                + ", ".join(f"{t:.1f}s={s:.1f}x" for t, s in top5),
                flush=True,
            )
        # Strip internal fields, then cluster
        for d in self.detections:
            d.pop("_secs", None)
        return _cluster_bells(self.detections)


class _MusicDetector:
    """Detect music starts via sustained broadband energy increase.

    Uses 1-second windows compared to the median of the prior 15 seconds.
    Music must stay elevated for 3+ consecutive seconds to trigger (filters
    out brief crowd pops). No spectral flatness or flux gates — those
    were rejecting legitimate music.
    """

    def __init__(self):
        self.window_energies: deque[float] = deque(maxlen=MUSIC_HISTORY_WINDOWS)
        self.detections: list[dict] = []
        self.elevated_count = 0
        self.elevated_start_secs = 0.0
        self.cooldown_until = 0.0
        self.samples_processed = 0
        self.total_windows = 0
        self.top_ratios: list[tuple[float, float]] = []

    def process_chunk(self, samples: np.ndarray):
        n_windows = len(samples) // MUSIC_WINDOW_SAMPLES
        for i in range(n_windows):
            start = i * MUSIC_WINDOW_SAMPLES
            window = samples[start : start + MUSIC_WINDOW_SAMPLES]
            energy = _rms(window)

            abs_sample = self.samples_processed + start
            abs_time = abs_sample / SAMPLE_RATE
            self.total_windows += 1

            # Cooldown after a detection
            if abs_time < self.cooldown_until:
                self.window_energies.append(energy)
                self.elevated_count = 0
                continue

            # Need enough history for a stable baseline
            if len(self.window_energies) >= 10:
                median_e = float(np.median(list(self.window_energies)))
                ratio = energy / median_e if median_e > 0 else 0.0

                # Track top ratios for diagnostics
                if len(self.top_ratios) < 20 or ratio > self.top_ratios[-1][1]:
                    self.top_ratios.append((abs_time, ratio))
                    self.top_ratios.sort(key=lambda x: -x[1])
                    self.top_ratios = self.top_ratios[:20]

                if ratio > MUSIC_ENERGY_THRESHOLD:
                    if self.elevated_count == 0:
                        self.elevated_start_secs = abs_time
                    self.elevated_count += 1

                    if self.elevated_count >= MUSIC_SUSTAIN_WINDOWS:
                        ticks = int(self.elevated_start_secs * TICKS_PER_SECOND)
                        conf = min(
                            0.85,
                            0.3
                            + (ratio - MUSIC_ENERGY_THRESHOLD) * 0.2
                            + (self.elevated_count - MUSIC_SUSTAIN_WINDOWS) * 0.05,
                        )
                        conf = max(0.2, conf)
                        self.detections.append({
                            "timestamp_ticks": ticks,
                            "confidence": round(conf, 3),
                            "type": "music_start",
                        })
                        self.cooldown_until = abs_time + MUSIC_COOLDOWN_SECS
                        self.elevated_count = 0
                else:
                    self.elevated_count = 0

            self.window_energies.append(energy)

        self.samples_processed += len(samples)

    def finalize(self) -> list[dict]:
        print(
            f"[MUSIC] Windows processed: {self.total_windows}, "
            f"raw detections: {len(self.detections)}",
            flush=True,
        )
        if self.top_ratios:
            top5 = self.top_ratios[:5]
            print(
                f"[MUSIC] Top 5 energy ratios: "
                + ", ".join(f"{t:.1f}s={r:.2f}x" for t, r in top5),
                flush=True,
            )
        return _merge_music(self.detections)


def _cluster_bells(detections: list[dict]) -> list[dict]:
    """Cluster bell hits within 30 seconds (ding-ding-ding pattern) and boost confidence."""
    if not detections:
        return []

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


def _merge_music(detections: list[dict]) -> list[dict]:
    """Merge music detections within 30 seconds, keep highest confidence."""
    music = sorted(
        [d for d in detections if d["type"] == "music_start"],
        key=lambda d: d["timestamp_ticks"],
    )
    others = [d for d in detections if d["type"] != "music_start"]
    if not music:
        return others

    clusters: list[list[dict]] = [[music[0]]]
    for m in music[1:]:
        if (
            m["timestamp_ticks"] - clusters[-1][-1]["timestamp_ticks"]
            <= MUSIC_COOLDOWN_SECS * TICKS_PER_SECOND
        ):
            clusters[-1].append(m)
        else:
            clusters.append([m])

    result = [max(c, key=lambda d: d["confidence"]) for c in clusters]
    return result + others


async def _run_audio_pipeline(
    local_file_path: str,
    duration_ticks: int,
    on_progress: Callable[[int, int], None] | None = None,
) -> list[dict]:
    total_seconds = duration_ticks // TICKS_PER_SECOND
    chunk_bytes = CHUNK_SAMPLES * 2  # 16-bit = 2 bytes per sample

    print(f"[AUDIO] Starting analysis: {local_file_path}, {total_seconds}s", flush=True)

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

    bell = _BellDetector()
    music = _MusicDetector()
    chunk_idx = 0

    try:
        while True:
            try:
                raw = await process.stdout.readexactly(chunk_bytes)
            except asyncio.IncompleteReadError as e:
                raw = e.partial
                if len(raw) < SAMPLE_RATE * 2:  # less than 1 second
                    break

            samples = np.frombuffer(raw, dtype=np.int16)
            bell.process_chunk(samples)
            music.process_chunk(samples)
            chunk_idx += 1

            if on_progress and total_seconds > 0:
                processed = min(chunk_idx * CHUNK_SECONDS, total_seconds)
                on_progress(processed, total_seconds)

    finally:
        if process.returncode is None:
            process.kill()
        await process.wait()
        await stderr_task

    print(f"[AUDIO] Processed {chunk_idx} chunks ({chunk_idx * CHUNK_SECONDS}s)", flush=True)

    if process.returncode != 0:
        last = stderr_lines[-5:] if stderr_lines else ["(no stderr)"]
        print(f"[AUDIO] ffmpeg exit code {process.returncode}: {' | '.join(last)}", flush=True)

    bell_results = bell.finalize()
    music_results = music.finalize()
    return bell_results + music_results


async def detect_audio_events(
    local_file_path: str,
    duration_ticks: int,
    on_progress: Callable[[int, int], None] | None = None,
) -> list[dict]:
    """
    Extract audio from a local video file via ffmpeg and analyze for:
    1. Bell sounds (onset detection in 2-5kHz band)
    2. Music starts (sustained broadband energy increase)

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
    music_count = sum(1 for d in all_detections if d["type"] == "music_start")
    print(f"[AUDIO] Final: {bells} bells, {music_count} music starts", flush=True)
    return all_detections
