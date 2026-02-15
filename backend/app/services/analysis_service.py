from __future__ import annotations

import asyncio
import json
import logging
import os
import traceback
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import async_session
from app.models.analysis_result import AnalysisResult
from app.models.video_item import VideoItem
from app.services.jellyfin_client import JellyfinClient
from app.services.ml_client import check_ml_available, classify_audio
from app.services.scene_detector import detect_visual_transitions, detect_visual_transitions_trickplay

logger = logging.getLogger(__name__)

# In-memory progress tracking keyed by video_item_id
_analysis_progress: dict[int, dict] = {}

# In-memory batch progress tracking keyed by library_id
_batch_progress: dict[int, dict] = {}

# Overall timeout for a single video analysis
ANALYSIS_TIMEOUT_SECONDS = 600  # 10 minutes


def get_analysis_progress(video_id: int) -> dict | None:
    return _analysis_progress.get(video_id)


def get_batch_progress(library_id: int) -> dict | None:
    return _batch_progress.get(library_id)


async def run_analysis(
    video_id: int, client: JellyfinClient, phase: str = "both"
) -> None:
    """
    Run analysis pipeline for a video.
    phase: "both" (default), "visual", or "audio"
    1. Fetch trickplay metadata and run visual scene detection (if phase != "audio")
    2. Resolve local file path and run audio pattern detection (if phase != "visual")
    3. Persist results to DB
    """
    _analysis_progress[video_id] = {
        "status": "running_visual" if phase != "audio" else "running_audio",
        "progress": 0,
        "total_steps": 0,
        "message": f"Starting {'visual' if phase != 'audio' else 'audio'} analysis...",
    }

    try:
        await asyncio.wait_for(
            _run_analysis_pipeline(video_id, client, phase),
            timeout=ANALYSIS_TIMEOUT_SECONDS,
        )
    except asyncio.TimeoutError:
        logger.error(f"Analysis timed out for video {video_id}")
        traceback.print_exc()
        _analysis_progress[video_id].update({
            "status": "failed",
            "message": "Analysis timed out (10 minute limit)",
        })
        try:
            async with async_session() as db:
                ar_result = await db.execute(
                    select(AnalysisResult).where(AnalysisResult.video_item_id == video_id)
                )
                analysis = ar_result.scalar_one_or_none()
                if analysis:
                    analysis.status = "failed"
                    analysis.error = "Analysis timed out"
                    await db.commit()
        except Exception:
            pass
    except Exception as e:
        logger.error(f"Analysis failed for video {video_id}: {e}")
        traceback.print_exc()
        _analysis_progress[video_id].update({
            "status": "failed",
            "message": f"Analysis failed: {e}",
        })
        try:
            async with async_session() as db:
                ar_result = await db.execute(
                    select(AnalysisResult).where(AnalysisResult.video_item_id == video_id)
                )
                analysis = ar_result.scalar_one_or_none()
                if analysis:
                    analysis.status = "failed"
                    analysis.error = str(e)
                    await db.commit()
        except Exception:
            pass
    finally:
        await asyncio.sleep(5)
        _analysis_progress.pop(video_id, None)


