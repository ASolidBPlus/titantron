from datetime import datetime

from sqlalchemy import BigInteger, DateTime, ForeignKey, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class BellSample(Base):
    __tablename__ = "bell_samples"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    video_item_id: Mapped[int] = mapped_column(Integer, ForeignKey("video_items.id"), nullable=False)
    start_ticks: Mapped[int] = mapped_column(BigInteger, nullable=False)
    end_ticks: Mapped[int] = mapped_column(BigInteger, nullable=False)
    label: Mapped[str | None] = mapped_column(String, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    video_item = relationship("VideoItem", back_populates="bell_samples")
