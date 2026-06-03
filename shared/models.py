"""SQLAlchemy 2.0 ORM models."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


class IPUniverse(Base):
    __tablename__ = "ip_universe"

    ip: Mapped[str] = mapped_column(String(64), primary_key=True)
    first_seen: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    last_seen: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    ua: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    country: Mapped[Optional[str]] = mapped_column(String(8), nullable=True)
    fingerprint_json: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    request_count: Mapped[int] = mapped_column(Integer, default=0)
    token_count_in: Mapped[int] = mapped_column(Integer, default=0)
    token_count_out: Mapped[int] = mapped_column(Integer, default=0)


class Page(Base):
    __tablename__ = "page"
    __table_args__ = (UniqueConstraint("ip", "path", name="uq_page_ip_path"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    ip: Mapped[str] = mapped_column(
        String(64), ForeignKey("ip_universe.ip", ondelete="CASCADE"), index=True
    )
    path: Mapped[str] = mapped_column(Text)
    content_type: Mapped[str] = mapped_column(String(64))
    body: Mapped[str] = mapped_column(Text)
    generated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    tokens_in: Mapped[int] = mapped_column(Integer, default=0)
    tokens_out: Mapped[int] = mapped_column(Integer, default=0)


class LinkEdge(Base):
    __tablename__ = "link_edge"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    ip: Mapped[str] = mapped_column(
        String(64), ForeignKey("ip_universe.ip", ondelete="CASCADE"), index=True
    )
    from_path: Mapped[str] = mapped_column(Text)
    to_path: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)


class RequestLog(Base):
    __tablename__ = "request_log"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    ip: Mapped[str] = mapped_column(
        String(64), ForeignKey("ip_universe.ip", ondelete="CASCADE"), index=True
    )
    method: Mapped[str] = mapped_column(String(8))
    path: Mapped[str] = mapped_column(Text)
    status: Mapped[int] = mapped_column(Integer)
    ua: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    referer: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, index=True)
    was_generated: Mapped[bool] = mapped_column(Boolean, default=False)
    was_bait: Mapped[bool] = mapped_column(Boolean, default=False)
    post_body: Mapped[Optional[str]] = mapped_column(Text, nullable=True)


class CredentialAttempt(Base):
    __tablename__ = "credential_attempt"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    ip: Mapped[str] = mapped_column(
        String(64), ForeignKey("ip_universe.ip", ondelete="CASCADE"), index=True
    )
    path: Mapped[str] = mapped_column(Text)
    username: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    password: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    extra_json: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, index=True)
