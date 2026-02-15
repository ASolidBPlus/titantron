import asyncio
from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import async_session, get_db
from app.models.library import Library
from app.models.promotion import Promotion
from app.models.video_item import VideoItem
from app.routers.auth import get_jellyfin_client
from app.schemas.cagematch import ConfigureLibraryRequest, ConfiguredLibraryResponse, UpdateLibraryRequest
from app.services.jellyfin_client import JellyfinClient
from app.services.sync_service import sync_library, sync_status

router = APIRouter()


@router.get("/jellyfin")
async def list_jellyfin_libraries(client: JellyfinClient = Depends(get_jellyfin_client)):
    """List available libraries from the connected Jellyfin server."""
    try:
        views = await client.get_views()
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Failed to fetch libraries: {e}")

    # Virtual folders may require Jellyfin admin — don't fail if unavailable
    folder_paths: dict[str, list[str]] = {}
    try:
        virtual_folders = await client.get_virtual_folders()
        for vf in virtual_folders:
            folder_paths[vf["name"]] = vf["paths"]
    except Exception:
        pass

    return [
        {
            "id": v.id,
            "name": v.name,
            "collection_type": v.collection_type,
            "paths": folder_paths.get(v.name, []),
        }
        for v in views
    ]


@router.get("", response_model=list[ConfiguredLibraryResponse])
async def list_configured_libraries(db: AsyncSession = Depends(get_db)):
    """List all configured library-promotion mappings."""
    result = await db.execute(
        select(
            Library.id,
            Library.jellyfin_library_id,
            Library.name,
            Library.promotion_id,
            Library.jellyfin_path,
            Library.local_path,
            Promotion.name.label("promotion_name"),
            Promotion.abbreviation.label("promotion_abbreviation"),
            func.count(VideoItem.id).label("video_count"),
            Library.last_synced,
        )
        .outerjoin(Promotion, Library.promotion_id == Promotion.id)
        .outerjoin(VideoItem, VideoItem.library_id == Library.id)
        .group_by(Library.id)
    )
    rows = result.all()

    return [
        ConfiguredLibraryResponse(
            id=row.id,
            jellyfin_library_id=row.jellyfin_library_id,
            name=row.name,
            promotion_id=row.promotion_id,
            promotion_name=row.promotion_name or "Unknown",
            promotion_abbreviation=row.promotion_abbreviation or "",
            video_count=row.video_count,
            last_synced=row.last_synced.isoformat() if row.last_synced else None,
            jellyfin_path=row.jellyfin_path,
            local_path=row.local_path,
        )
        for row in rows
    ]


@router.post("", response_model=ConfiguredLibraryResponse)
async def configure_library(request: ConfigureLibraryRequest, db: AsyncSession = Depends(get_db)):
    """Map a Jellyfin library to a Cagematch promotion."""
    # Check if already configured
    result = await db.execute(
        select(Library).where(Library.jellyfin_library_id == request.jellyfin_library_id)
    )
    if result.scalar_one_or_none():
        raise HTTPException(status_code=409, detail="Library already configured")

    # Get or create promotion
    result = await db.execute(
        select(Promotion).where(Promotion.cagematch_id == request.cagematch_promotion_id)
    )
    promotion = result.scalar_one_or_none()
    if not promotion:
        promotion = Promotion(
            cagematch_id=request.cagematch_promotion_id,
            name=request.promotion_name,
            abbreviation=request.promotion_abbreviation,
        )
        db.add(promotion)
        await db.flush()

    library = Library(
        jellyfin_library_id=request.jellyfin_library_id,
        name=request.jellyfin_library_name,
        promotion_id=promotion.id,
        jellyfin_path=request.jellyfin_path or None,
        local_path=request.local_path or None,
    )
    db.add(library)
    await db.commit()
    await db.refresh(library)

    return ConfiguredLibraryResponse(
        id=library.id,
        jellyfin_library_id=library.jellyfin_library_id,
        name=library.name,
        promotion_id=promotion.id,
        promotion_name=promotion.name,
        promotion_abbreviation=promotion.abbreviation or "",
        video_count=0,
        last_synced=None,
        jellyfin_path=library.jellyfin_path,
        local_path=library.local_path,
    )


@router.patch("/{library_id}", response_model=ConfiguredLibraryResponse)
async def update_library(library_id: int, body: UpdateLibraryRequest, db: AsyncSession = Depends(get_db)):
    """Update a library's path mapping."""
    result = await db.execute(select(Library).where(Library.id == library_id))
    library = result.scalar_one_or_none()
    if not library:
        raise HTTPException(status_code=404, detail="Library not found")

    if body.jellyfin_path is not None:
        library.jellyfin_path = body.jellyfin_path or None
    if body.local_path is not None:
        library.local_path = body.local_path or None

    await db.commit()
    await db.refresh(library)

    # Fetch promotion info for response
    result = await db.execute(
        select(
            Promotion.name, Promotion.abbreviation,
            func.count(VideoItem.id).label("video_count"),
        )
        .outerjoin(VideoItem, VideoItem.library_id == Library.id)
        .where(Promotion.id == library.promotion_id)
        .group_by(Promotion.id)
    )
    row = result.one()

    return ConfiguredLibraryResponse(
        id=library.id,
        jellyfin_library_id=library.jellyfin_library_id,
        name=library.name,
        promotion_id=library.promotion_id,
        promotion_name=row.name or "Unknown",
        promotion_abbreviation=row.abbreviation or "",
        video_count=row.video_count,
        last_synced=library.last_synced.isoformat() if library.last_synced else None,
        jellyfin_path=library.jellyfin_path,
        local_path=library.local_path,
    )


@router.delete("/{library_id}")
async def delete_library(library_id: int, db: AsyncSession = Depends(get_db)):
    """Remove a library configuration."""
    result = await db.execute(select(Library).where(Library.id == library_id))
    library = result.scalar_one_or_none()
    if not library:
        raise HTTPException(status_code=404, detail="Library not found")

    await db.delete(library)
    await db.commit()
    return {"success": True}


async def _run_sync(library_id: int, client: JellyfinClient):
    """Background task to run sync."""
    async with async_session() as db:
        try:
            await sync_library(db, library_id, client)
        except Exception:
            pass  # Error is captured in sync_status


@router.post("/{library_id}/sync")
async def trigger_sync(
    library_id: int,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
    client: JellyfinClient = Depends(get_jellyfin_client),
):
    """Trigger a sync for a specific library."""
    if sync_status.is_running:
        raise HTTPException(status_code=409, detail="A sync is already in progress")

    result = await db.execute(select(Library).where(Library.id == library_id))
    if not result.scalar_one_or_none():
        raise HTTPException(status_code=404, detail="Library not found")

    background_tasks.add_task(_run_sync, library_id, client)
    return {"message": "Sync started"}


@router.get("/browse-dirs")
async def browse_directories(path: str = Query("/", description="Directory path to list")):
    """List subdirectories at a given path for the file browser."""
    target = Path(path)
    if not target.is_absolute():
        raise HTTPException(status_code=400, detail="Path must be absolute")
    if not target.is_dir():
        raise HTTPException(status_code=404, detail="Directory not found")

    dirs = []
    try:
        for entry in sorted(target.iterdir()):
            if entry.is_dir() and not entry.name.startswith("."):
                dirs.append({"name": entry.name, "path": str(entry)})
    except PermissionError:
        raise HTTPException(status_code=403, detail="Permission denied")

    return {"path": str(target), "parent": str(target.parent) if target != target.parent else None, "directories": dirs}
