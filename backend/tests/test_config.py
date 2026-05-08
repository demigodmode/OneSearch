# Copyright (C) 2025 demigodmode
# SPDX-License-Identifier: AGPL-3.0-only

"""
Tests for Settings configuration defaults and env var loading
"""
import pytest
from app.config import Settings


# Fields that may be overridden by .env or environment variables.
# We clear them in tests that check defaults.
_ENV_SENSITIVE_FIELDS = [
    "MEILI_URL", "MEILI_MASTER_KEY", "DATABASE_URL",
    "LOG_LEVEL", "SESSION_SECRET", "CORS_ORIGINS",
    "ALLOWED_SOURCE_PATHS", "SCHEDULER_ENABLED", "SCHEDULE_TIMEZONE",
    "MAX_TEXT_FILE_SIZE_MB", "MAX_PDF_FILE_SIZE_MB", "MAX_OFFICE_FILE_SIZE_MB",
    "TEXT_EXTRACTION_TIMEOUT", "PDF_EXTRACTION_TIMEOUT", "OFFICE_EXTRACTION_TIMEOUT",
    "MEILISEARCH_BATCH_SIZE", "INDEXING_PROGRESS_INTERVAL",
    "SESSION_EXPIRE_HOURS", "AUTH_RATE_LIMIT",
    "UNSUPPORTED_FILE_POLICY", "MEDIA_METADATA_MODE", "INDEX_GPS_METADATA",
    "SHOW_PREVIEWS", "RAW_PREVIEW_ENABLED", "MAX_PREVIEW_SIZE_MB",
]


@pytest.fixture
def clean_env(monkeypatch):
    """Clear environment variables that could override Settings defaults"""
    for key in _ENV_SENSITIVE_FIELDS:
        monkeypatch.delenv(key, raising=False)
    # Also prevent .env file from loading by pointing to non-existent file
    monkeypatch.setenv("ENV_FILE", "/dev/null")


class TestSettingsDefaults:

    def test_meili_url_default(self, clean_env):
        s = Settings(_env_file=None)
        assert s.meili_url == "http://localhost:7700"

    def test_meili_master_key_default(self, clean_env):
        s = Settings(_env_file=None)
        assert s.meili_master_key == ""

    def test_database_url_default(self, clean_env):
        s = Settings(_env_file=None)
        assert s.database_url == "sqlite:////app/data/onesearch.db"

    def test_log_level_default(self, clean_env):
        s = Settings(_env_file=None)
        assert s.log_level == "INFO"

    def test_file_size_limits(self, clean_env):
        s = Settings(_env_file=None)
        assert s.max_text_file_size_mb == 10
        assert s.max_pdf_file_size_mb == 50
        assert s.max_office_file_size_mb == 50

    def test_extraction_timeouts(self, clean_env):
        s = Settings(_env_file=None)
        assert s.text_extraction_timeout == 5
        assert s.pdf_extraction_timeout == 30
        assert s.office_extraction_timeout == 30

    def test_batch_size_default(self, clean_env):
        s = Settings(_env_file=None)
        assert s.meilisearch_batch_size == 100

    def test_auth_defaults(self, clean_env):
        s = Settings(_env_file=None)
        assert s.session_expire_hours == 24
        assert s.auth_rate_limit == 5

    def test_scheduler_defaults(self, clean_env):
        s = Settings(_env_file=None)
        assert s.scheduler_enabled is True
        assert s.schedule_timezone == "UTC"

    def test_allowed_source_paths_default(self, clean_env):
        s = Settings(_env_file=None)
        assert s.allowed_source_paths == "/data"

    def test_rich_media_settings_defaults(self, clean_env):
        s = Settings(_env_file=None)
        assert s.unsupported_file_policy == "metadata_only"
        assert s.media_metadata_mode == "auto"
        assert s.index_gps_metadata is False
        assert s.show_previews is True
        assert s.raw_preview_enabled is True
        assert s.max_preview_size_mb == 50


class TestSettingsFromEnv:

    def test_meili_url_from_env(self, monkeypatch):
        monkeypatch.setenv("MEILI_URL", "http://meili:7700")
        s = Settings(_env_file=None)
        assert s.meili_url == "http://meili:7700"

    def test_log_level_from_env(self, monkeypatch):
        monkeypatch.setenv("LOG_LEVEL", "DEBUG")
        s = Settings(_env_file=None)
        assert s.log_level == "DEBUG"

    def test_scheduler_disabled_from_env(self, monkeypatch):
        monkeypatch.setenv("SCHEDULER_ENABLED", "false")
        s = Settings(_env_file=None)
        assert s.scheduler_enabled is False

    def test_batch_size_from_env(self, monkeypatch):
        monkeypatch.setenv("MEILISEARCH_BATCH_SIZE", "500")
        s = Settings(_env_file=None)
        assert s.meilisearch_batch_size == 500

    def test_session_expire_from_env(self, monkeypatch):
        monkeypatch.setenv("SESSION_EXPIRE_HOURS", "48")
        s = Settings(_env_file=None)
        assert s.session_expire_hours == 48

    def test_rich_media_settings_from_env(self, monkeypatch):
        monkeypatch.setenv("UNSUPPORTED_FILE_POLICY", "skip")
        monkeypatch.setenv("MEDIA_METADATA_MODE", "off")
        monkeypatch.setenv("INDEX_GPS_METADATA", "true")
        monkeypatch.setenv("SHOW_PREVIEWS", "false")
        monkeypatch.setenv("RAW_PREVIEW_ENABLED", "false")
        monkeypatch.setenv("MAX_PREVIEW_SIZE_MB", "100")

        s = Settings(_env_file=None)

        assert s.unsupported_file_policy == "skip"
        assert s.media_metadata_mode == "off"
        assert s.index_gps_metadata is True
        assert s.show_previews is False
        assert s.raw_preview_enabled is False
        assert s.max_preview_size_mb == 100
