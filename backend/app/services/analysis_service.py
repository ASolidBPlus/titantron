from __future__ import annotations

import json
import logging
import os
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import async_session
from app.models.analysis_result import AnalysisResult
from app.models.library import Library
from app.models.video_item import VideoItem
from app.services.audio_detector import detect_audio_events
from app.services.jellyfin_client import JellyfinClient
from app.services.scene_detector import detect_visual_transitions

logger = logging.getLogger(__name__)

# In-memory progress tracking keyed by video_item_id
_analysis_progress: dict[int, dict] = {}


def get_analysis_progress(video_id: int) -> dict | None:
    return _analysis_progress.get(video_id)


async def run_analysis(video_id: int, client: JellyfinClient) -> None:
    """
    Run full analysis pipeline for a video:
    1. Fetch trickplay metadata and run visual scene detection
    2. Resolve local file path and run audio pattern detection
    3. Persist results to DB
    """
    _analysis_progress[video_id] = {
        "status": "running_visual",
        "progress": 0,
        "total_steps": 0,
        "message": "Starting visual analysis...",
    }

    try:
        async with async_session() as db:
            # Load video + library
            result = await db.execute(
                select(VideoItem).where(VideoItem.id == video_id)
            )
            video = result.scalar_one_or_none()
            if not video:
                raise ValueError(f"Video {video_id} not found")

            # Create or reset analysis result row
            ar_result = await db.execute(
                select(AnalysisResult).where(AnalysisResult.video_item_id == video_id)
            )
            analysis = ar_result.scalar_one_or_none()
            if analysis:
                analysis.status = "running_visual"
                analysis.progress = 0
                analysis.total_steps = 0
                analysis.message = "Starting visual analysis..."
                analysis.error = None
                analysis.visual_detections = None
                analysis.audio_detections = None
                analysis.completed_at = None
            else:
                analysis = AnalysisResult(
                    video_item_id=video_id,
                    status="running_visual",
                )
                db.add(analysis)
            await db.commit()

            # --- Visual scene detection ---
            visual_detections: list[dict] = []
            try:
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
                    def on_visual_progress(current: int, total: int):
                        _analysis_progress[video_id].update({
                            "progress": current,
                            "total_steps": total,
                            "message": f"Analyzing trickplay sheets ({current}/{total})...",
                        })

                    visual_detections = await detect_visual_transitions(
                        client, video.jellyfin_item_id, trickplay_meta,
                        on_progress=on_visual_progress,
                    )
                else:
                    logger.info(f"Video {video_id} has no trickplay data, skipping visual detection")
            except Exception as e:
                logger.error(f"Visual detection failed: {e}")
                _analysis_progress[video_id]["message"] = f"Visual detection failed: {e}"

            # Save visual results
            analysis.visual_detections = json.dumps(visual_detections)
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

            # --- Audio detection ---
            audio_detections: list[dict] = []
            local_path = None

            # Resolve local file path via library path mapping
            if video.library_id and video.path:
                lib_result = await db.execute(
                    select(Library).where(Library.id == video.library_id)
                )
                library = lib_result.scalar_one_or_none()
                if library:
                    local_path = library.resolve_local_path(video.path)

            if local_path and os.path.isfile(local_path):
                try:
                    def on_audio_progress(current: int, total: int):
                        _analysis_progress[video_id].update({
                            "progress": current,
                            "total_steps": total,
                            "message": f"Analyzing audio ({current}/{total}s)...",
                        })

                    audio_detections = await detect_audio_events(
                        local_path,
                        video.duration_ticks or 0,
                        on_progress=on_audio_progress,
                    )
                except Exception as e:
                    logger.error(f"Audio detection failed: {e}")
                    _analysis_progress[video_id]["message"] = f"Audio detection failed: {e}"
            else:
                if not local_path:
                    logger.info(f"No local path mapping for video {video_id}, skipping audio")
                    _analysis_progress[video_id]["message"] = (
                        "Audio analysis skipped (no path mapping configured)"
                    )
                else:
                    logger.warning(f"Local file not found: {local_path}")
                    _analysis_progress[video_id]["message"] = (
                        f"Audio analysis skipped (file not found: {local_path})"
                    )

            # Save final results
            analysis.audio_detections = json.dumps(audio_detections)
            analysis.status = "completed"
            analysis.completed_at = datetime.now()
            analysis.message = (
                f"Done: {len(visual_detections)} visual, {len(audio_detections)} audio detections"
            )
            analysis.error = None
            await db.commit()

            _analysis_progress[video_id].update({
                "status": "completed",
                "message": analysis.message,
            })

    except Exception as e:
        logger.error(f"Analysis failed for video {video_id}: {e}")
        _analysis_progress[video_id].update({
            "status": "failed",
            "message": f"Analysis failed: {e}",
        })
        # Try to update DB status
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
        # Clean up in-memory progress after a delay so the frontend can read the final status
        import asyncio
        await asyncio.sleep(5)
        _analysis_progress.pop(video_id, None)
