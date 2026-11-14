
"""add conversation persistence

Revision ID: c8f1a2b3d4e5
Revises: a7ce9c35d210
Create Date: 2026-11-14
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "c8f1a2b3d4e5"

down_revision: Union[str, Sequence[str], None] = "a7ce9c35d210"

branch_labels: Union[str, Sequence[str], None] = None

depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:

    op.create_table(
        "conversations",

        sa.Column(
            "id",
            sa.Integer(),
            nullable=False,
        ),

        sa.Column(
            "user_id",
            sa.Integer(),
            nullable=False,
        ),

        sa.Column(
            "repository_id",
            sa.Integer(),
            nullable=False,
        ),

        sa.Column(
            "title",
            sa.String(length=200),
            nullable=False,
        ),

        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),

        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),

        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name="fk_conversations_user_id",
            ondelete="CASCADE",
        ),

        sa.ForeignKeyConstraint(
            ["repository_id"],
            ["repositories.id"],
            name="fk_conversations_repository_id",
            ondelete="CASCADE",
        ),

        sa.PrimaryKeyConstraint("id"),
    )

    op.create_index(
        "ix_conversations_id",
        "conversations",
        ["id"],
        unique=False,
    )

    op.create_index(
        "ix_conversations_user_id",
        "conversations",
        ["user_id"],
        unique=False,
    )

    op.create_index(
        "ix_conversations_repository_id",
        "conversations",
        ["repository_id"],
        unique=False,
    )

    op.create_table(
        "messages",

        sa.Column(
            "id",
            sa.Integer(),
            nullable=False,
        ),

        sa.Column(
            "conversation_id",
            sa.Integer(),
            nullable=False,
        ),

        sa.Column(
            "role",
            sa.String(length=20),
            nullable=False,
        ),

        sa.Column(
            "content",
            sa.Text(),
            nullable=False,
        ),

        sa.Column(
            "provider",
            sa.String(length=100),
            nullable=True,
        ),

        sa.Column(
            "model",
            sa.String(length=150),
            nullable=True,
        ),

        sa.Column(
            "sources",
            sa.JSON(),
            nullable=True,
        ),

        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),

        sa.ForeignKeyConstraint(
            ["conversation_id"],
            ["conversations.id"],
            name="fk_messages_conversation_id",
            ondelete="CASCADE",
        ),

        sa.PrimaryKeyConstraint("id"),
    )

    op.create_index(
        "ix_messages_id",
        "messages",
        ["id"],
        unique=False,
    )

    op.create_index(
        "ix_messages_conversation_id",
        "messages",
        ["conversation_id"],
        unique=False,
    )


def downgrade() -> None:

    op.drop_index(
        "ix_messages_conversation_id",
        table_name="messages",
    )

    op.drop_index(
        "ix_messages_id",
        table_name="messages",
    )

    op.drop_table("messages")

    op.drop_index(
        "ix_conversations_repository_id",
        table_name="conversations",
    )

    op.drop_index(
        "ix_conversations_user_id",
        table_name="conversations",
    )

    op.drop_index(
        "ix_conversations_id",
        table_name="conversations",
    )

    op.drop_table("conversations")
