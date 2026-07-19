"""Versioned JSON wire contracts for OneSearch servers and remote agents.

All wire timestamps are Unix UTC epoch seconds. Integers keep JSON payloads
timezone-independent and avoid runtime-specific datetime serialization.
"""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, ConfigDict, Field, JsonValue, model_validator

PROTOCOL_VERSION = 1


class WireModel(BaseModel):
    """Base for JSON messages that rejects fields unknown to this protocol."""

    model_config = ConfigDict(extra="forbid", allow_inf_nan=False, strict=True)


class ProcessingMode(str, Enum):
    ON_AGENT = "on_agent"
    ON_SERVER = "on_server"


class JobKind(str, Enum):
    SCAN = "scan"
    BROWSE = "browse"
    EXTRACT_FILE = "extract_file"
    STREAM_FILE = "stream_file"


class JobStatus(str, Enum):
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"


class JobFailureReason(str, Enum):
    PROTOCOL_INCOMPATIBLE = "protocol_incompatible"
    INVALID_REQUEST = "invalid_request"
    ACCESS_DENIED = "access_denied"
    NOT_FOUND = "not_found"
    EXTRACTION_FAILED = "extraction_failed"
    INTERNAL_ERROR = "internal_error"


class AgentHeartbeat(WireModel):
    protocol_version: int = Field(default=PROTOCOL_VERSION, ge=1)
    agent_version: str = Field(min_length=1, max_length=40)
    platform: str = Field(min_length=1, max_length=80)
    current_job_id: str | None = None


class AgentJobLease(WireModel):
    id: str = Field(min_length=1)
    kind: JobKind
    source_id: int | None = Field(default=None, gt=0)
    processing_mode: ProcessingMode | None = None
    payload: dict[str, JsonValue] = Field(default_factory=dict)
    lease_token: str = Field(min_length=1)


class AllowedRoot(WireModel):
    root_id: str = Field(min_length=1)
    path: str = Field(min_length=1)
    display_name: str | None = None
    read_only: bool = True


class AgentEnrollmentRequest(WireModel):
    protocol_version: int = Field(default=PROTOCOL_VERSION, ge=1)
    enrollment_token: str = Field(min_length=1)
    agent_name: str = Field(min_length=1, max_length=120)
    agent_version: str = Field(min_length=1, max_length=40)
    platform: str = Field(min_length=1, max_length=80)
    allowed_roots: list[AllowedRoot] = Field(min_length=1)


class AgentEnrollmentResponse(WireModel):
    protocol_version: int = Field(default=PROTOCOL_VERSION, ge=1)
    agent_id: str = Field(min_length=1)
    agent_token: str = Field(min_length=1)
    allowed_roots: list[AllowedRoot] = Field(default_factory=list)


class DirectoryEntry(WireModel):
    name: str = Field(min_length=1)
    path: str = Field(min_length=1)
    is_directory: bool
    size_bytes: int | None = Field(default=None, ge=0)
    modified_at: int | None = Field(default=None, ge=0)


class BrowseRequest(WireModel):
    root_id: str = Field(min_length=1)
    path: str = ""


class BrowseResponse(WireModel):
    root_id: str = Field(min_length=1)
    path: str = ""
    entries: list[DirectoryEntry] = Field(default_factory=list)


class ScanFile(WireModel):
    path: str = Field(min_length=1)
    size_bytes: int = Field(ge=0)
    modified_at: int = Field(ge=0)
    content_hash: str | None = None


class ScanCheckpoint(WireModel):
    cursor: str = Field(min_length=1)
    scanned_count: int = Field(ge=0)


class ScanManifest(WireModel):
    job_id: str = Field(min_length=1)
    source_id: int = Field(gt=0)
    files: list[ScanFile] = Field(default_factory=list)
    deleted_paths: list[str] = Field(default_factory=list)
    checkpoint: ScanCheckpoint | None = None
    complete: bool = False


class NormalizedRemoteDocument(WireModel):
    source_id: int = Field(gt=0)
    path: str = Field(min_length=1)
    title: str | None = None
    content: str
    mime_type: str | None = None
    size_bytes: int | None = Field(default=None, ge=0)
    modified_at: int = Field(ge=0)
    metadata: dict[str, JsonValue] = Field(default_factory=dict)


class DocumentBatch(WireModel):
    job_id: str = Field(min_length=1)
    batch_id: str = Field(min_length=1)
    documents: list[NormalizedRemoteDocument] = Field(default_factory=list)
    checkpoint: ScanCheckpoint | None = None


class BatchAck(WireModel):
    batch_id: str = Field(min_length=1)
    accepted_count: int = Field(ge=0)
    rejected_paths: dict[str, str] = Field(default_factory=dict)


class JobProgress(WireModel):
    job_id: str = Field(min_length=1)
    completed_items: int = Field(ge=0)
    total_items: int | None = Field(default=None, ge=0)
    message: str | None = None


class JobCompletion(WireModel):
    job_id: str = Field(min_length=1)
    status: JobStatus
    reason: JobFailureReason | None = None
    detail: str | None = None
    checkpoint: ScanCheckpoint | None = None


class ProtocolVersionRange(WireModel):
    minimum_version: int = Field(ge=1)
    maximum_version: int = Field(ge=1)

    @model_validator(mode="after")
    def validate_bounds(self) -> ProtocolVersionRange:
        if self.maximum_version < self.minimum_version:
            raise ValueError("maximum_version must be greater than or equal to minimum_version")
        return self

    def supports(self, protocol_version: int) -> bool:
        return self.minimum_version <= protocol_version <= self.maximum_version


class ProtocolCompatibilityResponse(WireModel):
    agent_protocol_version: int = Field(ge=1)
    supported_range: ProtocolVersionRange
    compatible: bool

    @model_validator(mode="after")
    def validate_compatibility(self) -> ProtocolCompatibilityResponse:
        expected = self.supported_range.supports(self.agent_protocol_version)
        if self.compatible is not expected:
            raise ValueError("compatible must match agent_protocol_version and supported_range")
        return self

    @classmethod
    def for_version(
        cls,
        agent_protocol_version: int,
        supported_range: ProtocolVersionRange,
    ) -> ProtocolCompatibilityResponse:
        return cls(
            agent_protocol_version=agent_protocol_version,
            supported_range=supported_range,
            compatible=supported_range.supports(agent_protocol_version),
        )
