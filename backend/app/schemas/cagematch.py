from pydantic import BaseModel


class ConfigureLibraryRequest(BaseModel):
    jellyfin_library_id: str
    jellyfin_library_name: str
    cagematch_promotion_id: int
    promotion_name: str
    promotion_abbreviation: str = ""
    jellyfin_path: str = ""
    local_path: str = ""


class ConfiguredLibraryResponse(BaseModel):
    id: int
    jellyfin_library_id: str
    name: str
    promotion_id: int
    promotion_name: str
    promotion_abbreviation: str
    video_count: int
    last_synced: str | None
    jellyfin_path: str | None = None
    local_path: str | None = None


class SyncStatusResponse(BaseModel):
    is_running: bool
    library_id: int | None = None
    progress: int | None = None
    total: int | None = None
    message: str | None = None
