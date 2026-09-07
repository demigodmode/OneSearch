# Copyright (C) 2025 demigodmode
# SPDX-License-Identifier: AGPL-3.0-only

"""Shared, strict source teardown reused by source-delete and agent-revoke cleanup."""
from __future__ import annotations

import json
import logging

from sqlalchemy.orm import Session

from .search import meili_service

logger = logging.getLogger(__name__)


async def purge_source(source, db: Session, *, scheduler=None) -> None:
    """Delete a source and everything derived from it. Strict: Meili docs are deleted and
    CONFIRMED before the DB row is removed, so a failure leaves the source intact and retryable.
    Preview cleanup is best-effort."""
    escaped_id = json.dumps(source.id)
    await meili_service.delete_documents_by_filter_confirmed(f"source_id = {escaped_id}")  # raises on failure
    if scheduler is not None:
        scheduler.remove_source(source.id)
    try:
        from app.config import settings as runtime_settings
        from app.services.preview_assets import app_data_preview_directory, delete_source_previews

        delete_source_previews(source.id, app_data_preview_directory(runtime_settings.database_url))
    except Exception as error:  # best-effort
        logger.warning("preview cleanup failed for source %s: %s", source.id, error)
    db.delete(source)
    db.commit()
