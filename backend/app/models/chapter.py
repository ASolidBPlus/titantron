from datetime import datetime

from sqlalchemy import BigInteger, DateTime, ForeignKey, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class Chapter(Base):
    __tablename__ = "chapters"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    video_item_id: Mapped[int] = mapped_column(Integer, ForeignKey("video_items.id"), nullable=False)
    match_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("matches.id"), nullable=True)
    title: Mapped[str] = mapped_column(String, nullable=False)
    start_ticks: Mapped[int] = mapped_column(BigInteger, nullable=False)
    end_ticks: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime | None] = mapped_column(DateTime, onupdate=func.now(), nullable=True)

    video_item = relationship("VideoItem", back_populates="chapters")
    match = relationship("Match", back_populates="chapter")
