import logging
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.database import get_db
from app.models.event import Event
from app.models.match import Match, MatchParticipant
from app.models.wrestler import Wrestler
from app.services.cagematch_scraper import CagematchScraper

logger = logging.getLogger(__name__)

router = APIRouter()

STALE_THRESHOLD = timedelta(days=7)


async def _find_wrestler(db: AsyncSession, cagematch_id: int) -> Wrestler | None:
    """Look up a wrestler by cagematch_wrestler_id."""
    result = await db.execute(
        select(Wrestler).where(Wrestler.cagematch_wrestler_id == cagematch_id)
    )
    return result.scalar_one_or_none()


async def _maybe_scrape_profile(wrestler: Wrestler, db: AsyncSession):
    """Lazy-scrape wrestler profile from Cagematch if linked and data is stale."""
    if not wrestler.is_linked or not wrestler.cagematch_wrestler_id:
        return

    is_stale = not wrestler.last_scraped or (datetime.now() - wrestler.last_scraped) >= STALE_THRESHOLD
    missing_image = not wrestler.image_url
    if not is_stale and not missing_image:
        return

    try:
        scraper = CagematchScraper()
        profile = await scraper.scrape_wrestler_profile(wrestler.cagematch_wrestler_id)
        if profile:
            if profile.name:
                wrestler.name = profile.name
            wrestler.birth_date = profile.birth_date
            wrestler.birth_place = profile.birth_place
            wrestler.height = profile.height
            wrestler.weight = profile.weight
            wrestler.style = profile.style
            wrestler.debut = profile.debut
            wrestler.roles = profile.roles
            wrestler.nicknames = profile.nicknames
            wrestler.signature_moves = profile.signature_moves
            wrestler.trainers = profile.trainers
            wrestler.alter_egos = profile.alter_egos
            wrestler.rating = profile.rating
            wrestler.votes = profile.votes
            if profile.image_url:
                wrestler.image_url = profile.image_url
            wrestler.last_scraped = datetime.now()
            await db.commit()
    except Exception:
        logger.exception(f"Failed to scrape profile for wrestler {wrestler.cagematch_wrestler_id}")


@router.get("/{cagematch_id}")
async def get_wrestler(cagematch_id: int, db: AsyncSession = Depends(get_db)):
    """Get wrestler profile by Cagematch ID. Lazy-scrapes if data is stale."""
    wrestler = await _find_wrestler(db, cagematch_id)
    if not wrestler:
        raise HTTPException(status_code=404, detail="Wrestler not found")

    await _maybe_scrape_profile(wrestler, db)

    # Count matches
    match_count_result = await db.execute(
        select(func.count()).select_from(MatchParticipant).where(MatchParticipant.wrestler_id == wrestler.id)
    )
    match_count = match_count_result.scalar() or 0

    return {
        "id": wrestler.id,
        "cagematch_wrestler_id": wrestler.cagematch_wrestler_id,
        "name": wrestler.name,
        "image_url": wrestler.image_url,
        "is_linked": wrestler.is_linked,
        "birth_date": str(wrestler.birth_date) if wrestler.birth_date else None,
        "birth_place": wrestler.birth_place,
        "height": wrestler.height,
        "weight": wrestler.weight,
        "style": wrestler.style,
        "debut": wrestler.debut,
        "roles": wrestler.roles,
        "nicknames": wrestler.nicknames,
        "signature_moves": wrestler.signature_moves,
        "trainers": wrestler.trainers,
        "alter_egos": wrestler.alter_egos,
        "rating": wrestler.rating,
        "votes": wrestler.votes,
        "match_count": match_count,
    }


@router.get("/{cagematch_id}/matches")
async def get_wrestler_matches(
    cagematch_id: int,
    limit: int = Query(default=50, le=100),
    offset: int = Query(default=0, ge=0),
    db: AsyncSession = Depends(get_db),
):
    """Get paginated match history for a wrestler by Cagematch ID."""
    wrestler = await _find_wrestler(db, cagematch_id)
    if not wrestler:
        raise HTTPException(status_code=404, detail="Wrestler not found")

    wrestler_id = wrestler.id

    # Total count
    total_result = await db.execute(
        select(func.count()).select_from(MatchParticipant).where(MatchParticipant.wrestler_id == wrestler_id)
    )
    total = total_result.scalar() or 0

    # Fetch matches with eager loading
    result = await db.execute(
        select(MatchParticipant)
        .options(
            selectinload(MatchParticipant.match)
            .selectinload(Match.event),
            selectinload(MatchParticipant.match)
            .selectinload(Match.participants)
            .selectinload(MatchParticipant.wrestler),
        )
        .where(MatchParticipant.wrestler_id == wrestler_id)
        .join(Match, MatchParticipant.match_id == Match.id)
        .join(Event, Match.event_id == Event.id)
        .order_by(Event.date.desc(), Match.match_number)
        .offset(offset)
        .limit(limit)
    )
    participations = result.scalars().unique().all()

    matches = []
    for mp in participations:
        m = mp.match
        ev = m.event
        matches.append({
            "match_id": m.id,
            "match_number": m.match_number,
            "match_type": m.match_type,
            "title_name": m.title_name,
            "result": m.result,
            "rating": m.rating,
            "votes": m.votes,
            "duration": m.duration,
            "is_winner": mp.is_winner,
            "role": mp.role,
            "event": {
                "id": ev.id,
                "cagematch_event_id": ev.cagematch_event_id,
                "name": ev.name,
                "date": str(ev.date),
                "promotion_id": ev.promotion_id,
            },
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
        })

    return {"total": total, "matches": matches}
