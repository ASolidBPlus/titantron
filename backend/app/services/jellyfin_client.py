from __future__ import annotations

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

    async def _request_bytes(self, path: str) -> bytes:
        """Download binary data (e.g., trickplay sprite sheet images)."""
        url = f"{self.server_url}{path}"
        headers = {"Authorization": self._auth_header()}
        async with aiohttp.ClientSession() as session:
            async with session.get(url, headers=headers) as resp:
                resp.raise_for_status()
                return await resp.read()

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
                )
            )
        return items, total

    async def get_playback_info(self, item_id: str, media_source_id: str) -> dict:
        """Get playback info — lets Jellyfin decide direct play vs transcode."""
        return await self._request(
            "POST",
            f"/Items/{item_id}/PlaybackInfo",
            params={
                "UserId": self.user_id,
                "StartTimeTicks": "0",
                "IsPlayback": "true",
                "AutoOpenLiveStream": "true",
                "MediaSourceId": media_source_id,
            },
            json={
                "DeviceProfile": {
                    "DirectPlayProfiles": [
                        {
                            "Container": "mp4,webm",
                            "Type": "Video",
                            "VideoCodec": "h264,h265,hevc,vp8,vp9,av1",
                            "AudioCodec": "aac,mp3,opus,flac,vorbis",
                        }
                    ],
                    "TranscodingProfiles": [
                        {
                            "Container": "ts",
                            "Type": "Video",
                            "AudioCodec": "aac,mp3",
                            "VideoCodec": "h264",
                            "Context": "Streaming",
                            "Protocol": "hls",
                            "BreakOnNonKeyFrames": True,
                        }
                    ],
                }
            },
        )

    async def get_item_detail(self, item_id: str) -> dict:
        """Get full item detail including Trickplay metadata."""
        return await self._request(
            "GET",
            f"/Users/{self.user_id}/Items/{item_id}",
            params={"Fields": "Trickplay,MediaSources"},
        )

    async def _request_no_body(self, method: str, path: str, json: dict | None = None) -> None:
        """Make a request that returns no body (e.g. 204)."""
        url = f"{self.server_url}{path}"
        headers = {"Authorization": self._auth_header()}
        async with aiohttp.ClientSession() as session:
            async with session.request(method, url, json=json, headers=headers) as resp:
                resp.raise_for_status()

    async def update_item_chapters(self, item_id: str, chapters: list[dict]) -> None:
        """Push chapters to Jellyfin via UpdateItem (POST /Items/{itemId})."""
        # Fetch existing item data so we only override Chapters
        item = await self._request("GET", f"/Users/{self.user_id}/Items/{item_id}")
        item["Chapters"] = chapters
        await self._request_no_body("POST", f"/Items/{item_id}", json=item)

    async def report_playback_start(self, body: dict) -> None:
        await self._request_no_body("POST", "/Sessions/Playing", json=body)

    async def report_playback_progress(self, body: dict) -> None:
        await self._request_no_body("POST", "/Sessions/Playing/Progress", json=body)

    async def report_playback_stopped(self, body: dict) -> None:
        await self._request_no_body("POST", "/Sessions/Playing/Stopped", json=body)
