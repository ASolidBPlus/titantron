from sqlalchemy import Float, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class Match(Base):
    __tablename__ = "matches"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    cagematch_match_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    event_id: Mapped[int] = mapped_column(Integer, ForeignKey("events.id"), nullable=False)
    match_number: Mapped[int] = mapped_column(Integer, nullable=False)
    match_type: Mapped[str | None] = mapped_column(String, nullable=True)
    stipulation: Mapped[str | None] = mapped_column(String, nullable=True)
    title_name: Mapped[str | None] = mapped_column(String, nullable=True)
    result: Mapped[str | None] = mapped_column(String, nullable=True)
    rating: Mapped[float | None] = mapped_column(Float, nullable=True)
    votes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    duration: Mapped[str | None] = mapped_column(String, nullable=True)

    event = relationship("Event", back_populates="matches")
    participants = relationship("MatchParticipant", back_populates="match", cascade="all, delete-orphan")
    chapter = relationship("Chapter", back_populates="match", uselist=False)


class MatchParticipant(Base):
    __tablename__ = "match_participants"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    match_id: Mapped[int] = mapped_column(Integer, ForeignKey("matches.id"), nullable=False)
    wrestler_id: Mapped[int] = mapped_column(Integer, ForeignKey("wrestlers.id"), nullable=False)
    side: Mapped[int | None] = mapped_column(Integer, nullable=True)
    team_name: Mapped[str | None] = mapped_column(String, nullable=True)
    is_winner: Mapped[bool] = mapped_column(default=False)
    role: Mapped[str] = mapped_column(String, default="competitor")

    match = relationship("Match", back_populates="participants")
    wrestler = relationship("Wrestler", back_populates="match_participants")
