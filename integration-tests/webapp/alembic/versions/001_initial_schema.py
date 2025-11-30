"""Initial schema

Revision ID: 001
Revises:
Create Date: 2025-11-21

"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.String(255), primary_key=True),
        sa.Column("email", sa.String(255), nullable=False, unique=True),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
    )

    op.create_table(
        "folders",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("owner_id", sa.String(255), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("parent_folder_id", sa.Integer(), sa.ForeignKey("folders.id"), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now(), onupdate=sa.func.now()),
    )

    op.create_table(
        "documents",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("content", sa.Text(), nullable=False, server_default=""),
        sa.Column("owner_id", sa.String(255), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("folder_id", sa.Integer(), sa.ForeignKey("folders.id"), nullable=True),
        sa.Column("is_public", sa.Boolean(), default=False, nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now(), onupdate=sa.func.now()),
    )

    op.create_table(
        "shares",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("document_id", sa.Integer(), sa.ForeignKey("documents.id"), nullable=False),
        sa.Column("user_id", sa.String(255), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("permission", sa.String(50), nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
    )

    op.create_index("idx_documents_owner", "documents", ["owner_id"])
    op.create_index("idx_documents_folder", "documents", ["folder_id"])
    op.create_index("idx_shares_document", "shares", ["document_id"])
    op.create_index("idx_shares_user", "shares", ["user_id"])


def downgrade() -> None:
    op.drop_index("idx_shares_user")
    op.drop_index("idx_shares_document")
    op.drop_index("idx_documents_folder")
    op.drop_index("idx_documents_owner")
    op.drop_table("shares")
    op.drop_table("documents")
    op.drop_table("folders")
    op.drop_table("users")
