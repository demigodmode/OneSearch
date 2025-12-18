# Copyright (C) 2025 demigodmode
# SPDX-License-Identifier: AGPL-3.0-only

"""
Application configuration using pydantic-settings
Loads settings from environment variables
"""
from pydantic_settings import BaseSettings
from pydantic import Field


class Settings(BaseSettings):
    """Application settings loaded from environment"""

    # Meilisearch configuration
    meili_url: str = Field(default="http://localhost:7700", env="MEILI_URL")
    meili_master_key: str = Field(default="", env="MEILI_MASTER_KEY")  # Required in production

    # Database configuration
    database_url: str = Field(
        default="sqlite:///data/onesearch.db",
        env="DATABASE_URL"
    )

    # Application settings
    log_level: str = Field(default="INFO", env="LOG_LEVEL")

    # File size limits (in MB)
    max_text_file_size_mb: int = Field(default=10, env="MAX_TEXT_FILE_SIZE_MB")
    max_pdf_file_size_mb: int = Field(default=50, env="MAX_PDF_FILE_SIZE_MB")

    # Extraction timeouts (in seconds)
    text_extraction_timeout: int = Field(default=5, env="TEXT_EXTRACTION_TIMEOUT")
    pdf_extraction_timeout: int = Field(default=30, env="PDF_EXTRACTION_TIMEOUT")

    # Indexing configuration
    meilisearch_batch_size: int = Field(default=100, env="MEILISEARCH_BATCH_SIZE")
    indexing_progress_interval: int = Field(default=100, env="INDEXING_PROGRESS_INTERVAL")

    class Config:
        env_file = ".env"
        case_sensitive = False


# Global settings instance
settings = Settings()
