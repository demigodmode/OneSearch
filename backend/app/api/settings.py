# Copyright (C) 2025 demigodmode
# SPDX-License-Identifier: AGPL-3.0-only

"""
Application settings API endpoints.
"""
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from ..db.database import get_db
from ..models import User
from ..schemas import AppSettingsResponse, AppSettingsUpdate
from ..services.app_settings import AppSettingsService
from .auth import get_current_user

router = APIRouter(prefix="/api", tags=["settings"])


@router.get("/settings", response_model=AppSettingsResponse)
def get_settings(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Get backend-managed indexing and preview settings."""
    return AppSettingsService(db).get_settings()


@router.put("/settings", response_model=AppSettingsResponse)
def update_settings(
    update: AppSettingsUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Update backend-managed indexing and preview settings."""
    return AppSettingsService(db).update_settings(update)
