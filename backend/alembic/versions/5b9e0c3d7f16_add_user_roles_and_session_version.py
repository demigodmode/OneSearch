# Copyright (C) 2026 demigodmode
# SPDX-License-Identifier: AGPL-3.0-only

"""add user roles and session version

Revision ID: 5b9e0c3d7f16
Revises: f9c23a14b980
Create Date: 2026-11-02 10:00:00.000000

"""
import sqlalchemy as sa
from alembic import op

revision = "5b9e0c3d7f16"
down_revision = "f9c23a14b980"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Existing users are the instance owner(s) from before roles existed, so they become admins.
    with op.batch_alter_table("users", schema=None) as batch_op:
        batch_op.add_column(sa.Column("role", sa.String(16), nullable=False, server_default="admin"))
    # The admin default only fills rows that existed before the upgrade, so new rows must set a role.
    with op.batch_alter_table("users", schema=None) as batch_op:
        batch_op.alter_column("role", server_default=None)
    with op.batch_alter_table("users", schema=None) as batch_op:
        batch_op.add_column(sa.Column("session_version", sa.Integer(), nullable=False, server_default="0"))
        batch_op.add_column(sa.Column("must_change_password", sa.Boolean(), nullable=False, server_default="0"))
        batch_op.add_column(sa.Column("created_by_id", sa.Integer(), nullable=True))
        batch_op.create_foreign_key(
            "fk_users_created_by_id_users", "users", ["created_by_id"], ["id"], ondelete="SET NULL"
        )
        batch_op.add_column(sa.Column("last_login_at", sa.DateTime(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("users", schema=None) as batch_op:
        batch_op.drop_column("last_login_at")
        batch_op.drop_constraint("fk_users_created_by_id_users", type_="foreignkey")
        batch_op.drop_column("created_by_id")
        batch_op.drop_column("must_change_password")
        batch_op.drop_column("session_version")
        batch_op.drop_column("role")
