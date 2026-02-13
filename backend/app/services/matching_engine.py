import logging
import re
from datetime import date, timedelta

from rapidfuzz import fuzz
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.event import Event
from app.models.promotion import Promotion
from app.models.video_item import VideoItem
from app.services.cagematch_scraper import CagematchScraper, EventSummary

logger = logging.getLogger(__name__)

# Thresholds
AUTO_MATCH_THRESHOLD = 0.75
SUGGEST_THRESHOLD = 0.50


def normalize_wrestling_title(title: str, promotion_abbr: str = "") -> str:
    """Remove noise from wrestling video filenames for comparison."""
    # Strip file extension
    title = re.sub(r"\.\w{2,4}$", "", title)
    # Replace separators with spaces
    title = re.sub(r"[._\-]", " ", title)
    # Remove quality/codec tags
    title = re.sub(
        r"\b(720p|1080p|480p|2160p|4k|web|webdl|hdtv|bluray|dvdrip|"
        r"h264|h265|x264|x265|aac|hevc|sdtv|mp4|mkv|avi)\b",
        "",
        title,
        flags=re.IGNORECASE,
    )
    # Remove scene group suffix (e.g., "-HEEL", "-WH")
    title = re.sub(r"\s*-\s*[A-Z0-9]+$", "", title)
    # Remove promotion prefix if known
    if promotion_abbr:
        title = re.sub(rf"^{re.escape(promotion_abbr)}\s+", "", title, flags=re.IGNORECASE)
    # Common promotion prefixes
    title = re.sub(
        r"^(WWE|AEW|NJPW|ROH|TNA|CMLL|AAA|NOAH|CHIKARA|GCW|ICW|PROGRESS)\s+",
        "",
        title,
        flags=re.IGNORECASE,
    )
    # Remove year if standalone (but keep it as part of event name like "WrestleMania 40")
    title = re.sub(r"\b(19|20)\d{2}\b", "", title)
    # Collapse whitespace
    title = re.sub(r"\s+", " ", title).strip().lower()
    return title


def score_match(
    video_title: str,
    event_name: str,
    video_date: date,
    event_date: date,
    promotion_abbr: str = "",
) -> float:
    """Score how well a video matches a Cagematch event. Returns 0.0-1.0."""
    # 1. Date proximity (0.0 to 0.4)
    day_diff = abs((video_date - event_date).days)
    if day_diff == 0:
        date_score = 0.4
    elif day_diff == 1:
        date_score = 0.3
    elif day_diff == 2:
        date_score = 0.2
    elif day_diff <= 3:
        date_score = 0.1
    else:
        date_score = 0.0

    # 2. Name similarity (0.0 to 0.5)
    clean_video = normalize_wrestling_title(video_title, promotion_abbr)
    clean_event = normalize_wrestling_title(event_name, promotion_abbr)

    if not clean_video or not clean_event:
        name_score = 0.0
    else:
        ratio = fuzz.token_sort_ratio(clean_video, clean_event) / 100.0
        partial = fuzz.partial_ratio(clean_video, clean_event) / 100.0
        name_score = max(ratio, partial) * 0.5

    # 3. Exact date bonus (0.0 or 0.1)
    exact_bonus = 0.1 if day_diff == 0 else 0.0

    return date_score + name_score + exact_bonus


async def find_candidates(
    scraper: CagematchScraper,
    cagematch_promotion_id: int,
    target_date: date,
) -> list[EventSummary]:
    """Find candidate events from Cagematch for a given date.

    Searches the target date's month. If the date is near a month
    boundary (first/last 3 days), also searches the adjacent month.
    """
    # Always search the target month
    events = await scraper.scrape_promotion_events(
        cagematch_promotion_id,
        date_from=target_date.replace(day=1),
        date_to=target_date,
    )

    # If near month boundary, also search adjacent month
    if target_date.day <= 3:
        prev_month = target_date.replace(day=1) - timedelta(days=1)
        extra = await scraper.scrape_promotion_events(
            cagematch_promotion_id,
            date_from=prev_month.replace(day=1),
            date_to=prev_month,
        )
        events.extend(extra)
    elif target_date.day >= 28:
        next_month = target_date.replace(day=28) + timedelta(days=4)
        extra = await scraper.scrape_promotion_events(
            cagematch_promotion_id,
            date_from=next_month.replace(day=1),
            date_to=next_month,
        )
        events.extend(extra)

    # Deduplicate by event ID
    seen = set()
    unique = []
    for ev in events:
        if ev.cagematch_event_id not in seen:
            seen.add(ev.cagematch_event_id)
            unique.append(ev)

    # Filter to within ±3 days of target
    return [
        ev for ev in unique
        if abs((ev.date - target_date).days) <= 3
    ]


async def match_video(
    db: AsyncSession,
    video: VideoItem,
    scraper: CagematchScraper,
    cagematch_promotion_id: int,
    promotion_abbr: str = "",
) -> dict | None:
    """Try to match a single video to a Cagematch event.

    Returns match info dict or None if no good match found.
    """
    if not video.extracted_date:
        return None

    candidates = await find_candidates(scraper, cagematch_promotion_id, video.extracted_date)

    if not candidates:
        return None

    title = video.title or video.filename or ""

    # Score all candidates
    scored = []
    for ev in candidates:
        score = score_match(title, ev.name, video.extracted_date, ev.date, promotion_abbr)
        scored.append((ev, score))

    # Sort by score descending
    scored.sort(key=lambda x: x[1], reverse=True)
    best_event, best_score = scored[0]

    # Special case: if only one event on the exact date, boost confidence
    exact_date_events = [ev for ev in candidates if ev.date == video.extracted_date]
    if len(exact_date_events) == 1 and exact_date_events[0].cagematch_event_id == best_event.cagematch_event_id:
        best_score = max(best_score, 0.80)

    # Check or create the event in our DB
    result = await db.execute(
        select(Event).where(Event.cagematch_event_id == best_event.cagematch_event_id)
    )
    db_event = result.scalar_one_or_none()
    if not db_event:
        # Get promotion ID from DB
        promo_result = await db.execute(
            select(Promotion).where(Promotion.cagematch_id == cagematch_promotion_id)
        )
        promo = promo_result.scalar_one_or_none()
        if not promo:
            return None

        db_event = Event(
            cagematch_event_id=best_event.cagematch_event_id,
            name=best_event.name,
            date=best_event.date,
            promotion_id=promo.id,
            location=best_event.location,
            rating=best_event.rating,
            votes=best_event.votes,
        )
        db.add(db_event)
        await db.flush()

    # Determine match status
    if best_score >= AUTO_MATCH_THRESHOLD:
        status = "auto_matched"
    elif best_score >= SUGGEST_THRESHOLD:
        status = "suggested"
    else:
        return None

    # Update the video item
    video.matched_event_id = db_event.id
    video.match_confidence = best_score
    video.match_status = status

    return {
        "event_id": db_event.id,
        "event_name": best_event.name,
        "event_date": str(best_event.date),
        "score": best_score,
        "status": status,
        "candidates": [
            {
                "cagematch_event_id": ev.cagematch_event_id,
                "name": ev.name,
                "date": str(ev.date),
                "score": sc,
            }
            for ev, sc in scored[:5]
        ],
    }


async def match_library(
    db: AsyncSession,
    library_id: int,
    scraper: CagematchScraper,
    on_progress: callable = None,
) -> dict:
    """Run matching for all unmatched videos in a library.

    on_progress(current, total, video_title, status, log_message) is called
    after each video is processed.
    """
    from app.models.library import Library

    result = await db.execute(select(Library).where(Library.id == library_id))
    library = result.scalar_one_or_none()
    if not library:
        raise ValueError(f"Library {library_id} not found")

    promo_result = await db.execute(
        select(Promotion).where(Promotion.id == library.promotion_id)
    )
    promotion = promo_result.scalar_one_or_none()
    if not promotion:
        raise ValueError("Promotion not found")

    # Get unmatched videos with extracted dates
    result = await db.execute(
        select(VideoItem).where(
            VideoItem.library_id == library_id,
            VideoItem.match_status == "unmatched",
            VideoItem.extracted_date.isnot(None),
        )
    )
    videos = result.scalars().all()

    stats = {"total": len(videos), "auto_matched": 0, "suggested": 0, "unmatched": 0}

    if on_progress:
        on_progress(0, len(videos), "", "", f"Starting matching for {len(videos)} videos (promotion: {promotion.name}, cagematch_id: {promotion.cagematch_id})")

    for i, video in enumerate(videos):
        title = video.title or video.filename or "Unknown"
        try:
            match_result = await match_video(
                db, video, scraper, promotion.cagematch_id, promotion.abbreviation or ""
            )
            if match_result:
                if match_result["status"] == "auto_matched":
                    stats["auto_matched"] += 1
                    log = f"Auto-matched: {title} -> {match_result['event_name']} ({match_result['score']:.0%})"
                else:
                    stats["suggested"] += 1
                    log = f"Suggested: {title} -> {match_result['event_name']} ({match_result['score']:.0%})"
                status = match_result["status"]
            else:
                stats["unmatched"] += 1
                log = f"No match: {title} (date: {video.extracted_date})"
                status = "unmatched"

            if on_progress:
                on_progress(i + 1, len(videos), title, status, log)

        except Exception as e:
            logger.error(f"Failed to match {title}: {e}")
            stats["unmatched"] += 1
            if on_progress:
                on_progress(i + 1, len(videos), title, "error", f"Error: {title} - {e}")

    await db.commit()
    return stats
