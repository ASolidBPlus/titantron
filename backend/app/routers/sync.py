from fastapi import APIRouter

from app.schemas.cagematch import SyncStatusResponse
from app.services.sync_service import sync_status

router = APIRouter()


@router.get("/status", response_model=SyncStatusResponse)
async def get_sync_status():
    """Get the current sync status."""
    return SyncStatusResponse(
        is_running=sync_status.is_running,
        library_id=sync_status.library_id,
        progress=sync_status.progress,
        total=sync_status.total,
        message=sync_status.message,
    )
