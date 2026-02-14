from datetime import date, datetime

from sqlalchemy import BigInteger, Date, DateTime, Float, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class VideoItem(Base):
    __tablename__ = "video_items"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    jellyfin_item_id: Mapped[str] = mapped_column(String, unique=True, nullable=False)
    title: Mapped[str | None] = mapped_column(String, nullable=True)
    filename: Mapped[str | None] = mapped_column(String, nullable=True)
    path: Mapped[str | None] = mapped_column(String, nullable=True)
    duration_ticks: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    date_added: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    premiere_date: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    extracted_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    media_source_id: Mapped[str | None] = mapped_column(String, nullable=True)
    library_id: Mapped[int] = mapped_column(Integer, ForeignKey("libraries.id"), nullable=False)
    matched_event_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("events.id"), nullable=True)
    match_confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    match_status: Mapped[str] = mapped_column(String, default="unmatched")

    library = relationship("Library", back_populates="video_items")
    matched_event = relationship("Event", back_populates="video_items")
    chapters = relationship("Chapter", back_populates="video_item", order_by="Chapter.start_ticks")
    analysis_result = relationship("AnalysisResult", back_populates="video_item", uselist=False)
