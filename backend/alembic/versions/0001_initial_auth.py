"""initial auth schema: organizations, users, api_keys

Revision ID: 0001_initial_auth
Revises:
Create Date: 2026-07-09
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0001_initial_auth"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

user_role = postgresql.ENUM("owner", "admin", "member", name="user_role", create_type=False)


def upgrade() -> None:
    bind = op.get_bind()
    user_role.create(bind, checkfirst=True)

    op.create_table(
        "organizations",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("slug", sa.String(length=120), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_organizations"),
    )
    op.create_index("ix_organizations_slug", "organizations", ["slug"], unique=True)

    op.create_table(
        "users",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("email", sa.String(length=320), nullable=False),
        sa.Column("hashed_password", sa.String(length=255), nullable=False),
        sa.Column("full_name", sa.String(length=255), nullable=True),
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("role", user_role, nullable=False, server_default="member"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("last_login_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(
            ["organization_id"], ["organizations.id"],
            name="fk_users_organization_id_organizations", ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_users"),
    )
    op.create_index("ix_users_email", "users", ["email"], unique=True)
    op.create_index("ix_users_organization_id", "users", ["organization_id"], unique=False)

    op.create_table(
        "api_keys",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("prefix", sa.String(length=16), nullable=False),
        sa.Column("hashed_key", sa.String(length=128), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_by_user_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(
            ["organization_id"], ["organizations.id"],
            name="fk_api_keys_organization_id_organizations", ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["created_by_user_id"], ["users.id"],
            name="fk_api_keys_created_by_user_id_users", ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_api_keys"),
    )
    op.create_index("ix_api_keys_organization_id", "api_keys", ["organization_id"], unique=False)
    op.create_index("ix_api_keys_prefix", "api_keys", ["prefix"], unique=False)
    op.create_index("ix_api_keys_hashed_key", "api_keys", ["hashed_key"], unique=True)


def downgrade() -> None:
    op.drop_table("api_keys")
    op.drop_table("users")
    op.drop_table("organizations")
    user_role.drop(op.get_bind(), checkfirst=True)
