import os
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class Library(Base):
    __tablename__ = "libraries"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    jellyfin_library_id: Mapped[str] = mapped_column(String, unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String, nullable=False)
    promotion_id: Mapped[int] = mapped_column(Integer, ForeignKey("promotions.id"), nullable=False)
    last_synced: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    jellyfin_path: Mapped[str | None] = mapped_column(String, nullable=True)
    local_path: Mapped[str | None] = mapped_column(String, nullable=True)

    promotion = relationship("Promotion", back_populates="libraries")
    video_items = relationship("VideoItem", back_populates="library")

    def resolve_local_path(self, video_path: str) -> str | None:
        """Map a Jellyfin file path to a local path using the configured path mapping."""
        if not self.jellyfin_path or not self.local_path or not video_path:
            return None
        if not video_path.startswith(self.jellyfin_path):
            return None
        relative = video_path[len(self.jellyfin_path):].lstrip("/")
        return os.path.join(self.local_path, relative)
