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

    promotion = relationship("Promotion", back_populates="libraries")
    video_items = relationship("VideoItem", back_populates="library")
