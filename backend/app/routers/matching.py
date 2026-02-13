import logging

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import async_session, get_db
from app.models.event import Event
from app.models.library import Library
from app.models.promotion import Promotion
from app.models.video_item import VideoItem
from app.routers.browse import _jellyfin_base_url, _poster_url
from app.services.cagematch_scraper import CagematchScraper
from app.services.matching_engine import (
    find_candidates,
    match_library,
    match_video,
    score_match,
)

logger = logging.getLogger(__name__)
router = APIRouter()

# Module-level matching status with log
MAX_LOG_LINES = 200

match_status = {
    "is_running": False,
    "library_id": None,
    "progress": None,
    "total": None,
    "message": None,
    "results": None,
    "log": [],
}


def _log(msg: str):
    """Append to the matching log."""
    from datetime import datetime
    entry = {"time": datetime.now().isoformat(timespec="seconds"), "message": msg}
    match_status["log"].append(entry)
    if len(match_status["log"]) > MAX_LOG_LINES:
        match_status["log"] = match_status["log"][-MAX_LOG_LINES:]
    logger.info(f"[matching] {msg}")


def _on_progress(current: int, total: int, title: str, status: str, log_msg: str):
    """Progress callback from match_library."""
    match_status["progress"] = current
    match_status["total"] = total
    match_status["message"] = f"Matching {current}/{total}: {title}" if title else log_msg
    _log(log_msg)


async def _run_matching(library_id: int):
    """Background task to run matching for a library."""
    match_status["is_running"] = True
    match_status["library_id"] = library_id
    match_status["progress"] = 0
    match_status["total"] = None
    match_status["message"] = "Starting matching..."
    match_status["results"] = None
    match_status["log"] = []

    _log(f"Matching started for library {library_id}")

    scraper = CagematchScraper()
    try:
        async with async_session() as db:
            stats = await match_library(db, library_id, scraper, on_progress=_on_progress)
            match_status["results"] = stats
            done_msg = (
                f"Done: {stats['auto_matched']} auto-matched, "
                f"{stats['suggested']} suggested, "
                f"{stats['unmatched']} unmatched "
                f"(total: {stats['total']})"
            )
            match_status["message"] = done_msg
            _log(done_msg)
    except Exception as e:
        logger.error(f"Matching failed: {e}")
        match_status["message"] = f"Matching failed: {e}"
        _log(f"ERROR: {e}")
    finally:
        match_status["is_running"] = False


@router.post("/libraries/{library_id}/match")
async def trigger_matching(
    library_id: int,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
):
    """Trigger matching for all unmatched videos in a library."""
    if match_status["is_running"]:
        raise HTTPException(status_code=409, detail="Matching already in progress")

    result = await db.execute(select(Library).where(Library.id == library_id))
    if not result.scalar_one_or_none():
        raise HTTPException(status_code=404, detail="Library not found")

    background_tasks.add_task(_run_matching, library_id)
    return {"message": "Matching started"}


@router.get("/status")
async def get_match_status():
    """Get current matching status."""
    return match_status


@router.get("/libraries/{library_id}/videos")
async def list_library_videos(
    library_id: int,
    status: str | None = None,
    db: AsyncSession = Depends(get_db),
):
    """List videos in a library with match info, optionally filtered by status."""
    query = select(VideoItem).where(VideoItem.library_id == library_id)
    if status:
        query = query.where(VideoItem.match_status == status)
    query = query.order_by(VideoItem.extracted_date.desc())

    result = await db.execute(query)
    videos = result.scalars().all()

    base_url = _jellyfin_base_url()
    items = []
    for v in videos:
        item = {
            "id": v.id,
            "jellyfin_item_id": v.jellyfin_item_id,
            "title": v.title,
            "filename": v.filename,
            "extracted_date": str(v.extracted_date) if v.extracted_date else None,
            "match_status": v.match_status,
            "match_confidence": v.match_confidence,
            "matched_event_id": v.matched_event_id,
            "matched_event_name": None,
            "poster_url": _poster_url(v.jellyfin_item_id, v.image_tag, base_url),
        }
        if v.matched_event_id:
            ev_result = await db.execute(
                select(Event).where(Event.id == v.matched_event_id)
            )
            event = ev_result.scalar_one_or_none()
            if event:
                item["matched_event_name"] = event.name
        items.append(item)

    return items


