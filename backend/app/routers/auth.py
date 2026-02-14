import json
import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database import get_db
from app.models.library import Library
from app.models.promotion import Promotion
from app.models.video_item import VideoItem
from app.schemas.jellyfin import AuthStatusLibrary, AuthStatusResponse, ConnectRequest, ConnectResponse
from app.services.jellyfin_client import JellyfinClient

router = APIRouter()

# Persist connection info next to the database (survives container restarts)
_CONN_FILE = settings.db_dir / "connection.json"


def _load_connection() -> dict:
    if _CONN_FILE.exists():
        return json.loads(_CONN_FILE.read_text())
    return {}


def _save_connection(data: dict):
    _CONN_FILE.parent.mkdir(parents=True, exist_ok=True)
    _CONN_FILE.write_text(json.dumps(data))


def _clear_connection():
    if _CONN_FILE.exists():
        _CONN_FILE.unlink()


def get_jellyfin_client() -> JellyfinClient:
    conn = _load_connection()
    if not conn.get("url"):
        raise HTTPException(status_code=401, detail="Not connected to Jellyfin")
    return JellyfinClient(
        server_url=conn["url"],
        access_token=conn["token"],
        user_id=conn["user_id"],
        device_id=conn.get("device_id", ""),
    )


@router.post("/connect", response_model=ConnectResponse)
async def connect(request: ConnectRequest):
    """Authenticate with a Jellyfin server and persist the connection."""
    client = JellyfinClient(device_id=str(uuid.uuid4()))
    try:
        result = await client.authenticate(request.url, request.username, request.password)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Failed to connect: {e}")

    _save_connection(
        {
            "url": request.url.rstrip("/"),
            "token": result.access_token,
            "user_id": result.user_id,
            "username": result.username,
            "device_id": client.device_id,
        }
    )

    return ConnectResponse(success=True, username=result.username, user_id=result.user_id)


@router.get("/status", response_model=AuthStatusResponse)
async def status(db: AsyncSession = Depends(get_db)):
    """Check current connection status and list configured libraries."""
    conn = _load_connection()
    if not conn.get("url"):
        return AuthStatusResponse(connected=False)

    # Get configured libraries with video counts
    result = await db.execute(
        select(
            Library.id,
            Library.name,
            Promotion.name.label("promotion_name"),
            func.count(VideoItem.id).label("video_count"),
            Library.last_synced,
        )
        .outerjoin(Promotion, Library.promotion_id == Promotion.id)
        .outerjoin(VideoItem, VideoItem.library_id == Library.id)
        .group_by(Library.id)
    )
    rows = result.all()

    libraries = [
        AuthStatusLibrary(
            id=row.id,
            name=row.name,
            promotion_name=row.promotion_name or "Unknown",
            video_count=row.video_count,
            last_synced=row.last_synced.isoformat() if row.last_synced else None,
        )
        for row in rows
    ]

    return AuthStatusResponse(
        connected=True,
        jellyfin_url=conn.get("url"),
        username=conn.get("username"),
        libraries=libraries,
    )


@router.post("/disconnect")
async def disconnect():
    """Clear the Jellyfin connection."""
    _clear_connection()
    return {"success": True}
