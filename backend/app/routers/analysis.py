from __future__ import annotations

import json
import logging

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.analysis_result import AnalysisResult
from app.models.video_item import VideoItem
from app.routers.auth import get_jellyfin_client
from app.services.analysis_service import get_analysis_progress, run_analysis
from app.services.jellyfin_client import JellyfinClient

logger = logging.getLogger(__name__)
router = APIRouter()


@router.post("/{video_id}/analyze")
async def start_analysis(
    video_id: int,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
    client: JellyfinClient = Depends(get_jellyfin_client),
):
    """Trigger chapter detection analysis for a video."""
    video = await db.get(VideoItem, video_id)
    if not video:
        raise HTTPException(status_code=404, detail="Video not found")

    progress = get_analysis_progress(video_id)
    if progress and progress.get("status", "").startswith("running"):
        raise HTTPException(status_code=409, detail="Analysis already in progress")

    background_tasks.add_task(run_analysis, video_id, client)
    return {"message": "Analysis started"}


@router.get("/{video_id}/analyze/status")
async def get_analysis_status(
    video_id: int,
    db: AsyncSession = Depends(get_db),
):
    """Poll analysis progress."""
    # Check in-memory progress first (active analysis)
    progress = get_analysis_progress(video_id)
    if progress:
        return progress

    # Fall back to DB (completed/failed analysis)
    result = await db.execute(
        select(AnalysisResult).where(AnalysisResult.video_item_id == video_id)
    )
    analysis = result.scalar_one_or_none()
    if not analysis:
        return {"status": "none"}

    return {
        "status": analysis.status,
        "progress": analysis.progress,
        "total_steps": analysis.total_steps,
        "message": analysis.message,
        "error": analysis.error,
    }


@router.get("/{video_id}/analyze/results")
async def get_analysis_results(
    video_id: int,
    db: AsyncSession = Depends(get_db),
):
    """Get completed analysis detections."""
    result = await db.execute(
        select(AnalysisResult).where(AnalysisResult.video_item_id == video_id)
    )
    analysis = result.scalar_one_or_none()
    if not analysis or analysis.status != "completed":
        raise HTTPException(status_code=404, detail="No completed analysis")

    return {
        "visual": json.loads(analysis.visual_detections or "[]"),
        "audio": json.loads(analysis.audio_detections or "[]"),
        "completed_at": analysis.completed_at.isoformat() if analysis.completed_at else None,
    }


@router.delete("/{video_id}/analyze")
async def clear_analysis(
    video_id: int,
    db: AsyncSession = Depends(get_db),
):
    """Clear analysis results for a video."""
    result = await db.execute(
        select(AnalysisResult).where(AnalysisResult.video_item_id == video_id)
    )
    analysis = result.scalar_one_or_none()
    if analysis:
        await db.delete(analysis)
        await db.commit()
    return {"success": True}