async def _run_analysis_pipeline(
    video_id: int, client: JellyfinClient, phase: str
) -> None:
    """Inner pipeline that does the actual analysis work."""
    async with async_session() as db:
        # Load video
        result = await db.execute(
            select(VideoItem).where(VideoItem.id == video_id)
        )
        video = result.scalar_one_or_none()
        if not video:
            raise ValueError(f"Video {video_id} not found")

        # Create or update analysis result row
        ar_result = await db.execute(
            select(AnalysisResult).where(AnalysisResult.video_item_id == video_id)
        )
        analysis = ar_result.scalar_one_or_none()

        if analysis:
            status = "running_visual" if phase != "audio" else "running_audio"
            analysis.status = status
            analysis.progress = 0
            analysis.total_steps = 0
            analysis.message = f"Starting {phase} analysis..."
            analysis.error = None
            # Only clear detections for the phase being re-run
            if phase in ("both", "visual"):
                analysis.visual_detections = None
            if phase in ("both", "audio"):
                analysis.audio_detections = None
                analysis.audio_spectrum = None
                analysis.audio_skip_reason = None
            analysis.completed_at = None
        else:
            analysis = AnalysisResult(
                video_item_id=video_id,
                status="running_visual" if phase != "audio" else "running_audio",
            )
            db.add(analysis)
        await db.commit()

        # --- Resolve local file path (shared by visual + audio) ---
        local_path = None
        if video.path:
            from app.config import get_setting
            path_from = get_setting("path_map_from")
            path_to = get_setting("path_map_to")
            print(f"[ANALYSIS] Path mapping: from={path_from!r} to={path_to!r} video.path={video.path!r}", flush=True)
            if path_from and path_to and video.path.startswith(path_from):
                relative = video.path[len(path_from):].lstrip("/")
                local_path = os.path.join(path_to, relative)
                if not os.path.isfile(local_path):
                    print(f"[ANALYSIS] Local file NOT found: {local_path}", flush=True)
                    local_path = None
                else:
                    print(f"[ANALYSIS] Local file found: {local_path}", flush=True)
        else:
            print(f"[ANALYSIS] Video has no path set", flush=True)

        # --- Visual scene detection ---
        visual_detections: list[dict] = []
        if phase in ("both", "visual"):
            try:
                def on_visual_progress(current: int, total: int):
                    _analysis_progress[video_id].update({
                        "progress": current,
                        "total_steps": total,
                        "message": f"Analyzing video frames ({current}/{total}s)...",
                    })

                if local_path:
                    # Primary: ffmpeg frame extraction (0.5fps, much more accurate)
                    logger.info(f"Visual detection via ffmpeg: {local_path}")
                    visual_detections = await detect_visual_transitions(
                        local_path,
                        video.duration_ticks or 0,
                        on_progress=on_visual_progress,
                    )
                else:
                    # Fallback: trickplay thumbnails (less accurate, 10s intervals)
                    logger.info(f"Visual detection via trickplay (no local path)")
                    detail = await client.get_item_detail(video.jellyfin_item_id)
                    tp = detail.get("Trickplay", {})
                    trickplay_meta = None
                    for media_id, resolutions in tp.items():
                        for res_str, meta in resolutions.items():
                            trickplay_meta = {
                                "resolution": int(res_str),
                                "width": meta["Width"],
                                "height": meta["Height"],
                                "tile_width": meta["TileWidth"],
                                "tile_height": meta["TileHeight"],
                                "thumbnail_count": meta["ThumbnailCount"],
                                "interval": meta["Interval"],
                            }
                            break
                        break

                    if trickplay_meta:
                        visual_detections = await detect_visual_transitions_trickplay(
                            client, video.jellyfin_item_id, trickplay_meta,
                            on_progress=on_visual_progress,
                        )
                    else:
                        logger.info(f"Video {video_id} has no trickplay data, skipping visual detection")
            except Exception as e:
                logger.error(f"Visual detection failed: {e}")
                traceback.print_exc()
                _analysis_progress[video_id]["message"] = f"Visual detection failed: {e}"

            # Save visual results
            analysis.visual_detections = json.dumps(visual_detections)

        # --- Audio detection (ML-powered, opt-in) ---
        if phase in ("both", "audio"):
            analysis.status = "running_audio"
            analysis.progress = 0
            analysis.total_steps = 0
            analysis.message = "Starting audio analysis..."
            await db.commit()

            _analysis_progress[video_id].update({
                "status": "running_audio",
                "progress": 0,
                "total_steps": 0,
                "message": "Starting audio analysis...",
            })

            audio_detections: list[dict] = []
            audio_spectrum: list[dict] = []
            audio_window_secs: int = 30
            audio_skip_reason: str | None = None

            ml_enabled = get_setting("ml_audio_enabled")

            if not ml_enabled:
                audio_skip_reason = "ml_audio_disabled"
                logger.info(f"ML audio disabled, skipping audio for video {video_id}")
                _analysis_progress[video_id]["message"] = (
                    "Audio analysis skipped (ML audio not enabled)"
                )
            elif not local_path:
                audio_skip_reason = "no_path_mapping"
                logger.info(f"No local path mapping for video {video_id}, skipping audio")
                _analysis_progress[video_id]["message"] = (
                    "Audio analysis skipped (no path mapping configured)"
                )
            else:
                # Check ML service availability
                ml_status = await check_ml_available()
                if not ml_status["available"]:
                    audio_skip_reason = "ml_service_unavailable"
                    logger.warning(f"ML service unavailable, skipping audio for video {video_id}")
                    _analysis_progress[video_id]["message"] = (
                        "Audio analysis skipped (ML service unavailable)"
                    )
                else:
                    try:
                        def on_audio_progress(current: int, total: int, message: str | None = None):
                            update = {
                                "progress": current,
                                "total_steps": total,
                            }
                            if message:
                                update["message"] = message
                            else:
                                update["message"] = f"Analyzing audio ({current}/{total}s)..."
                            _analysis_progress[video_id].update(update)

                        audio_result = await classify_audio(
                            local_path,
                            video.duration_ticks or 0,
                            on_progress=on_audio_progress,
                        )
                        audio_detections = audio_result["detections"]
                        audio_spectrum = audio_result["spectrum"]
                        audio_window_secs = audio_result["window_secs"]
                    except Exception as e:
                        logger.error(f"ML audio detection failed: {e}")
                        audio_skip_reason = f"error:{e}"
                        _analysis_progress[video_id]["message"] = f"Audio detection failed: {e}"

            analysis.audio_detections = json.dumps(audio_detections)
            analysis.audio_spectrum = json.dumps({"spectrum": audio_spectrum, "window_secs": audio_window_secs})
            analysis.audio_skip_reason = audio_skip_reason

        # Save final results
        analysis.status = "completed"
        analysis.completed_at = datetime.now()

        # Build summary message
        vis_count = len(json.loads(analysis.visual_detections or "[]"))
        aud_count = len(json.loads(analysis.audio_detections or "[]"))
        skip_note = ""
        if analysis.audio_skip_reason:
            skip_note = f" (skipped: {analysis.audio_skip_reason.split(':')[0]})"
        analysis.message = f"Done: {vis_count} visual, {aud_count} audio detections{skip_note}"
        analysis.error = None
        await db.commit()

        _analysis_progress[video_id].update({
            "status": "completed",
            "message": analysis.message,
            "audio_skip_reason": analysis.audio_skip_reason,
        })


