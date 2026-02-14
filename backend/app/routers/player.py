import uuid

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.config import get_setting
from app.database import get_db
from app.models.chapter import Chapter
from app.models.event import Event
from app.models.match import Match, MatchParticipant
from app.models.video_item import VideoItem
from app.routers.auth import _load_connection, get_jellyfin_client
from app.services.jellyfin_client import JellyfinClient

router = APIRouter()


# --- Pydantic schemas ---


class ChapterCreate(BaseModel):
    title: str
    start_ticks: int
    match_id: int | None = None


class ChapterUpdate(BaseModel):
    title: str | None = None
    start_ticks: int | None = None
    match_id: int | None = None


class PlaybackReport(BaseModel):
    position_ticks: int
    is_paused: bool = False
    play_session_id: str


# --- Helper ---


async def _recompute_chapter_ends(db: AsyncSession, video_id: int):
    """Auto-fill end_ticks: each chapter ends where the next begins, last ends at video duration."""
    video = await db.get(VideoItem, video_id)
    result = await db.execute(
        select(Chapter).where(Chapter.video_item_id == video_id).order_by(Chapter.start_ticks)
    )
    chapters = list(result.scalars().all())
    for i, ch in enumerate(chapters):
        if i + 1 < len(chapters):
            ch.end_ticks = chapters[i + 1].start_ticks
        else:
            ch.end_ticks = video.duration_ticks if video else None


async def _sync_chapters_to_jellyfin(db: AsyncSession, video_id: int, client: JellyfinClient):
    """Push current chapters to Jellyfin so they appear in native clients too."""
    video = await db.get(VideoItem, video_id)
    if not video:
        return
    result = await db.execute(
        select(Chapter).where(Chapter.video_item_id == video_id).order_by(Chapter.start_ticks)
    )
    chapters = list(result.scalars().all())
    jellyfin_chapters = [
        {"StartPositionTicks": ch.start_ticks, "Name": ch.title}
        for ch in chapters
    ]
    try:
        await client.update_item_chapters(video.jellyfin_item_id, jellyfin_chapters)
    except Exception:
        pass  # Non-fatal — local chapters still work


# --- Player info endpoint ---


