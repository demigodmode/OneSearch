# Copyright (C) 2025 demigodmode
# SPDX-License-Identifier: AGPL-3.0-only

"""
Pydantic schemas for request/response validation
"""
from datetime import datetime
from typing import Optional, Dict, Any, List
from pydantic import BaseModel, ConfigDict, Field


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
    title: Optional[str] = None  # Extracted or derived title
    metadata: Dict[str, Any] = Field(default_factory=dict)  # Additional metadata


class SourceBase(BaseModel):
    """Base schema for Source"""
    name: str
    root_path: str
    include_patterns: Optional[List[str]] = None
    exclude_patterns: Optional[List[str]] = None
    scan_schedule: Optional[str] = Field(default=None, max_length=100)


class SourceCreate(SourceBase):
    """Schema for creating a new source"""
    id: Optional[str] = None  # Auto-generated if not provided


class SourceUpdate(BaseModel):
    """Schema for updating a source"""
    name: Optional[str] = None
    root_path: Optional[str] = None
    include_patterns: Optional[List[str]] = None
    exclude_patterns: Optional[List[str]] = None
    scan_schedule: Optional[str] = Field(default=None, max_length=100)


class SourceResponse(SourceBase):
    """Schema for source response"""
    model_config = ConfigDict(from_attributes=True)

    id: str
    created_at: datetime
    updated_at: datetime
    last_scan_at: Optional[datetime] = None
    next_scan_at: Optional[datetime] = None

    @classmethod
    def from_orm_model(cls, source):
        """Create SourceResponse from ORM model, deserializing JSON fields"""
        import json
        return cls(
            id=source.id,
            name=source.name,
            root_path=source.root_path,
            include_patterns=json.loads(source.include_patterns) if source.include_patterns else None,
            exclude_patterns=json.loads(source.exclude_patterns) if source.exclude_patterns else None,
            scan_schedule=source.scan_schedule,
            created_at=source.created_at,
            updated_at=source.updated_at,
            last_scan_at=source.last_scan_at,
            next_scan_at=source.next_scan_at,
        )


class SearchQuery(BaseModel):
    """Schema for search query request"""
    q: str  # Query string
    source_id: Optional[str] = None
    type: Optional[str] = None
    limit: int = Field(default=20, ge=1, le=100)
    offset: int = Field(default=0, ge=0)


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
    results: List[SearchResult]
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
    last_indexed_at: Optional[datetime] = None
    scan_schedule: Optional[str] = None
    next_scan_at: Optional[datetime] = None


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


class MessageResponse(BaseModel):
    """Generic message response"""
    message: str
