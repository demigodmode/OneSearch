# Copyright (C) 2025 demigodmode
# SPDX-License-Identifier: AGPL-3.0-only

"""
Pydantic schemas for request/response validation
"""

from datetime import datetime
from typing import Any, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, model_validator


class Document(BaseModel):
    """
    Normalized document structure returned by extractors
    and sent to Meilisearch for indexing
    """

    id: str  # Format: "{source_id}--{path_hash}" (SHA256 truncated to 12 chars)
    source_id: str
    source_name: str
    path: str
    basename: str
    extension: str
    type: str  # File type: text, markdown, pdf, etc.
    size_bytes: int
    modified_at: int  # Unix timestamp
    indexed_at: int  # Unix timestamp
    content: str  # Extracted full text
    title: str | None = None  # Extracted or derived title
    metadata: dict[str, Any] = Field(default_factory=dict)  # Additional metadata


class ScheduleConfig(BaseModel):
    """A resolved or stored schedule: either a cron expression/preset or a true interval."""

    schedule_type: Literal["cron", "interval"] = "cron"
    scan_schedule: str | None = Field(default=None, max_length=100)
    interval_value: int | None = Field(default=None, gt=0)
    interval_unit: Literal["minutes", "hours", "days"] | None = None

    @model_validator(mode="after")
    def _require_both_interval_fields(self):
        if self.schedule_type == "interval" and (self.interval_value is None) != (
            self.interval_unit is None
        ):
            raise ValueError("interval_value and interval_unit must be set together")
        return self


class SourceBase(BaseModel):
    """Base schema for Source"""

    name: str
    root_path: str
    location_type: Literal["local", "agent"] = "local"
    agent_id: str | None = None
    processing_mode: Literal["on_agent", "on_server"] | None = None
    include_patterns: list[str] | None = None
    exclude_patterns: list[str] | None = None
    scan_schedule: str | None = Field(default=None, max_length=100)
    schedule_type: Literal["cron", "interval"] = "cron"
    interval_value: int | None = Field(default=None, gt=0)
    interval_unit: Literal["minutes", "hours", "days"] | None = None
    use_default_schedule: bool = False


class SourceCreate(SourceBase):
    """Schema for creating a new source"""

    id: str | None = None  # Auto-generated if not provided


class SourceUpdate(BaseModel):
    """Schema for updating a source"""

    name: str | None = None
    root_path: str | None = None
    location_type: Literal["local", "agent"] | None = None
    agent_id: str | None = None
    processing_mode: Literal["on_agent", "on_server"] | None = None
    include_patterns: list[str] | None = None
    exclude_patterns: list[str] | None = None
    scan_schedule: str | None = Field(default=None, max_length=100)
    schedule_type: Literal["cron", "interval"] | None = None
    interval_value: int | None = Field(default=None, gt=0)
    interval_unit: Literal["minutes", "hours", "days"] | None = None
    use_default_schedule: bool | None = None


class SourcePathTestRequest(BaseModel):
    """Schema for testing a source path before saving it."""

    root_path: str
    location_type: Literal["local", "agent"] = "local"
    agent_id: str | None = None


class SourcePathTestResponse(BaseModel):
    """Diagnostics for a candidate source root path."""

    path: str
    ok: bool
    exists: bool
    is_directory: bool
    readable: bool
    inside_allowed_roots: bool
    allowed_roots: list[str]
    looks_like_host_path: bool = False
    message: str
    hint: str | None = None
    job_id: str | None = None
    status: str | None = None


class SourceResponse(SourceBase):
    """Schema for source response"""

    model_config = ConfigDict(from_attributes=True)

    id: str
    created_at: datetime
    updated_at: datetime
    last_scan_at: datetime | None = None
    next_scan_at: datetime | None = None
    effective_schedule: Optional["ScheduleConfig"] = None

    @classmethod
    def from_orm_model(cls, source, effective_schedule: Optional["ScheduleConfig"] = None):
        """Create SourceResponse from ORM model, deserializing JSON fields"""
        import json

        return cls(
            id=source.id,
            name=source.name,
            root_path=source.root_path,
            location_type=getattr(source, "location_type", "local"),
            agent_id=getattr(source, "agent_id", None),
            processing_mode=getattr(source, "processing_mode", None),
            include_patterns=json.loads(source.include_patterns)
            if source.include_patterns
            else None,
            exclude_patterns=json.loads(source.exclude_patterns)
            if source.exclude_patterns
            else None,
            scan_schedule=source.scan_schedule,
            schedule_type=source.schedule_type,
            interval_value=source.interval_value,
            interval_unit=source.interval_unit,
            use_default_schedule=source.use_default_schedule,
            created_at=source.created_at,
            updated_at=source.updated_at,
            last_scan_at=source.last_scan_at,
            next_scan_at=source.next_scan_at,
            effective_schedule=effective_schedule,
        )


class SearchQuery(BaseModel):
    """Schema for search query request"""

    q: str  # Query string
    source_id: str | None = None
    type: str | None = None
    limit: int = Field(default=20, ge=1, le=100)
    offset: int = Field(default=0, ge=0)
    sort: Literal["relevance", "modified_at:desc", "modified_at:asc", "size_bytes:desc", "basename:asc"] | None = None
    snippet_length: int = Field(default=300, ge=50, le=1000)


class SearchResult(BaseModel):
    """Schema for individual search result"""

    id: str
    path: str
    basename: str
    source_name: str
    type: str
    size_bytes: int
    modified_at: int
    snippet: str  # Content snippet with highlighting
    score: float  # Relevance score


