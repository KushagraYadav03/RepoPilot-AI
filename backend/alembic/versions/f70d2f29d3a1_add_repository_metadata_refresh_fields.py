"""add repository metadata refresh fields

Revision ID: f70d2f29d3a1
Revises: 3d7d9d7baf18
Create Date: 2026-11-03

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "f70d2f29d3a1"
down_revision: Union[str, Sequence[str], None] = "3d7d9d7baf18"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "repositories",
        sa.Column("default_branch", sa.String(length=255), nullable=True),
    )
    op.add_column(
        "repositories",
        sa.Column("tree_sha", sa.String(length=64), nullable=True),
    )
    op.add_column(
        "repositories",
        sa.Column("last_commit_sha", sa.String(length=255), nullable=True),
    )
    op.add_column(
        "repositories",
        sa.Column("programming_languages", sa.String(length=500), nullable=True),
    )
    op.add_column(
        "repositories",
        sa.Column(
            "last_synced_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
    )


def downgrade() -> None:
    op.drop_column("repositories", "last_synced_at")
    op.drop_column("repositories", "programming_languages")
    op.drop_column("repositories", "last_commit_sha")
    op.drop_column("repositories", "tree_sha")
    op.drop_column("repositories", "default_branch")
