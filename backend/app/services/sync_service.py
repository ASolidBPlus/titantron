import logging
from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.library import Library
from app.models.promotion import Promotion
from app.models.video_item import VideoItem
from app.services.jellyfin_client import JellyfinClient
from app.utils.date_parser import extract_date

logger = logging.getLogger(__name__)


class SyncStatus:
    def __init__(self):
        self.is_running = False
        self.library_id: int | None = None
        self.progress: int = 0
        self.total: int = 0
        self.message: str = ""


# Global sync status (single-user, single process)
sync_status = SyncStatus()


async def sync_library(db: AsyncSession, library_id: int, jellyfin: JellyfinClient) -> None:
    """Pull video items from Jellyfin for a library and extract dates."""
    if sync_status.is_running:
        raise RuntimeError("A sync is already in progress")

    sync_status.is_running = True
    sync_status.library_id = library_id
    sync_status.progress = 0
    sync_status.message = "Starting sync..."

    try:
        # Get library
        result = await db.execute(select(Library).where(Library.id == library_id))
        library = result.scalar_one_or_none()
        if not library:
            raise ValueError(f"Library {library_id} not found")

        sync_status.message = "Fetching items from Jellyfin..."

        # Fetch all items from Jellyfin, paginated
        all_items = []
        start_index = 0
        page_size = 100
        while True:
            items, total = await jellyfin.get_items(
                library.jellyfin_library_id, start_index=start_index, limit=page_size
            )
            sync_status.total = total
            all_items.extend(items)
            start_index += page_size
            if start_index >= total:
                break

        sync_status.message = f"Processing {len(all_items)} items..."

        # Upsert video items
        for i, item in enumerate(all_items):
            sync_status.progress = i + 1

            # Check if already exists
            result = await db.execute(
                select(VideoItem).where(VideoItem.jellyfin_item_id == item.id)
            )
            existing = result.scalar_one_or_none()

            extracted = extract_date(
                premiere_date=item.premiere_date,
                filename=item.filename,
                date_created=item.date_created,
            )

            premiere_dt = None
            if item.premiere_date:
                try:
                    premiere_dt = datetime.fromisoformat(item.premiere_date.replace("Z", "+00:00"))
                except ValueError:
                    pass

            date_added = None
            if item.date_created:
                try:
                    date_added = datetime.fromisoformat(item.date_created.replace("Z", "+00:00"))
                except ValueError:
                    pass

            if existing:
                existing.title = item.name
                existing.filename = item.filename
                existing.path = item.path
                existing.duration_ticks = item.duration_ticks
                existing.premiere_date = premiere_dt
                existing.date_added = date_added
                existing.extracted_date = extracted
                existing.media_source_id = item.media_source_id
                existing.has_trickplay = item.has_trickplay
                existing.image_tag = item.image_tag
            else:
                video = VideoItem(
                    jellyfin_item_id=item.id,
                    title=item.name,
                    filename=item.filename,
                    path=item.path,
                    duration_ticks=item.duration_ticks,
                    premiere_date=premiere_dt,
                    date_added=date_added,
                    extracted_date=extracted,
                    media_source_id=item.media_source_id,
                    has_trickplay=item.has_trickplay,
                    image_tag=item.image_tag,
                    library_id=library.id,
                    match_status="unmatched",
                )
                db.add(video)

        # Update library sync timestamp
        library.last_synced = datetime.now()
        await db.commit()

        sync_status.message = f"Sync complete. {len(all_items)} items processed."
        logger.info(f"Synced {len(all_items)} items for library {library.name}")

    except Exception as e:
        sync_status.message = f"Sync failed: {e}"
        logger.error(f"Sync failed: {e}")
        raise
    finally:
        sync_status.is_running = False
