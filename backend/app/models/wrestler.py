from datetime import date, datetime

from sqlalchemy import Boolean, Date, DateTime, Float, Integer, String
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

    # Profile fields (scraped from Cagematch)
    birth_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    birth_place: Mapped[str | None] = mapped_column(String, nullable=True)
    height: Mapped[str | None] = mapped_column(String, nullable=True)
    weight: Mapped[str | None] = mapped_column(String, nullable=True)
    style: Mapped[str | None] = mapped_column(String, nullable=True)
    debut: Mapped[str | None] = mapped_column(String, nullable=True)
    roles: Mapped[str | None] = mapped_column(String, nullable=True)
    nicknames: Mapped[str | None] = mapped_column(String, nullable=True)
    signature_moves: Mapped[str | None] = mapped_column(String, nullable=True)
    trainers: Mapped[str | None] = mapped_column(String, nullable=True)
    alter_egos: Mapped[str | None] = mapped_column(String, nullable=True)
    rating: Mapped[float | None] = mapped_column(Float, nullable=True)
    votes: Mapped[int | None] = mapped_column(Integer, nullable=True)

    match_participants = relationship("MatchParticipant", back_populates="wrestler")
