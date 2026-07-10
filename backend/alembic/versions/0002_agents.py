"""ai agents table

Revision ID: 0002_agents
Revises: 0001_initial_auth
Create Date: 2026-07-09
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0002_agents"
down_revision: str | None = "0001_initial_auth"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "agents",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("description", sa.String(length=1000), nullable=True),
        sa.Column("system_prompt", sa.Text(), nullable=False, server_default=""),
        sa.Column("greeting", sa.Text(), nullable=True),
        sa.Column("llm_model", sa.String(length=120), nullable=False, server_default="gpt-oss-120b"),
        sa.Column("temperature", sa.Float(), nullable=False, server_default="0.7"),
        sa.Column("voice", sa.String(length=60), nullable=False, server_default="meera"),
        sa.Column("language", sa.String(length=16), nullable=False, server_default="en-IN"),
        sa.Column("max_call_duration_seconds", sa.Integer(), nullable=False, server_default="300"),
        sa.Column("interruptible", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("memory_enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("tools", postgresql.JSONB(), nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("transfer_rules", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("end_call_rules", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("custom_variables", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(
            ["organization_id"], ["organizations.id"],
            name="fk_agents_organization_id_organizations", ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_agents"),
    )
    op.create_index("ix_agents_organization_id", "agents", ["organization_id"], unique=False)


def downgrade() -> None:
    op.drop_table("agents")