@router.get("/{video_id}/info")
async def get_player_info(
    video_id: int,
    db: AsyncSession = Depends(get_db),
    client: JellyfinClient = Depends(get_jellyfin_client),
):
    """Main player info endpoint: stream URL, trickplay, chapters, event data."""
    # Load video with eager-loaded chapters and matched_event
    result = await db.execute(
        select(VideoItem)
        .options(selectinload(VideoItem.chapters), selectinload(VideoItem.matched_event))
        .where(VideoItem.id == video_id)
    )
    video = result.scalar_one_or_none()
    if not video:
        raise HTTPException(status_code=404, detail="Video not found")

    # Public URL for client-facing URLs (stream, trickplay)
    # Backend still uses client.server_url for API calls
    jellyfin_public_url = get_setting("jellyfin_public_url")
    public_url = jellyfin_public_url.rstrip("/") if jellyfin_public_url else client.server_url

    # Ask Jellyfin for optimal playback method (direct play vs transcode)
    play_session_id = str(uuid.uuid4())
    playback_info = await client.get_playback_info(
        video.jellyfin_item_id, video.media_source_id or video.jellyfin_item_id
    )
    play_session_id = playback_info.get("PlaySessionId", play_session_id)

    # Determine stream URL from Jellyfin's response
    media_sources = playback_info.get("MediaSources", [])
    stream_url = None
    is_hls = False
    if media_sources:
        ms = media_sources[0]
        transcode_url = ms.get("TranscodingUrl")
        if ms.get("SupportsDirectPlay") or ms.get("SupportsDirectStream"):
            # Direct play/stream — serve the file as-is or remuxed
            stream_url = (
                f"{public_url}/Videos/{video.jellyfin_item_id}/stream"
                f"?static=true"
                f"&MediaSourceId={video.media_source_id}"
                f"&api_key={client.access_token}"
                f"&DeviceId={client.device_id}"
                f"&PlaySessionId={play_session_id}"
            )
        elif transcode_url:
            # Jellyfin provides a transcoding URL (HLS)
            stream_url = f"{public_url}{transcode_url}"
            is_hls = True

    if not stream_url:
        # Fallback: direct stream
        stream_url = (
            f"{public_url}/Videos/{video.jellyfin_item_id}/stream"
            f"?static=true"
            f"&MediaSourceId={video.media_source_id}"
            f"&api_key={client.access_token}"
            f"&DeviceId={client.device_id}"
            f"&PlaySessionId={play_session_id}"
        )

    # Trickplay metadata (always check Jellyfin — DB flag may be stale)
    trickplay_data = None
    try:
        detail = await client.get_item_detail(video.jellyfin_item_id)
        tp = detail.get("Trickplay", {})
        for media_id, resolutions in tp.items():
            for res_str, meta in resolutions.items():
                trickplay_data = {
                    "resolution": int(res_str),
                    "width": meta["Width"],
                    "height": meta["Height"],
                    "tile_width": meta["TileWidth"],
                    "tile_height": meta["TileHeight"],
                    "thumbnail_count": meta["ThumbnailCount"],
                    "interval": meta["Interval"],
                    "base_url": f"/api/v1/player/{video_id}/trickplay/{res_str}/",
                }
                break
            break
    except Exception:
        pass  # Trickplay is optional

    # Event data with matches and participants
    event_data = None
    if video.matched_event_id:
        ev_result = await db.execute(
            select(Event)
            .options(selectinload(Event.matches).selectinload(Match.participants).selectinload(MatchParticipant.wrestler))
            .where(Event.id == video.matched_event_id)
        )
        event = ev_result.scalar_one_or_none()
        if event:
            event_data = {
                "id": event.id,
                "cagematch_event_id": event.cagematch_event_id,
                "name": event.name,
                "date": str(event.date),
                "matches": [
                    {
                        "id": m.id,
                        "match_number": m.match_number,
                        "match_type": m.match_type,
                        "title_name": m.title_name,
                        "result": m.result,
                        "rating": m.rating,
                        "duration": m.duration,
                        "participants": [
                            {
                                "id": p.wrestler.id,
                                "name": p.wrestler.name,
                                "cagematch_wrestler_id": p.wrestler.cagematch_wrestler_id,
                                "is_linked": p.wrestler.is_linked,
                                "side": p.side,
                                "team_name": p.team_name,
                                "is_winner": p.is_winner,
                                "role": p.role,
                            }
                            for p in m.participants
                        ],
                    }
                    for m in event.matches
                ],
            }

    # Chapters (already ordered by start_ticks via relationship)
    chapters = [
        {
            "id": c.id,
            "video_item_id": c.video_item_id,
            "match_id": c.match_id,
            "title": c.title,
            "start_ticks": c.start_ticks,
            "end_ticks": c.end_ticks,
        }
        for c in video.chapters
    ]

    return {
        "video": {
            "id": video.id,
            "jellyfin_item_id": video.jellyfin_item_id,
            "title": video.title,
            "duration_ticks": video.duration_ticks,
            "media_source_id": video.media_source_id,
        },
        "stream": {
            "url": stream_url,
            "is_hls": is_hls,
            "play_session_id": play_session_id,
            "api_key": client.access_token,
            "server_url": public_url,
        },
        "trickplay": trickplay_data,
        "chapters": chapters,
        "event": event_data,
    }


# --- Chapter CRUD endpoints ---


@router.get("/{video_id}/chapters")
async def list_chapters(
    video_id: int,
    db: AsyncSession = Depends(get_db),
):
    """List chapters for a video."""
    result = await db.execute(
        select(Chapter).where(Chapter.video_item_id == video_id).order_by(Chapter.start_ticks)
    )
    chapters = result.scalars().all()
    return [
        {
            "id": c.id,
            "video_item_id": c.video_item_id,
            "match_id": c.match_id,
            "title": c.title,
            "start_ticks": c.start_ticks,
            "end_ticks": c.end_ticks,
        }
        for c in chapters
    ]


@router.post("/{video_id}/chapters")
async def create_chapter(
    video_id: int,
    body: ChapterCreate,
    db: AsyncSession = Depends(get_db),
    client: JellyfinClient = Depends(get_jellyfin_client),
):
    """Create a chapter for a video."""
    chapter = Chapter(
        video_item_id=video_id,
        title=body.title,
        start_ticks=body.start_ticks,
        match_id=body.match_id,
    )
    db.add(chapter)
    await db.flush()
    await _recompute_chapter_ends(db, video_id)
    await db.commit()
    await _sync_chapters_to_jellyfin(db, video_id, client)
    return {
        "id": chapter.id,
        "video_item_id": chapter.video_item_id,
        "match_id": chapter.match_id,
        "title": chapter.title,
        "start_ticks": chapter.start_ticks,
        "end_ticks": chapter.end_ticks,
    }


