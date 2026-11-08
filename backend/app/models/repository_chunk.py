from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class RepositoryChunk(Base):
    __tablename__ = "repository_chunks"

    id: Mapped[int] = mapped_column(
        Integer,
        primary_key=True,
        index=True,
    )

    repository_id: Mapped[int] = mapped_column(
        ForeignKey("repositories.id"),
        nullable=False,
        index=True,
    )

    file_path: Mapped[str] = mapped_column(
        String(1000),
        nullable=False,
        index=True,
    )

    symbol_name: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
        index=True,
    )

    symbol_kind: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        index=True,
    )

    start_line: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=1,
    )

    end_line: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=1,
    )

    content: Mapped[str] = mapped_column(
        Text,
        nullable=False,
    )

    commit_sha: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
        index=True,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
