# Copyright (C) 2026 demigodmode
# SPDX-License-Identifier: AGPL-3.0-only

"""Deletes audit entries older than the audit_retention_days setting."""

from datetime import datetime, timedelta

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from ..models import AuditEvent
from .app_settings import AppSettingsService

PURGE_BATCH_SIZE = 1000


def purge_old_audit_events(
    db: Session, now: datetime, batch_size: int = PURGE_BATCH_SIZE
) -> int:
    """Delete entries created before now minus the retention period.

    `now` is naive UTC. Each batch is committed on its own so SQLite's write lock
    is held briefly. Returns the number removed.
    """
    days = AppSettingsService(db).get_settings().audit_retention_days
    cutoff = now - timedelta(days=days)
    removed = 0
    while True:
        ids = list(
            db.scalars(
                select(AuditEvent.id)
                .where(AuditEvent.created_at < cutoff)
                .limit(batch_size)
            )
        )
        if not ids:
            return removed
        db.execute(delete(AuditEvent).where(AuditEvent.id.in_(ids)))
        db.commit()
        removed += len(ids)
