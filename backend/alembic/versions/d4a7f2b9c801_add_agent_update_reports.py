"""add sanitized agent update reports

Revision ID: d4a7f2b9c801
Revises: e8b4c6d912fa
"""

import sqlalchemy as sa
from alembic import op

revision = "d4a7f2b9c801"
down_revision = "e8b4c6d912fa"
branch_labels = None
depends_on = None


def _clear_legacy_auto_update_statement():
    agents = sa.table("agents", sa.column("auto_update", sa.Boolean()))
    return sa.update(agents).where(agents.c.auto_update.is_(False)).values(auto_update=None)


def upgrade() -> None:
    with op.batch_alter_table("agents") as batch:
        batch.alter_column("auto_update", existing_type=sa.Boolean(), nullable=True, server_default=None)
        batch.add_column(sa.Column("update_runtime_kind", sa.String(length=10), nullable=True))
        batch.add_column(sa.Column("update_status", sa.String(length=16), nullable=True))
        batch.add_column(sa.Column("update_available_version", sa.String(length=40), nullable=True))
        batch.add_column(sa.Column("update_checked_at", sa.DateTime(), nullable=True))
        batch.add_column(sa.Column("update_error_code", sa.String(length=32), nullable=True))
    # Pre-reporting rows inherited the old server default and did not state a local preference.
    op.execute(_clear_legacy_auto_update_statement())


def downgrade() -> None:
    op.execute("UPDATE agents SET auto_update = 0 WHERE auto_update IS NULL")
    with op.batch_alter_table("agents") as batch:
        batch.drop_column("update_error_code")
        batch.drop_column("update_checked_at")
        batch.drop_column("update_available_version")
        batch.drop_column("update_status")
        batch.drop_column("update_runtime_kind")
        batch.alter_column("auto_update", existing_type=sa.Boolean(), nullable=False, server_default="0")
