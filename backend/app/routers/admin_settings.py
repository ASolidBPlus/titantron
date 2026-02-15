from fastapi import APIRouter
from pydantic import BaseModel

from app.config import get_setting, save_runtime_settings
from app.services.admin_session import invalidate_all_sessions

router = APIRouter()


class SettingsUpdate(BaseModel):
    jellyfin_public_url: str | None = None
    admin_password: str | None = None
    scrape_rate_limit: float | None = None
    scrape_burst: int | None = None
    path_map_from: str | None = None
    path_map_to: str | None = None


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

    if updates:
        save_runtime_settings(updates)

    if password_changed:
        invalidate_all_sessions()

    return {"success": True, "updated": list(updates.keys())}
