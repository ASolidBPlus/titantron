from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import settings
from app.database import init_db
from app.routers import auth, libraries, sync


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

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router, prefix="/api/v1/auth", tags=["auth"])
app.include_router(libraries.router, prefix="/api/v1/libraries", tags=["libraries"])
app.include_router(sync.router, prefix="/api/v1/sync", tags=["sync"])
