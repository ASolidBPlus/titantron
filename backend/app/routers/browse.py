from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.database import get_db
from app.models.event import Event
from app.models.library import Library
from app.models.match import Match, MatchParticipant
from app.models.promotion import Promotion
from app.models.video_item import VideoItem
from app.models.wrestler import Wrestler
from app.routers.auth import _load_connection
from app.services.cagematch_scraper import CagematchScraper


def _jellyfin_base_url() -> str:
    """Get the Jellyfin server base URL from the stored connection."""
    conn = _load_connection()
    return conn.get("url", "")


def _poster_url(jellyfin_item_id: str, image_tag: str | None, base_url: str | None = None) -> str | None:
    """Build a Jellyfin poster URL if the video has an image tag."""
    if not image_tag:
        return None
    if base_url is None:
        base_url = _jellyfin_base_url()
    if not base_url:
        return None
    return f"{base_url}/Items/{jellyfin_item_id}/Images/Primary?tag={image_tag}&maxWidth=400&quality=90"

router = APIRouter()


@router.get("/promotions")
async def list_promotions(db: AsyncSession = Depends(get_db)):
    """List all promotions that have configured libraries."""
    result = await db.execute(
        select(
            Promotion.id,
            Promotion.cagematch_id,
            Promotion.name,
            Promotion.abbreviation,
            func.count(Event.id.distinct()).label("event_count"),
            func.count(VideoItem.id.distinct()).label("video_count"),
        )
        .outerjoin(Event, Event.promotion_id == Promotion.id)
        .outerjoin(Library, Library.promotion_id == Promotion.id)
        .outerjoin(VideoItem, VideoItem.library_id == Library.id)
        .group_by(Promotion.id)
    )
    rows = result.all()

    return [
        {
            "id": row.id,
            "cagematch_id": row.cagematch_id,
            "name": row.name,
            "abbreviation": row.abbreviation,
            "event_count": row.event_count,
            "video_count": row.video_count,
        }
        for row in rows
    ]


@router.get("/promotions/{cagematch_id}/events")
async def list_promotion_events(
    cagematch_id: int,
    year: int | None = None,
    db: AsyncSession = Depends(get_db),
):
    """List events for a promotion (by Cagematch ID), optionally filtered by year."""
    promo_result = await db.execute(
        select(Promotion).where(Promotion.cagematch_id == cagematch_id)
    )
    promotion = promo_result.scalar_one_or_none()
    if not promotion:
        raise HTTPException(status_code=404, detail="Promotion not found")

    query = (
        select(
            Event.id,
            Event.cagematch_event_id,
            Event.name,
            Event.date,
            Event.location,
            Event.rating,
            Event.votes,
            func.count(VideoItem.id).label("video_count"),
        )
        .outerjoin(VideoItem, VideoItem.matched_event_id == Event.id)
        .where(Event.promotion_id == promotion.id)
        .group_by(Event.id)
        .order_by(Event.date.desc())
    )

    if year:
        query = query.where(func.extract("year", Event.date) == year)

    result = await db.execute(query)
    rows = result.all()

    return {
        "promotion": {
            "id": promotion.id,
            "cagematch_id": promotion.cagematch_id,
            "name": promotion.name,
            "abbreviation": promotion.abbreviation,
        },
        "events": [
            {
                "id": row.id,
                "cagematch_event_id": row.cagematch_event_id,
                "name": row.name,
                "date": str(row.date),
                "location": row.location,
                "rating": row.rating,
                "votes": row.votes,
                "video_count": row.video_count,
            }
            for row in rows
        ],
    }


