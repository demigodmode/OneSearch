"""add durable source batches

Revision ID: f9c23a14b980
Revises: d4a7f2b9c801
"""

import sqlalchemy as sa
from alembic import op

revision = "f9c23a14b980"
down_revision = "d4a7f2b9c801"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "source_batches",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("owner_user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("fingerprint", sa.String(64), nullable=False),
        sa.Column("request_snapshot", sa.Text(), nullable=False),
        sa.Column("location_type", sa.String(5), nullable=False),
        sa.Column("agent_id", sa.String(), nullable=True),
        sa.Column("dismissed", sa.Boolean(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_source_batches_owner_user_id", "source_batches", ["owner_user_id"])
    op.create_table(
        "source_batch_items",
        sa.Column("batch_id", sa.String(36), sa.ForeignKey("source_batches.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("item_id", sa.String(36), primary_key=True),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("root_path", sa.String(4096), nullable=False),
        sa.Column("state", sa.String(24), nullable=False, server_default="pending"),
        sa.Column("source_id", sa.String(100), nullable=True),
        sa.Column("duplicate_of_item_id", sa.String(36), nullable=True),
        sa.Column("last_error", sa.String(500), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("batch_id", "item_id", name="uq_source_batch_item"),
    )


def downgrade():
    op.drop_table("source_batch_items")
    op.drop_index("ix_source_batches_owner_user_id", table_name="source_batches")
    op.drop_table("source_batches")
