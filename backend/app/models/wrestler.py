from datetime import datetime

from sqlalchemy import Boolean, DateTime, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class Wrestler(Base):
    __tablename__ = "wrestlers"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    cagematch_wrestler_id: Mapped[int | None] = mapped_column(Integer, unique=True, nullable=True)
    name: Mapped[str] = mapped_column(String, nullable=False)
    image_url: Mapped[str | None] = mapped_column(String, nullable=True)
    is_linked: Mapped[bool] = mapped_column(Boolean, default=True)
    last_scraped: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    match_participants = relationship("MatchParticipant", back_populates="wrestler")
