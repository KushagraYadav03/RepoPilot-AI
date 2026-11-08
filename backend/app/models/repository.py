
from datetime import datetime

from sqlalchemy import Column, DateTime, ForeignKey, Integer, String, UniqueConstraint, func
from sqlalchemy.orm import relationship

from app.db.base import Base


class Repository(Base):
    __tablename__ = "repositories"
    __table_args__ = (
        UniqueConstraint("owner_id", "github_url", name="uq_repository_owner_github_url"),
    )

    id = Column(Integer, primary_key=True, index=True)

    name = Column(String, nullable=False)

    github_url = Column(String, nullable=False)

    default_branch = Column(String(255), nullable=True)

    tree_sha = Column(String(64), nullable=True)

    last_commit_sha = Column(String(255), nullable=True)

    programming_languages = Column(String(500), nullable=True)

    last_synced_at = Column(DateTime(timezone=True), nullable=True)

    owner_id = Column(
        Integer,
        ForeignKey("users.id"),
        nullable=False,
        index=True,
    )

    owner = relationship("User")

    created_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    updated_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )
