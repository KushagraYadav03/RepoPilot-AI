"""add repository files table

Revision ID: 9c35d1355d2d
Revises: 597113f84bde
Create Date: 2026-11-03

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "9c35d1355d2d"
down_revision: Union[str, Sequence[str], None] = "597113f84bde"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "repository_files",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("repository_id", sa.Integer(), nullable=False),
        sa.Column("ingestion_job_id", sa.Integer(), nullable=False),
        sa.Column("file_path", sa.String(length=1000), nullable=False),
        sa.Column("file_name", sa.String(length=255), nullable=False),
        sa.Column("extension", sa.String(length=50), nullable=True),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("size", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("line_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_repository_files_id"), "repository_files", ["id"], unique=False)
    op.create_index(op.f("ix_repository_files_repository_id"), "repository_files", ["repository_id"], unique=False)
    op.create_index(op.f("ix_repository_files_ingestion_job_id"), "repository_files", ["ingestion_job_id"], unique=False)
    op.create_foreign_key(
        "fk_repository_files_repository_id",
        "repository_files",
        "repositories",
        ["repository_id"],
        ["id"],
    )
    op.create_foreign_key(
        "fk_repository_files_ingestion_job_id",
        "repository_files",
        "ingestion_jobs",
        ["ingestion_job_id"],
        ["id"],
    )


def downgrade() -> None:
    op.drop_constraint("fk_repository_files_ingestion_job_id", "repository_files", type_="foreignkey")
    op.drop_constraint("fk_repository_files_repository_id", "repository_files", type_="foreignkey")
    op.drop_index(op.f("ix_repository_files_ingestion_job_id"), table_name="repository_files")
    op.drop_index(op.f("ix_repository_files_repository_id"), table_name="repository_files")
    op.drop_index(op.f("ix_repository_files_id"), table_name="repository_files")
    op.drop_table("repository_files")
