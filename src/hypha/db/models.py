"""SQLAlchemy models. See SPEC.md §8."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import BigInteger, DateTime, Float, Integer, String, Text, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class Click(Base):
    """Referral redirect events for revenue attribution."""

    __tablename__ = "clicks"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    token: Mapped[str] = mapped_column(String(72), index=True)
    venue: Mapped[str] = mapped_column(String(32))
    target: Mapped[str] = mapped_column(Text)
    user_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class User(Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)   # tg user id
    username: Mapped[str | None] = mapped_column(String(64), nullable=True)
    analyses: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class LabeledAddress(Base):
    """The moat: pools, burn, lockers, CEX, known bundlers — excluded from holder analysis."""

    __tablename__ = "labeled_addresses"
    address: Mapped[str] = mapped_column(String(72), primary_key=True)
    kind: Mapped[str] = mapped_column(String(32))    # pool | burn | locker | cex | bundler
    label: Mapped[str] = mapped_column(String(128))
    source: Mapped[str | None] = mapped_column(String(64), nullable=True)


class ScoreHistory(Base):
    __tablename__ = "score_history"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    token: Mapped[str] = mapped_column(String(72), index=True)
    score: Mapped[int] = mapped_column(Integer)
    raw: Mapped[float] = mapped_column(Float)
    tier: Mapped[str] = mapped_column(String(32))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
