"""add exact indexed file nanosecond timestamp

Revision ID: c25f7a9b1d02
Revises: a91c5e7d2f40
"""

import sqlalchemy as sa
from alembic import op

revision = "c25f7a9b1d02"
down_revision = "a91c5e7d2f40"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("indexed_files", sa.Column("modified_at_ns", sa.BigInteger(), nullable=True))


def downgrade() -> None:
    op.drop_column("indexed_files", "modified_at_ns")