@router.get("/videos/{video_id}/candidates")
async def get_video_candidates(
    video_id: int,
    db: AsyncSession = Depends(get_db),
):
    """Get match candidates for a specific video (for manual review)."""
    result = await db.execute(select(VideoItem).where(VideoItem.id == video_id))
    video = result.scalar_one_or_none()
    if not video:
        raise HTTPException(status_code=404, detail="Video not found")

    if not video.extracted_date:
        return {"video_id": video_id, "candidates": [], "message": "No date extracted"}

    # Get library -> promotion info
    lib_result = await db.execute(select(Library).where(Library.id == video.library_id))
    library = lib_result.scalar_one_or_none()
    if not library:
        raise HTTPException(status_code=404, detail="Library not found")

    promo_result = await db.execute(
        select(Promotion).where(Promotion.id == library.promotion_id)
    )
    promotion = promo_result.scalar_one_or_none()
    if not promotion:
        raise HTTPException(status_code=404, detail="Promotion not found")

    scraper = CagematchScraper()
    candidates = await find_candidates(scraper, promotion.cagematch_id, video.extracted_date)

    title = video.title or video.filename or ""
    scored = []
    for ev in candidates:
        sc = score_match(title, ev.name, video.extracted_date, ev.date, promotion.abbreviation or "")
        scored.append({
            "cagematch_event_id": ev.cagematch_event_id,
            "name": ev.name,
            "date": str(ev.date),
            "location": ev.location,
            "rating": ev.rating,
            "votes": ev.votes,
            "score": round(sc, 3),
        })

    scored.sort(key=lambda x: x["score"], reverse=True)

    return {
        "video_id": video_id,
        "video_title": title,
        "extracted_date": str(video.extracted_date),
        "candidates": scored,
    }


@router.post("/videos/{video_id}/confirm")
async def confirm_match(
    video_id: int,
    db: AsyncSession = Depends(get_db),
):
    """Confirm a suggested match."""
    result = await db.execute(select(VideoItem).where(VideoItem.id == video_id))
    video = result.scalar_one_or_none()
    if not video:
        raise HTTPException(status_code=404, detail="Video not found")

    if not video.matched_event_id:
        raise HTTPException(status_code=400, detail="No match to confirm")

    video.match_status = "confirmed"
    await db.commit()
    return {"success": True, "status": "confirmed"}


@router.post("/videos/{video_id}/reject")
async def reject_match(
    video_id: int,
    db: AsyncSession = Depends(get_db),
):
    """Reject a match and reset to unmatched."""
    result = await db.execute(select(VideoItem).where(VideoItem.id == video_id))
    video = result.scalar_one_or_none()
    if not video:
        raise HTTPException(status_code=404, detail="Video not found")

    video.matched_event_id = None
    video.match_confidence = None
    video.match_status = "unmatched"
    await db.commit()
    return {"success": True, "status": "unmatched"}


@router.post("/videos/{video_id}/rematch")
async def rematch_video(
    video_id: int,
    db: AsyncSession = Depends(get_db),
):
    """Re-run matching for a specific video (resets it to unmatched first)."""
    result = await db.execute(select(VideoItem).where(VideoItem.id == video_id))
    video = result.scalar_one_or_none()
    if not video:
        raise HTTPException(status_code=404, detail="Video not found")

    if not video.extracted_date:
        raise HTTPException(status_code=400, detail="Video has no extracted date")

    lib_result = await db.execute(select(Library).where(Library.id == video.library_id))
    library = lib_result.scalar_one_or_none()
    if not library:
        raise HTTPException(status_code=404, detail="Library not found")

    promo_result = await db.execute(
        select(Promotion).where(Promotion.id == library.promotion_id)
    )
    promotion = promo_result.scalar_one_or_none()
    if not promotion:
        raise HTTPException(status_code=404, detail="Promotion not found")

    video.matched_event_id = None
    video.match_confidence = None
    video.match_status = "unmatched"

    scraper = CagematchScraper()
    match_result = await match_video(
        db, video, scraper, promotion.cagematch_id, promotion.abbreviation or ""
    )
    await db.commit()

    if match_result:
        return {
            "success": True,
            "status": match_result["status"],
            "event_name": match_result["event_name"],
            "score": match_result["score"],
        }
    return {"success": True, "status": "unmatched", "event_name": None, "score": None}


