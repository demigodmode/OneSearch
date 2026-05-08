# Copyright (C) 2025 demigodmode
# SPDX-License-Identifier: AGPL-3.0-only

"""
Backend-managed application settings.
"""
from typing import Any

from sqlalchemy.orm import Session

from ..config import settings
from ..models import AppSetting
from ..schemas import AppSettingsResponse, AppSettingsUpdate


SETTING_KEYS = (
    "unsupported_file_policy",
    "media_metadata_mode",
    "index_gps_metadata",
    "show_previews",
    "raw_preview_enabled",
    "max_preview_size_mb",
)


def default_app_settings() -> AppSettingsResponse:
    """Return app settings defaults from environment-backed config."""
    return AppSettingsResponse(
        unsupported_file_policy=settings.unsupported_file_policy,
        media_metadata_mode=settings.media_metadata_mode,
        index_gps_metadata=settings.index_gps_metadata,
        show_previews=settings.show_previews,
        raw_preview_enabled=settings.raw_preview_enabled,
        max_preview_size_mb=settings.max_preview_size_mb,
    )


def _serialize(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)


def _coerce_value(key: str, value: str) -> Any:
    if key in {"index_gps_metadata", "show_previews", "raw_preview_enabled"}:
        return value.lower() == "true"
    if key == "max_preview_size_mb":
        return int(value)
    return value


class AppSettingsService:
    """Read and persist app settings overrides."""

    def __init__(self, db: Session):
        self.db = db

    def get_settings(self) -> AppSettingsResponse:
        values = default_app_settings().model_dump()
        rows = self.db.query(AppSetting).filter(AppSetting.key.in_(SETTING_KEYS)).all()
        for row in rows:
            values[row.key] = _coerce_value(row.key, row.value)
        return AppSettingsResponse(**values)

    def update_settings(self, update: AppSettingsUpdate) -> AppSettingsResponse:
        update_values = update.model_dump(exclude_unset=True)
        for key, value in update_values.items():
            row = self.db.get(AppSetting, key)
            if row is None:
                row = AppSetting(key=key, value=_serialize(value))
                self.db.add(row)
            else:
                row.value = _serialize(value)
        self.db.commit()
        return self.get_settings()
