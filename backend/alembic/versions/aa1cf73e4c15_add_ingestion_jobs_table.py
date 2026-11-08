
"""add ingestion jobs table

Revision ID: aa1cf73e4c15
Revises: f25b31f8a06e
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'aa1cf73e4c15'
down_revision: Union[str, Sequence[str], None] = 'f25b31f8a06e'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'ingestion_jobs',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('owner', sa.String(length=100), nullable=False),
        sa.Column('repo', sa.String(length=100), nullable=False),
        sa.Column('status', sa.String(length=20), nullable=False),
        sa.Column('default_branch', sa.String(length=255), nullable=True),
        sa.Column('tree_sha', sa.String(length=64), nullable=True),
        sa.Column('total_files', sa.Integer(), nullable=False),
        sa.Column('processed_files', sa.Integer(), nullable=False),
        sa.Column('error_message', sa.Text(), nullable=True),
        sa.Column(
            'created_at',
            sa.DateTime(timezone=True),
            server_default=sa.text('now()'),
            nullable=False
        ),
        sa.Column(
            'updated_at',
            sa.DateTime(timezone=True),
            server_default=sa.text('now()'),
            nullable=False
        ),
        sa.PrimaryKeyConstraint('id')
    )

    op.create_index(
        'ix_ingestion_jobs_id',
        'ingestion_jobs',
        ['id'],
        unique=False
    )

    op.create_index(
        'ix_ingestion_jobs_status',
        'ingestion_jobs',
        ['status'],
        unique=False
    )


def downgrade() -> None:
    op.drop_index('ix_ingestion_jobs_status', table_name='ingestion_jobs')
    op.drop_index('ix_ingestion_jobs_id', table_name='ingestion_jobs')
    op.drop_table('ingestion_jobs')