@router.post("/videos/bulk-confirm")
async def bulk_confirm(
    body: dict,
    db: AsyncSession = Depends(get_db),
):
    """Confirm multiple video matches at once. Body: {"video_ids": [1, 2, 3]}"""
    video_ids = body.get("video_ids", [])
    if not video_ids:
        raise HTTPException(status_code=400, detail="No video IDs provided")

    result = await db.execute(
        select(VideoItem).where(VideoItem.id.in_(video_ids))
    )
    videos = result.scalars().all()

    confirmed = 0
    for v in videos:
        if v.matched_event_id:
            v.match_status = "confirmed"
            confirmed += 1

    await db.commit()
    return {"confirmed": confirmed, "total": len(video_ids)}


@router.post("/videos/bulk-reject")
async def bulk_reject(
    body: dict,
    db: AsyncSession = Depends(get_db),
):
    """Reject multiple video matches at once. Body: {"video_ids": [1, 2, 3]}"""
    video_ids = body.get("video_ids", [])
    if not video_ids:
        raise HTTPException(status_code=400, detail="No video IDs provided")

    result = await db.execute(
        select(VideoItem).where(VideoItem.id.in_(video_ids))
    )
    videos = result.scalars().all()

    rejected = 0
    for v in videos:
        v.matched_event_id = None
        v.match_confidence = None
        v.match_status = "unmatched"
        rejected += 1

    await db.commit()
    return {"rejected": rejected, "total": len(video_ids)}


@router.get("/events/search")
async def search_events(
    q: str,
    db: AsyncSession = Depends(get_db),
):
    """Search events in the local DB by name."""
    if len(q) < 2:
        return []

    result = await db.execute(
        select(Event).where(Event.name.ilike(f"%{q}%")).order_by(Event.date.desc()).limit(20)
    )
    events = result.scalars().all()

    return [
        {
            "id": ev.id,
            "cagematch_event_id": ev.cagematch_event_id,
            "name": ev.name,
            "date": str(ev.date) if ev.date else None,
            "location": ev.location,
            "rating": ev.rating,
        }
        for ev in events
    ]


@router.post("/videos/{video_id}/assign/{cagematch_event_id}")
async def assign_match(
    video_id: int,
    cagematch_event_id: int,
    db: AsyncSession = Depends(get_db),
):
    """Manually assign a video to a specific Cagematch event."""
    result = await db.execute(select(VideoItem).where(VideoItem.id == video_id))
    video = result.scalar_one_or_none()
    if not video:
        raise HTTPException(status_code=404, detail="Video not found")

    # Find or create the event in DB
    ev_result = await db.execute(
        select(Event).where(Event.cagematch_event_id == cagematch_event_id)
    )
    db_event = ev_result.scalar_one_or_none()

    if not db_event:
        # Scrape event detail to create it
        scraper = CagematchScraper()
        detail = await scraper.scrape_event_detail(cagematch_event_id)
        if not detail:
            raise HTTPException(status_code=404, detail="Event not found on Cagematch")

        # Get promotion from library
        lib_result = await db.execute(select(Library).where(Library.id == video.library_id))
        library = lib_result.scalar_one_or_none()

        db_event = Event(
            cagematch_event_id=cagematch_event_id,
            name=detail.name,
            date=detail.date,
            promotion_id=library.promotion_id if library else 1,
            location=detail.location,
            rating=detail.rating,
            votes=detail.votes,
        )
        db.add(db_event)
        await db.flush()

    video.matched_event_id = db_event.id
    video.match_confidence = 1.0
    video.match_status = "confirmed"
    await db.commit()

    return {
        "success": True,
        "event_id": db_event.id,
        "event_name": db_event.name,
        "status": "confirmed",
    }