@router.put("/{video_id}/chapters/{chapter_id}")
async def update_chapter(
    video_id: int,
    chapter_id: int,
    body: ChapterUpdate,
    db: AsyncSession = Depends(get_db),
    client: JellyfinClient = Depends(get_jellyfin_client),
):
    """Update a chapter."""
    chapter = await db.get(Chapter, chapter_id)
    if not chapter or chapter.video_item_id != video_id:
        raise HTTPException(status_code=404, detail="Chapter not found")
    if body.title is not None:
        chapter.title = body.title
    if body.start_ticks is not None:
        chapter.start_ticks = body.start_ticks
    if body.match_id is not None:
        chapter.match_id = body.match_id
    await _recompute_chapter_ends(db, video_id)
    await db.commit()
    await _sync_chapters_to_jellyfin(db, video_id, client)
    return {
        "id": chapter.id,
        "video_item_id": chapter.video_item_id,
        "match_id": chapter.match_id,
        "title": chapter.title,
        "start_ticks": chapter.start_ticks,
        "end_ticks": chapter.end_ticks,
    }


@router.delete("/{video_id}/chapters/{chapter_id}")
async def delete_chapter(
    video_id: int,
    chapter_id: int,
    db: AsyncSession = Depends(get_db),
    client: JellyfinClient = Depends(get_jellyfin_client),
):
    """Delete a chapter."""
    chapter = await db.get(Chapter, chapter_id)
    if not chapter or chapter.video_item_id != video_id:
        raise HTTPException(status_code=404, detail="Chapter not found")
    await db.delete(chapter)
    await db.flush()
    await _recompute_chapter_ends(db, video_id)
    await db.commit()
    await _sync_chapters_to_jellyfin(db, video_id, client)
    return {"success": True}


# --- Playback reporting endpoints ---


@router.post("/{video_id}/playback/start")
async def playback_start(
    video_id: int,
    report: PlaybackReport,
    db: AsyncSession = Depends(get_db),
    client: JellyfinClient = Depends(get_jellyfin_client),
):
    video = await db.get(VideoItem, video_id)
    if not video:
        raise HTTPException(status_code=404, detail="Video not found")
    await client.report_playback_start({
        "ItemId": video.jellyfin_item_id,
        "MediaSourceId": video.media_source_id,
        "PositionTicks": report.position_ticks,
        "IsPaused": report.is_paused,
        "PlaySessionId": report.play_session_id,
    })
    return {"success": True}


@router.post("/{video_id}/playback/progress")
async def playback_progress(
    video_id: int,
    report: PlaybackReport,
    db: AsyncSession = Depends(get_db),
    client: JellyfinClient = Depends(get_jellyfin_client),
):
    video = await db.get(VideoItem, video_id)
    if not video:
        raise HTTPException(status_code=404, detail="Video not found")
    await client.report_playback_progress({
        "ItemId": video.jellyfin_item_id,
        "MediaSourceId": video.media_source_id,
        "PositionTicks": report.position_ticks,
        "IsPaused": report.is_paused,
        "PlaySessionId": report.play_session_id,
    })
    return {"success": True}


@router.post("/{video_id}/playback/stopped")
async def playback_stopped(
    video_id: int,
    report: PlaybackReport,
    db: AsyncSession = Depends(get_db),
    client: JellyfinClient = Depends(get_jellyfin_client),
):
    video = await db.get(VideoItem, video_id)
    if not video:
        raise HTTPException(status_code=404, detail="Video not found")
    await client.report_playback_stopped({
        "ItemId": video.jellyfin_item_id,
        "MediaSourceId": video.media_source_id,
        "PositionTicks": report.position_ticks,
        "IsPaused": report.is_paused,
        "PlaySessionId": report.play_session_id,
    })
    return {"success": True}


# --- Trickplay proxy ---


@router.get("/{video_id}/trickplay/{resolution}/{filename}")
async def get_trickplay_tile(
    video_id: int,
    resolution: int,
    filename: str,
    db: AsyncSession = Depends(get_db),
    client: JellyfinClient = Depends(get_jellyfin_client),
):
    """Proxy trickplay sprite sheets from Jellyfin to avoid CORS issues."""
    video = await db.get(VideoItem, video_id)
    if not video:
        raise HTTPException(status_code=404, detail="Video not found")
    # filename arrives as e.g. "46185.jpg" — pass through to Jellyfin as-is
    data = await client._request_bytes(
        f"/Videos/{video.jellyfin_item_id}/Trickplay/{resolution}/{filename}"
    )
    return Response(content=data, media_type="image/jpeg")
