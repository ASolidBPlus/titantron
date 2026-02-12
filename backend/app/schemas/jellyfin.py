from pydantic import BaseModel


class ConnectRequest(BaseModel):
    url: str
    username: str
    password: str


class ConnectResponse(BaseModel):
    success: bool
    username: str
    user_id: str


class AuthStatusLibrary(BaseModel):
    id: int
    name: str
    promotion_name: str
    video_count: int
    last_synced: str | None


class AuthStatusResponse(BaseModel):
    connected: bool
    jellyfin_url: str | None = None
    username: str | None = None
    libraries: list[AuthStatusLibrary] = []
