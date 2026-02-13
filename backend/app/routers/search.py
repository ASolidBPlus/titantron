from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.event import Event
from app.models.match import MatchParticipant
from app.models.wrestler import Wrestler

router = APIRouter()


@router.get("")
async def global_search(
    q: str = Query(min_length=2),
    db: AsyncSession = Depends(get_db),
):
    """Search events and wrestlers by name (local DB only)."""
    pattern = f"%{q}%"

    # Search events
    event_result = await db.execute(
        select(
            Event.id,
            Event.cagematch_event_id,
            Event.name,
            Event.date,
            Event.location,
            Event.rating,
            Event.promotion_id,
        )
        .where(Event.name.ilike(pattern))
        .order_by(Event.date.desc())
        .limit(20)
    )
    events = [
        {
            "id": row.id,
            "cagematch_event_id": row.cagematch_event_id,
            "name": row.name,
            "date": str(row.date) if row.date else None,
            "location": row.location,
            "rating": row.rating,
            "promotion_id": row.promotion_id,
        }
        for row in event_result.all()
    ]

    # Search wrestlers with match count
    wrestler_result = await db.execute(
        select(
            Wrestler.id,
            Wrestler.cagematch_wrestler_id,
            Wrestler.name,
            Wrestler.image_url,
            Wrestler.is_linked,
            func.count(MatchParticipant.id).label("match_count"),
        )
        .outerjoin(MatchParticipant, MatchParticipant.wrestler_id == Wrestler.id)
        .where(or_(Wrestler.name.ilike(pattern), Wrestler.alter_egos.ilike(pattern)))
        .group_by(Wrestler.id)
        .order_by(func.count(MatchParticipant.id).desc())
        .limit(20)
    )
    wrestlers = [
        {
            "id": row.id,
            "cagematch_wrestler_id": row.cagematch_wrestler_id,
            "name": row.name,
            "image_url": row.image_url,
            "is_linked": row.is_linked,
            "match_count": row.match_count,
        }
        for row in wrestler_result.all()
    ]

    return {"events": events, "wrestlers": wrestlers}