class SearchResponse(BaseModel):
    """Schema for search response"""

    results: list[SearchResult]
    total: int
    limit: int
    offset: int
    processing_time_ms: int


class SourceStatus(BaseModel):
    """Schema for source indexing status"""

    source_id: str
    source_name: str
    total_files: int
    indexed_files: int
    failed_files: int
    last_indexed_at: datetime | None = None
    scan_schedule: str | None = None
    next_scan_at: datetime | None = None


class HealthResponse(BaseModel):
    """Schema for health check response"""

    status: str
    meilisearch_connected: bool
    database_connected: bool
    setup_required: bool = False


# Authentication schemas
class SetupRequest(BaseModel):
    """Schema for initial setup request"""

    username: str = Field(..., min_length=3, max_length=50)
    password: str = Field(..., min_length=8)


class LoginRequest(BaseModel):
    """Schema for login request"""

    username: str
    password: str


class UserResponse(BaseModel):
    """Schema for user info response"""

    model_config = ConfigDict(from_attributes=True)

    id: int
    username: str
    is_active: bool
    created_at: datetime


class AuthResponse(BaseModel):
    """Schema for authentication response"""

    access_token: str
    token_type: str = "bearer"
    expires_in: int  # seconds


class AppSettingsResponse(BaseModel):
    """Backend-managed indexing and preview settings."""

    unsupported_file_policy: Literal["skip", "metadata_only"] = "metadata_only"
    media_metadata_mode: Literal["auto", "off"] = "auto"
    raw_metadata_mode: Literal["auto", "off"] = "auto"
    index_gps_metadata: bool = False
    show_previews: bool = True
    raw_preview_enabled: bool = True
    max_preview_size_mb: Literal[25, 50, 100] = 50
    media_probe_max_size_mb: int = Field(default=0, ge=0)
    max_text_file_size_mb: int = Field(default=10, ge=1)
    max_pdf_file_size_mb: int = Field(default=50, ge=1)
    max_office_file_size_mb: int = Field(default=50, ge=1)
    image_metadata_max_size_mb: int = Field(default=100, ge=1)
    epub_extraction_max_size_mb: int = Field(default=100, ge=1)
    comic_extraction_max_size_mb: int = Field(default=100, ge=1)
    readable_preview_page_chars: int = Field(default=6000, ge=1000)
    long_text_pagination_threshold_chars: int = Field(default=20000, ge=1000)
    default_scan_schedule: ScheduleConfig | None = None
    remote_agents_enabled: bool = False


class AppSettingsUpdate(BaseModel):
    """Partial update for backend-managed indexing and preview settings."""

    unsupported_file_policy: Literal["skip", "metadata_only"] | None = None
    media_metadata_mode: Literal["auto", "off"] | None = None
    raw_metadata_mode: Literal["auto", "off"] | None = None
    index_gps_metadata: bool | None = None
    show_previews: bool | None = None
    raw_preview_enabled: bool | None = None
    max_preview_size_mb: Literal[25, 50, 100] | None = None
    media_probe_max_size_mb: int | None = Field(default=None, ge=0)
    max_text_file_size_mb: int | None = Field(default=None, ge=1)
    max_pdf_file_size_mb: int | None = Field(default=None, ge=1)
    max_office_file_size_mb: int | None = Field(default=None, ge=1)
    image_metadata_max_size_mb: int | None = Field(default=None, ge=1)
    epub_extraction_max_size_mb: int | None = Field(default=None, ge=1)
    comic_extraction_max_size_mb: int | None = Field(default=None, ge=1)
    readable_preview_page_chars: int | None = Field(default=None, ge=1000)
    long_text_pagination_threshold_chars: int | None = Field(default=None, ge=1000)
    default_scan_schedule: ScheduleConfig | None = None
    remote_agents_enabled: bool | None = None


class AgentEnrollmentCodeResponse(BaseModel):
    """One-time code returned only when an administrator creates it."""

    code: str
    expires_at: datetime


class AgentAdminResponse(BaseModel):
    """Agent details safe for administrative APIs."""

    id: str
    name: str
    platform: str
    version: str
    protocol_version: int
    allowed_roots: list[dict]
    default_processing_mode: str
    auto_update: bool
    status: str
    approved_at: datetime | None
    last_seen_at: datetime | None
    disabled_at: datetime | None
    created_at: datetime
    updated_at: datetime
    summary: "AgentAdminSummary"


class AgentAdminSummary(BaseModel):
    attached_sources: int
    indexed_documents: int
    pending_jobs: int
    active_jobs: int
    failed_jobs: int
    earliest_next_scan_at: datetime | None


class AgentSourceSummary(BaseModel):
    id: str
    name: str
    root_path: str
    next_scan_at: datetime | None


class AgentJobSummary(BaseModel):
    id: str
    kind: str
    status: str
    source_id: str | None
    created_at: datetime
    completed_at: datetime | None
    error: str | None


class AgentAdminDetails(AgentAdminResponse):
    summary: AgentAdminSummary
    sources: list[AgentSourceSummary]
    recent_jobs: list[AgentJobSummary]


class AgentAdminUpdate(BaseModel):
    """Administrator-controlled agent defaults."""

    default_processing_mode: Literal["on_agent", "on_server"]


class AgentHeartbeatResponse(BaseModel):
    """Current server-side state after a heartbeat."""

    status: str


class MessageResponse(BaseModel):
    """Generic message response"""

    message: str
