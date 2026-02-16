from fastapi import APIRouter
from pydantic import BaseModel

from app.config import get_setting, save_runtime_settings
from app.services.admin_session import invalidate_all_sessions
from app.services.ml_client import check_ml_available

router = APIRouter()


class SettingsUpdate(BaseModel):
    jellyfin_public_url: str | None = None
    admin_password: str | None = None
    scrape_rate_limit: float | None = None
    scrape_burst: int | None = None
    path_map_from: str | None = None
    path_map_to: str | None = None
    ml_path_map_to: str | None = None
    ml_audio_enabled: bool | None = None
    ml_service_url: str | None = None
    ml_window_secs: int | None = None


@router.get("/settings")
async def get_app_settings():
    """Return current app settings (password returned as boolean flag only)."""
    return {
        "jellyfin_public_url": get_setting("jellyfin_public_url"),
        "admin_password_is_set": bool(get_setting("admin_password")),
        "scrape_rate_limit": get_setting("scrape_rate_limit"),
        "scrape_burst": get_setting("scrape_burst"),
        "path_map_from": get_setting("path_map_from"),
        "path_map_to": get_setting("path_map_to"),
        "ml_path_map_to": get_setting("ml_path_map_to"),
        "ml_audio_enabled": get_setting("ml_audio_enabled"),
        "ml_service_url": get_setting("ml_service_url"),
        "ml_window_secs": get_setting("ml_window_secs"),
    }


@router.put("/settings")
async def update_app_settings(body: SettingsUpdate):
    """Update app settings and persist to settings.json."""
    updates = {}
    password_changed = False

    if body.jellyfin_public_url is not None:
        updates["jellyfin_public_url"] = body.jellyfin_public_url
    if body.admin_password is not None:
        updates["admin_password"] = body.admin_password
        password_changed = True
    if body.scrape_rate_limit is not None:
        updates["scrape_rate_limit"] = body.scrape_rate_limit
    if body.scrape_burst is not None:
        updates["scrape_burst"] = body.scrape_burst
    if body.path_map_from is not None:
        updates["path_map_from"] = body.path_map_from
    if body.path_map_to is not None:
        updates["path_map_to"] = body.path_map_to
    if body.ml_path_map_to is not None:
        updates["ml_path_map_to"] = body.ml_path_map_to
    if body.ml_audio_enabled is not None:
        updates["ml_audio_enabled"] = body.ml_audio_enabled
    if body.ml_service_url is not None:
        updates["ml_service_url"] = body.ml_service_url
    if body.ml_window_secs is not None:
        updates["ml_window_secs"] = max(2, min(body.ml_window_secs, 60))

    if updates:
        save_runtime_settings(updates)

    if password_changed:
        invalidate_all_sessions()

    return {"success": True, "updated": list(updates.keys())}


@router.get("/ml/health")
async def test_ml_connection(url: str | None = None):
    """Test connection to the ML sidecar container."""
    result = await check_ml_available(url=url)
    return result
