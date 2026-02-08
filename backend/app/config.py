# Copyright (C) 2025 demigodmode
# SPDX-License-Identifier: AGPL-3.0-only

"""
Application configuration using pydantic-settings
Loads settings from environment variables
"""
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from environment"""

    model_config = SettingsConfigDict(
        env_file=".env",
        case_sensitive=False,
    )

    # Meilisearch configuration
    meili_url: str = "http://localhost:7700"
    meili_master_key: str = ""  # Required in production

    # Database configuration
    database_url: str = "sqlite:////app/data/onesearch.db"

    # Application settings
    log_level: str = "INFO"

    # File size limits (in MB)
    max_text_file_size_mb: int = 10
    max_pdf_file_size_mb: int = 50
    max_office_file_size_mb: int = 50

    # Extraction timeouts (in seconds)
    text_extraction_timeout: int = 5
    pdf_extraction_timeout: int = 30
    office_extraction_timeout: int = 30

    # Indexing configuration
    meilisearch_batch_size: int = 100
    indexing_progress_interval: int = 100

    # Authentication settings
    session_secret: str = ""  # Required in production
    session_expire_hours: int = 24
    auth_rate_limit: int = 5  # Max attempts per minute

    # CORS settings (comma-separated origins, empty = localhost defaults)
    cors_origins: str = ""

    # Source path restrictions (comma-separated allowed parent dirs)
    allowed_source_paths: str = "/data"

    # Scheduler settings
    scheduler_enabled: bool = True
    schedule_timezone: str = "UTC"


# Global settings instance
settings = Settings()