async def run_batch_analysis(library_id: int, client: JellyfinClient) -> None:
    """
    Process all unanalyzed videos in a library sequentially.
    Skips videos that already have completed analysis.
    """
    _batch_progress[library_id] = {
        "status": "running",
        "current_video": None,
        "current_video_title": None,
        "progress": 0,
        "total": 0,
        "message": "Loading videos...",
    }

    try:
        async with async_session() as db:
            # Get all videos in the library
            result = await db.execute(
                select(VideoItem).where(VideoItem.library_id == library_id)
            )
            all_videos = result.scalars().all()

            # Filter out videos that already have completed analysis
            videos_to_analyze = []
            for video in all_videos:
                ar_result = await db.execute(
                    select(AnalysisResult).where(
                        AnalysisResult.video_item_id == video.id,
                        AnalysisResult.status == "completed",
                    )
                )
                if not ar_result.scalar_one_or_none():
                    videos_to_analyze.append(video)

        total = len(videos_to_analyze)
        _batch_progress[library_id].update({
            "total": total,
            "message": f"Analyzing {total} videos...",
        })

        if total == 0:
            _batch_progress[library_id].update({
                "status": "completed",
                "message": "All videos already analyzed",
            })
            await asyncio.sleep(5)
            _batch_progress.pop(library_id, None)
            return

        for i, video in enumerate(videos_to_analyze):
            _batch_progress[library_id].update({
                "current_video": video.id,
                "current_video_title": video.title,
                "progress": i,
                "message": f"Analyzing {i + 1}/{total}: {video.title}",
            })

            try:
                await _run_analysis_pipeline(video.id, client, "both")
            except Exception as e:
                logger.error(f"Batch analysis failed for video {video.id}: {e}")
                # Continue with next video

            # Clean up per-video progress
            _analysis_progress.pop(video.id, None)

        _batch_progress[library_id].update({
            "status": "completed",
            "progress": total,
            "message": f"Batch analysis complete: {total} videos processed",
        })

    except Exception as e:
        logger.error(f"Batch analysis failed for library {library_id}: {e}")
        _batch_progress[library_id].update({
            "status": "failed",
            "message": f"Batch analysis failed: {e}",
        })
    finally:
        await asyncio.sleep(10)
        _batch_progress.pop(library_id, None)
