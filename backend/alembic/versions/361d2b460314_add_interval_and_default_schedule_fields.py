# Copyright (C) 2025 demigodmode
# SPDX-License-Identifier: AGPL-3.0-only

"""add interval and default schedule fields

Revision ID: 361d2b460314
Revises: f3b8c2d1e9a4
Create Date: 2026-07-05 15:59:46.279944

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '361d2b460314'
down_revision = 'f3b8c2d1e9a4'
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table('sources', schema=None) as batch_op:
        batch_op.add_column(sa.Column('schedule_type', sa.String(), nullable=False, server_default='cron'))
        batch_op.add_column(sa.Column('interval_value', sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column('interval_unit', sa.String(), nullable=True))
        batch_op.add_column(sa.Column('use_default_schedule', sa.Boolean(), nullable=False, server_default='0'))


def downgrade() -> None:
    with op.batch_alter_table('sources', schema=None) as batch_op:
        batch_op.drop_column('use_default_schedule')
        batch_op.drop_column('interval_unit')
        batch_op.drop_column('interval_value')
        batch_op.drop_column('schedule_type')
