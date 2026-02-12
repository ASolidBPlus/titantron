import uuid
from dataclasses import dataclass

import aiohttp

from app.config import settings


@dataclass
class AuthResult:
    access_token: str
    user_id: str
    username: str


@dataclass
class LibraryView:
    id: str
    name: str
    collection_type: str


@dataclass
class ItemSummary:
    id: str
    name: str
    path: str | None
    filename: str | None
    premiere_date: str | None
    date_created: str | None
    duration_ticks: int | None
    media_source_id: str | None
    has_trickplay: bool


class JellyfinClient:
    def __init__(
        self,
        server_url: str | None = None,
        access_token: str | None = None,
        user_id: str | None = None,
        device_id: str | None = None,
    ):
        self.server_url = (server_url or settings.jellyfin_url).rstrip("/")
        self.access_token = access_token or settings.jellyfin_token
        self.user_id = user_id or settings.jellyfin_user_id
        self.device_id = device_id or settings.jellyfin_device_id or str(uuid.uuid4())

    def _auth_header(self) -> str:
        parts = [
            'MediaBrowser Client="Titantron"',
            'Device="Web"',
            f'DeviceId="{self.device_id}"',
            'Version="0.1.0"',
        ]
        if self.access_token:
            parts.append(f'Token="{self.access_token}"')
        return ", ".join(parts)

    async def _request(
        self, method: str, path: str, json: dict | None = None, params: dict | None = None
    ) -> dict | list:
        url = f"{self.server_url}{path}"
        headers = {"Authorization": self._auth_header()}
        async with aiohttp.ClientSession() as session:
            async with session.request(method, url, json=json, params=params, headers=headers) as resp:
                resp.raise_for_status()
                return await resp.json()

    async def authenticate(self, server_url: str, username: str, password: str) -> AuthResult:
        self.server_url = server_url.rstrip("/")
        data = await self._request("POST", "/Users/AuthenticateByName", json={"Username": username, "Pw": password})
        self.access_token = data["AccessToken"]
        self.user_id = data["User"]["Id"]
        return AuthResult(
            access_token=data["AccessToken"],
            user_id=data["User"]["Id"],
            username=data["User"]["Name"],
        )

    async def get_views(self) -> list[LibraryView]:
        data = await self._request("GET", f"/Users/{self.user_id}/Views")
        views = []
        for item in data.get("Items", []):
            views.append(
                LibraryView(
                    id=item["Id"],
                    name=item["Name"],
                    collection_type=item.get("CollectionType", "unknown"),
                )
            )
        return views

    async def get_items(
        self, parent_id: str, start_index: int = 0, limit: int = 100
    ) -> tuple[list[ItemSummary], int]:
        params = {
            "ParentId": parent_id,
            "IncludeItemTypes": "Movie,Video",
            "Fields": "Path,MediaSources,DateCreated,PremiereDate",
            "Recursive": "true",
            "SortBy": "PremiereDate,SortName",
            "SortOrder": "Descending",
            "StartIndex": str(start_index),
            "Limit": str(limit),
        }
        data = await self._request("GET", f"/Users/{self.user_id}/Items", params=params)
        total = data.get("TotalRecordCount", 0)
        items = []
        for item in data.get("Items", []):
            path = item.get("Path", "")
            filename = path.rsplit("/", 1)[-1] if path else path.rsplit("\\", 1)[-1] if path else None
            media_source_id = None
            if item.get("MediaSources"):
                media_source_id = item["MediaSources"][0].get("Id")
            has_trickplay = bool(item.get("Trickplay"))
            items.append(
                ItemSummary(
                    id=item["Id"],
                    name=item.get("Name", ""),
                    path=path or None,
                    filename=filename,
                    premiere_date=item.get("PremiereDate"),
                    date_created=item.get("DateCreated"),
                    duration_ticks=item.get("RunTimeTicks"),
                    media_source_id=media_source_id,
                    has_trickplay=has_trickplay,
                )
            )
        return items, total
