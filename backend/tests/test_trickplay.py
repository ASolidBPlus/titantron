"""Test the trickplay proxy endpoint handles .jpg filenames correctly."""

from unittest.mock import AsyncMock, patch

import pytest

from app.database import Base, get_db
from app.models.video_item import VideoItem
from app.routers.auth import get_jellyfin_client


@pytest.fixture
def mock_jellyfin():
    client = AsyncMock()
    client.server_url = "http://jellyfin:8096"
    client.access_token = "test-token"
    client.device_id = "test-device"
    client.user_id = "test-user"
    # Return a fake 1x1 JPEG
    client._request_bytes = AsyncMock(
        return_value=b"\xff\xd8\xff\xe0\x00\x10JFIF"
    )
    return client


@pytest.mark.asyncio
async def test_trickplay_with_jpg_extension(client, db, mock_jellyfin):
    """The exact bug: frontend requests /trickplay/320/46185.jpg but the old
    route had `index: int` which rejects '46185.jpg' with a 422."""
    from app.main import app
    from app.models.library import Library
    from app.models.promotion import Promotion

    app.dependency_overrides[get_jellyfin_client] = lambda: mock_jellyfin

    # Create required DB records
    promo = Promotion(id=1, cagematch_id=1, name="Test", abbreviation="TST")
    db.add(promo)
    await db.flush()

    lib = Library(id=1, jellyfin_library_id="lib1", name="Test Lib", promotion_id=1)
    db.add(lib)
    await db.flush()

    video = VideoItem(
        id=59,
        jellyfin_item_id="abc123",
        title="Test Show",
        library_id=1,
        match_status="unmatched",
    )
    db.add(video)
    await db.commit()

    # This is the exact URL pattern that was returning 422
    resp = await client.get("/api/v1/player/59/trickplay/320/46185.jpg")

    assert resp.status_code == 200, f"Expected 200, got {resp.status_code}: {resp.text}"
    assert resp.headers["content-type"] == "image/jpeg"

    # Verify it called Jellyfin with the correct path
    mock_jellyfin._request_bytes.assert_called_once_with(
        "/Videos/abc123/Trickplay/320/46185.jpg"
    )


@pytest.mark.asyncio
async def test_trickplay_video_not_found(client, db, mock_jellyfin):
    from app.main import app

    app.dependency_overrides[get_jellyfin_client] = lambda: mock_jellyfin

    resp = await client.get("/api/v1/player/999/trickplay/320/1.jpg")
    assert resp.status_code == 404
