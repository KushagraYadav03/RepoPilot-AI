"""add user repo timestamps and repo uniqueness

Revision ID: 3d7d9d7baf18
Revises: d3fd54efb0db
Create Date: 2026-11-03

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "3d7d9d7baf18"
down_revision: Union[str, Sequence[str], None] = "d3fd54efb0db"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
    )
    op.add_column(
        "users",
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
    )

    op.add_column(
        "repositories",
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
    )
    op.add_column(
        "repositories",
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
    )

    op.create_unique_constraint(
        "uq_repository_owner_github_url",
        "repositories",
        ["owner_id", "github_url"],
    )


def downgrade() -> None:
    op.drop_constraint("uq_repository_owner_github_url", "repositories", type_="unique")
    op.drop_column("repositories", "updated_at")
    op.drop_column("repositories", "created_at")
    op.drop_column("users", "updated_at")
    op.drop_column("users", "created_at")