@router.get("/events/{cagematch_event_id}")
async def get_event_detail(
    cagematch_event_id: int,
    db: AsyncSession = Depends(get_db),
):
    """Get event detail with matches and linked videos (by Cagematch event ID)."""
    result = await db.execute(
        select(Event)
        .options(selectinload(Event.matches).selectinload(Match.participants).selectinload(MatchParticipant.wrestler))
        .where(Event.cagematch_event_id == cagematch_event_id)
    )
    event = result.scalar_one_or_none()
    if not event:
        raise HTTPException(status_code=404, detail="Event not found")

    # Get linked videos
    vid_result = await db.execute(
        select(VideoItem).where(VideoItem.matched_event_id == event.id)
    )
    videos = vid_result.scalars().all()

    # Get promotion
    promo_result = await db.execute(
        select(Promotion).where(Promotion.id == event.promotion_id)
    )
    promotion = promo_result.scalar_one_or_none()

    base_url = _jellyfin_base_url()

    return {
        "id": event.id,
        "cagematch_event_id": event.cagematch_event_id,
        "name": event.name,
        "date": str(event.date),
        "promotion": {
            "id": promotion.id,
            "cagematch_id": promotion.cagematch_id,
            "name": promotion.name,
            "abbreviation": promotion.abbreviation,
        } if promotion else None,
        "location": event.location,
        "arena": event.arena,
        "rating": event.rating,
        "votes": event.votes,
        "matches": [
            {
                "id": m.id,
                "match_number": m.match_number,
                "match_type": m.match_type,
                "title_name": m.title_name,
                "result": m.result,
                "rating": m.rating,
                "votes": m.votes,
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
        "videos": [
            {
                "id": v.id,
                "jellyfin_item_id": v.jellyfin_item_id,
                "title": v.title,
                "match_status": v.match_status,
                "match_confidence": v.match_confidence,
                "poster_url": _poster_url(v.jellyfin_item_id, v.image_tag, base_url),
            }
            for v in videos
        ],
    }


@router.post("/events/{cagematch_event_id}/scrape-matches")
async def scrape_event_matches(
    cagematch_event_id: int,
    db: AsyncSession = Depends(get_db),
):
    """Scrape match card from Cagematch and store in DB."""
    result = await db.execute(select(Event).where(Event.cagematch_event_id == cagematch_event_id))
    event = result.scalar_one_or_none()
    if not event:
        raise HTTPException(status_code=404, detail="Event not found")

    scraper = CagematchScraper()
    match_data_list = await scraper.scrape_event_matches(event.cagematch_event_id)

    if not match_data_list:
        return {"message": "No matches found", "count": 0}

    # Clear existing matches for this event (re-scrape)
    existing = await db.execute(select(Match).where(Match.event_id == event.id))
    for m in existing.scalars().all():
        await db.delete(m)
    await db.flush()

    created_count = 0
    for md in match_data_list:
        match = Match(
            event_id=event.id,
            match_number=md.match_number,
            match_type=md.match_type,
            title_name=md.title_name,
            result=md.result,
            rating=md.rating,
            votes=md.votes,
            duration=md.duration,
        )
        db.add(match)
        await db.flush()

        # Add participants
        for wr in md.participants:
            # Find or create wrestler
            if wr.cagematch_id:
                w_result = await db.execute(
                    select(Wrestler).where(Wrestler.cagematch_wrestler_id == wr.cagematch_id)
                )
                wrestler = w_result.scalar_one_or_none()
            else:
                w_result = await db.execute(
                    select(Wrestler).where(
                        Wrestler.name == wr.name,
                        Wrestler.cagematch_wrestler_id.is_(None),
                    )
                )
                wrestler = w_result.scalar_one_or_none()

            if not wrestler:
                wrestler = Wrestler(
                    cagematch_wrestler_id=wr.cagematch_id,
                    name=wr.name,
                    is_linked=wr.is_linked,
                )
                db.add(wrestler)
                await db.flush()

            participant = MatchParticipant(
                match_id=match.id,
                wrestler_id=wrestler.id,
                side=wr.side,
                team_name=wr.team_name,
                role=wr.role,
            )
            db.add(participant)

        created_count += 1

    event.last_scraped = datetime.now()
    await db.commit()

    return {"message": f"Scraped {created_count} matches", "count": created_count}


@router.get("/events/{cagematch_event_id}/comments")
async def get_event_comments(
    cagematch_event_id: int,
    db: AsyncSession = Depends(get_db),
):
    """Scrape and return user comments/reviews from Cagematch for this event."""
    result = await db.execute(select(Event).where(Event.cagematch_event_id == cagematch_event_id))
    event = result.scalar_one_or_none()
    if not event:
        raise HTTPException(status_code=404, detail="Event not found")

    scraper = CagematchScraper()
    comments = await scraper.scrape_event_comments(event.cagematch_event_id)

    return [
        {
            "username": c.username,
            "date": str(c.date) if c.date else None,
            "rating": c.rating,
            "text": c.text,
        }
        for c in comments
    ]


@router.get("/test-scrape/{cagematch_event_id}")
async def test_scrape(cagematch_event_id: int):
    """Scrape a Cagematch event by its Cagematch ID and return parsed data without saving.

    Useful for testing the scraper against any event.
    """
    scraper = CagematchScraper()

    detail = await scraper.scrape_event_detail(cagematch_event_id)
    matches = await scraper.scrape_event_matches(cagematch_event_id)

    return {
        "event": {
            "cagematch_event_id": cagematch_event_id,
            "name": detail.name if detail else None,
            "date": str(detail.date) if detail else None,
            "promotion": detail.promotion_name if detail else None,
            "location": detail.location if detail else None,
            "arena": detail.arena if detail else None,
        },
        "matches": [
            {
                "match_number": m.match_number,
                "match_type": m.match_type,
                "title_name": m.title_name,
                "result": m.result,
                "rating": m.rating,
                "votes": m.votes,
                "duration": m.duration,
                "participants": [
                    {
                        "name": p.name,
                        "cagematch_id": p.cagematch_id,
                        "is_linked": p.is_linked,
                        "side": p.side,
                        "team_name": p.team_name,
                        "role": p.role,
                    }
                    for p in m.participants
                ],
            }
            for m in matches
        ],
    }
