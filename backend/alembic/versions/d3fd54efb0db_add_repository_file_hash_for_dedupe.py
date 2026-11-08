"""add repository file hash for dedupe

Revision ID: d3fd54efb0db
Revises: 9c35d1355d2d
Create Date: 2026-11-03

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "d3fd54efb0db"
down_revision: Union[str, Sequence[str], None] = "9c35d1355d2d"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "repository_files",
        sa.Column("file_hash", sa.String(length=64), nullable=True),
    )
    op.execute("UPDATE repository_files SET file_hash = '' WHERE file_hash IS NULL")
    op.alter_column("repository_files", "file_hash", nullable=False, server_default="")
    op.create_index(
        "ix_repository_files_file_hash",
        "repository_files",
        ["file_hash"],
        unique=False,
    )
    op.create_index(
        "uq_repository_file_repo_path",
        "repository_files",
        ["repository_id", "file_path"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index("uq_repository_file_repo_path", table_name="repository_files")
    op.drop_index("ix_repository_files_file_hash", table_name="repository_files")
    op.drop_column("repository_files", "file_hash")
