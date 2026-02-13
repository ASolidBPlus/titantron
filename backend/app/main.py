from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Depends, FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.config import settings
from app.database import init_db
from app.dependencies import require_admin
from app.routers import admin_auth, auth, browse, libraries, matching, player, search, sync, wrestlers


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings.db_dir.mkdir(parents=True, exist_ok=True)
    await init_db()
    yield


app = FastAPI(
    title="Titantron",
    description="Pro wrestling video organizer powered by Jellyfin",
    version="0.1.0",
    lifespan=lifespan,
)

origins = [o.strip() for o in settings.cors_origins.split(",") if o.strip()]
app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Admin auth (unprotected — must be accessible to show login form)
app.include_router(admin_auth.router, prefix="/api/v1/admin", tags=["admin"])

# Admin-only routers (protected by require_admin)
app.include_router(auth.router, prefix="/api/v1/auth", tags=["auth"], dependencies=[Depends(require_admin)])
app.include_router(libraries.router, prefix="/api/v1/libraries", tags=["libraries"], dependencies=[Depends(require_admin)])
app.include_router(sync.router, prefix="/api/v1/sync", tags=["sync"], dependencies=[Depends(require_admin)])
app.include_router(matching.router, prefix="/api/v1/matching", tags=["matching"], dependencies=[Depends(require_admin)])

# Client-facing routers (no admin auth required)
app.include_router(browse.router, prefix="/api/v1/browse", tags=["browse"])
app.include_router(player.router, prefix="/api/v1/player", tags=["player"])
app.include_router(wrestlers.router, prefix="/api/v1/wrestlers", tags=["wrestlers"])
app.include_router(search.router, prefix="/api/v1/search", tags=["search"])

# Serve static frontend (Docker production mode)
if settings.frontend_dir:
    _frontend_path = Path(settings.frontend_dir)
    if _frontend_path.is_dir():
        # Mount static assets (JS, CSS, images) — but NOT at root to avoid catch-all conflict
        app.mount("/_app", StaticFiles(directory=_frontend_path / "_app"), name="frontend_app")

        @app.get("/{path:path}")
        async def serve_frontend(request: Request, path: str):
            """Serve static files or fall back to index.html for SPA routing."""
            file_path = _frontend_path / path
            if path and file_path.is_file():
                return FileResponse(file_path)
            return FileResponse(_frontend_path / "index.html")
