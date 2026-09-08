"""add durable remote scan page staging

Revision ID: e8b4c6d912fa
Revises: c25f7a9b1d02
"""

import sqlalchemy as sa
from alembic import op

revision = "e8b4c6d912fa"
down_revision = "c25f7a9b1d02"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "agent_scan_pages",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("job_id", sa.String(), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("checksum", sa.String(length=64), nullable=False),
        sa.Column("cursor", sa.Text(), nullable=False),
        sa.Column("scanned_count", sa.Integer(), nullable=False),
        sa.Column("is_final", sa.Boolean(), server_default="0", nullable=False),
        sa.Column("entry_count", sa.Integer(), nullable=False),
        sa.Column("outcome_checksum", sa.String(length=64), nullable=True),
        sa.Column("accepted_at", sa.DateTime(), nullable=False),
        sa.Column("settled_at", sa.DateTime(), nullable=True),
        sa.CheckConstraint("sequence >= 0", name="ck_agent_scan_pages_sequence"),
        sa.CheckConstraint("scanned_count >= 0", name="ck_agent_scan_pages_scanned_count"),
        sa.CheckConstraint(
            "entry_count >= 0 AND entry_count <= 1000",
            name="ck_agent_scan_pages_entry_count",
        ),
        sa.CheckConstraint("is_final IN (0, 1)", name="ck_agent_scan_pages_is_final"),
        sa.CheckConstraint(
            "length(checksum) = 64 AND checksum = lower(checksum) "
            "AND checksum NOT GLOB '*[^0-9a-f]*'",
            name="ck_agent_scan_pages_checksum",
        ),
        sa.CheckConstraint(
            "outcome_checksum IS NULL OR (length(outcome_checksum) = 64 "
            "AND outcome_checksum = lower(outcome_checksum) "
            "AND outcome_checksum NOT GLOB '*[^0-9a-f]*')",
            name="ck_agent_scan_pages_outcome_checksum",
        ),
        sa.ForeignKeyConstraint(["job_id"], ["agent_jobs.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("job_id", "sequence", name="uq_agent_scan_pages_job_sequence"),
    )
    op.create_index("ix_agent_scan_pages_job_id", "agent_scan_pages", ["job_id"], unique=False)
    op.create_index(
        "ix_agent_scan_pages_job_final",
        "agent_scan_pages",
        ["job_id", "is_final"],
        unique=False,
    )

    op.create_table(
        "agent_scan_entries",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("job_id", sa.String(), nullable=False),
        sa.Column("page_sequence", sa.Integer(), nullable=False),
        sa.Column("path", sa.String(), nullable=False),
        sa.Column("path_hash", sa.String(length=64), nullable=False),
        sa.Column("size_bytes", sa.BigInteger(), nullable=False),
        sa.Column("modified_at_ns", sa.BigInteger(), nullable=False),
        sa.Column("content_hash", sa.String(), nullable=True),
        sa.Column("needs_processing", sa.Boolean(), server_default="0", nullable=False),
        sa.Column("outcome_status", sa.String(length=16), nullable=True),
        sa.Column("failure_error", sa.Text(), nullable=True),
        sa.CheckConstraint("page_sequence >= 0", name="ck_agent_scan_entries_page_sequence"),
        sa.CheckConstraint("size_bytes >= 0", name="ck_agent_scan_entries_size_bytes"),
        sa.CheckConstraint("modified_at_ns >= 0", name="ck_agent_scan_entries_modified_at_ns"),
        sa.CheckConstraint("needs_processing IN (0, 1)", name="ck_agent_scan_entries_processing"),
        sa.CheckConstraint(
            "length(path_hash) = 64 AND path_hash = lower(path_hash) "
            "AND path_hash NOT GLOB '*[^0-9a-f]*'",
            name="ck_agent_scan_entries_path_hash",
        ),
        sa.CheckConstraint(
            "CASE "
            "WHEN outcome_status IS NULL THEN failure_error IS NULL "
            "WHEN outcome_status IN ('indexed', 'skipped') THEN failure_error IS NULL "
            "WHEN outcome_status = 'failed' THEN failure_error IS NOT NULL "
            "AND length(trim(failure_error)) BETWEEN 1 AND 500 "
            "ELSE 0 END",
            name="ck_agent_scan_entries_outcome_failure",
        ),
        sa.ForeignKeyConstraint(
            ["job_id", "page_sequence"],
            ["agent_scan_pages.job_id", "agent_scan_pages.sequence"],
            name="fk_agent_scan_entries_page",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("job_id", "path", name="uq_agent_scan_entries_job_path"),
    )
    op.create_index(
        "ix_agent_scan_entries_job_page",
        "agent_scan_entries",
        ["job_id", "page_sequence"],
        unique=False,
    )
    op.create_index(
        "ix_agent_scan_entries_job_processing",
        "agent_scan_entries",
        ["job_id", "needs_processing", "outcome_status"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_table("agent_scan_entries")
    op.drop_table("agent_scan_pages")
