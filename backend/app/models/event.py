from datetime import date, datetime

from sqlalchemy import Date, DateTime, Float, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class Event(Base):
    __tablename__ = "events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    cagematch_event_id: Mapped[int] = mapped_column(Integer, unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String, nullable=False)
    date: Mapped[date] = mapped_column(Date, nullable=False)
    promotion_id: Mapped[int] = mapped_column(Integer, ForeignKey("promotions.id"), nullable=False)
    event_type: Mapped[str | None] = mapped_column(String, nullable=True)
    location: Mapped[str | None] = mapped_column(String, nullable=True)
    arena: Mapped[str | None] = mapped_column(String, nullable=True)
    rating: Mapped[float | None] = mapped_column(Float, nullable=True)
    votes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    last_scraped: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    promotion = relationship("Promotion", back_populates="events")
    matches = relationship("Match", back_populates="event", order_by="Match.match_number")
    video_items = relationship("VideoItem", back_populates="matched_event")
