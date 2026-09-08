# Copyright (C) 2025 demigodmode
# SPDX-License-Identifier: AGPL-3.0-only

"""add remote agents

Revision ID: a91c5e7d2f40
Revises: 361d2b460314
Create Date: 2026-07-18

"""

import sqlalchemy as sa
from alembic import op

revision = "a91c5e7d2f40"
down_revision = "361d2b460314"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "agents",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("platform", sa.String(length=80), nullable=False),
        sa.Column("version", sa.String(length=40), nullable=False),
        sa.Column("protocol_version", sa.Integer(), nullable=False),
        sa.Column("token_hash", sa.String(length=64), nullable=True),
        sa.Column("allowed_roots", sa.Text(), server_default="[]", nullable=False),
        sa.Column(
            "default_processing_mode", sa.String(), server_default="on_agent", nullable=False
        ),
        sa.Column("auto_update", sa.Boolean(), server_default="0", nullable=False),
        sa.Column("status", sa.String(), server_default="pending", nullable=False),
        sa.Column("approved_at", sa.DateTime(), nullable=True),
        sa.Column("last_seen_at", sa.DateTime(), nullable=True),
        sa.Column("disabled_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.CheckConstraint(
            "default_processing_mode IN ('on_agent', 'on_server')",
            name="ck_agents_default_processing_mode",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("token_hash"),
    )
    op.create_table(
        "agent_enrollments",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("code_hash", sa.String(length=64), nullable=False),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.Column("used_at", sa.DateTime(), nullable=True),
        sa.Column("created_by_user_id", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(
            ["created_by_user_id"], ["users.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("code_hash"),
    )

    with op.batch_alter_table("sources", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column("location_type", sa.String(), server_default="local", nullable=False)
        )
        batch_op.add_column(sa.Column("agent_id", sa.String(), nullable=True))
        batch_op.add_column(sa.Column("processing_mode", sa.String(), nullable=True))
        batch_op.create_foreign_key(
            "fk_sources_agent_id_agents", "agents", ["agent_id"], ["id"], ondelete="CASCADE"
        )
        batch_op.create_check_constraint(
            "ck_sources_location_type", "location_type IN ('local', 'agent')"
        )
        batch_op.create_check_constraint(
            "ck_sources_processing_mode",
            "processing_mode IS NULL OR processing_mode IN ('on_agent', 'on_server')",
        )
        batch_op.create_check_constraint(
            "ck_sources_location_agent",
            "(location_type = 'local' AND agent_id IS NULL AND processing_mode IS NULL) OR "
            "(location_type = 'agent' AND agent_id IS NOT NULL)",
        )
        batch_op.create_unique_constraint("uq_sources_id_agent_id", ["id", "agent_id"])
        batch_op.create_index("ix_sources_agent_id", ["agent_id"], unique=False)

    op.create_table(
        "agent_jobs",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("agent_id", sa.String(), nullable=False),
        sa.Column("source_id", sa.String(), nullable=True),
        sa.Column("kind", sa.String(), nullable=False),
        sa.Column("reason", sa.String(), nullable=True),
        sa.Column("status", sa.String(), server_default="pending", nullable=False),
        sa.Column("processing_mode", sa.String(), nullable=True),
        sa.Column("active_key", sa.String(), nullable=True),
        sa.Column("payload", sa.Text(), server_default="{}", nullable=False),
        sa.Column("checkpoint", sa.Text(), server_default="{}", nullable=False),
        sa.Column("lease_token_hash", sa.String(length=64), nullable=True),
        sa.Column("lease_expires_at", sa.DateTime(), nullable=True),
        sa.Column("progress_current", sa.Integer(), server_default="0", nullable=False),
        sa.Column("progress_total", sa.Integer(), nullable=True),
        sa.Column("attempts", sa.Integer(), server_default="0", nullable=False),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("completed_at", sa.DateTime(), nullable=True),
        sa.CheckConstraint(
            "kind IN ('scan', 'browse', 'extract_file', 'stream_file')",
            name="ck_agent_jobs_kind",
        ),
        sa.CheckConstraint(
            "status IN ('pending', 'claimed', 'running', 'cancelling', "
            "'completed', 'failed', 'cancelled')",
            name="ck_agent_jobs_status",
        ),
        sa.CheckConstraint(
            "processing_mode IS NULL OR processing_mode IN ('on_agent', 'on_server')",
            name="ck_agent_jobs_processing_mode",
        ),
        sa.ForeignKeyConstraint(["agent_id"], ["agents.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["source_id", "agent_id"],
            ["sources.id", "sources.agent_id"],
            name="fk_agent_jobs_source_agent_sources",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("active_key", name="uq_agent_jobs_active_key"),
    )
    with op.batch_alter_table("agent_jobs", schema=None) as batch_op:
        batch_op.create_index("ix_agent_jobs_agent_id", ["agent_id"], unique=False)
        batch_op.create_index(
            "ix_agent_jobs_agent_status_created",
            ["agent_id", "status", "created_at"],
            unique=False,
        )
        batch_op.create_index("ix_agent_jobs_source_id", ["source_id"], unique=False)
        batch_op.create_index(
            "ix_agent_jobs_status_lease_expires",
            ["status", "lease_expires_at"],
            unique=False,
        )

    op.create_table(
        "agent_batches",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("job_id", sa.String(), nullable=False),
        sa.Column("idempotency_key", sa.String(length=80), nullable=False),
        sa.Column("checksum", sa.String(length=64), nullable=False),
        sa.Column("accepted_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["job_id"], ["agent_jobs.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("job_id", "idempotency_key", name="uq_agent_batches_job_key"),
    )
    with op.batch_alter_table("agent_batches", schema=None) as batch_op:
        batch_op.create_index("ix_agent_batches_job_id", ["job_id"], unique=False)


def downgrade() -> None:
    with op.batch_alter_table("agent_batches", schema=None) as batch_op:
        batch_op.drop_index("ix_agent_batches_job_id")
    op.drop_table("agent_batches")

    with op.batch_alter_table("agent_jobs", schema=None) as batch_op:
        batch_op.drop_index("ix_agent_jobs_status_lease_expires")
        batch_op.drop_index("ix_agent_jobs_source_id")
        batch_op.drop_index("ix_agent_jobs_agent_status_created")
        batch_op.drop_index("ix_agent_jobs_agent_id")
    op.drop_table("agent_jobs")

    with op.batch_alter_table("sources", schema=None) as batch_op:
        batch_op.drop_index("ix_sources_agent_id")
        batch_op.drop_constraint("ck_sources_location_agent", type_="check")
        batch_op.drop_constraint("ck_sources_processing_mode", type_="check")
        batch_op.drop_constraint("ck_sources_location_type", type_="check")
        batch_op.drop_constraint("uq_sources_id_agent_id", type_="unique")
        batch_op.drop_constraint("fk_sources_agent_id_agents", type_="foreignkey")
        batch_op.drop_column("processing_mode")
        batch_op.drop_column("agent_id")
        batch_op.drop_column("location_type")

    op.drop_table("agent_enrollments")
    op.drop_table("agents")
