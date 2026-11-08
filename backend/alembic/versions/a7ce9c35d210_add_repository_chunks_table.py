"""add repository chunks table

Revision ID: a7ce9c35d210
Revises: f70d2f29d3a1
Create Date: 2026-11-05

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "a7ce9c35d210"
down_revision: Union[str, Sequence[str], None] = "f70d2f29d3a1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "repository_chunks",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("repository_id", sa.Integer(), nullable=False),
        sa.Column("file_path", sa.String(length=1000), nullable=False),
        sa.Column("symbol_name", sa.String(length=255), nullable=False),
        sa.Column("symbol_kind", sa.String(length=50), nullable=False),
        sa.Column("start_line", sa.Integer(), nullable=False),
        sa.Column("end_line", sa.Integer(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("commit_sha", sa.String(length=255), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["repository_id"], ["repositories.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_repository_chunks_commit_sha"), "repository_chunks", ["commit_sha"], unique=False)
    op.create_index(op.f("ix_repository_chunks_file_path"), "repository_chunks", ["file_path"], unique=False)
    op.create_index(op.f("ix_repository_chunks_id"), "repository_chunks", ["id"], unique=False)
    op.create_index(op.f("ix_repository_chunks_repository_id"), "repository_chunks", ["repository_id"], unique=False)
    op.create_index(op.f("ix_repository_chunks_symbol_kind"), "repository_chunks", ["symbol_kind"], unique=False)
    op.create_index(op.f("ix_repository_chunks_symbol_name"), "repository_chunks", ["symbol_name"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_repository_chunks_symbol_name"), table_name="repository_chunks")
    op.drop_index(op.f("ix_repository_chunks_symbol_kind"), table_name="repository_chunks")
    op.drop_index(op.f("ix_repository_chunks_repository_id"), table_name="repository_chunks")
    op.drop_index(op.f("ix_repository_chunks_id"), table_name="repository_chunks")
    op.drop_index(op.f("ix_repository_chunks_file_path"), table_name="repository_chunks")
    op.drop_index(op.f("ix_repository_chunks_commit_sha"), table_name="repository_chunks")
    op.drop_table("repository_chunks")
