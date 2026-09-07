"""Versioned JSON wire contracts for OneSearch servers and remote agents.

Wire timestamps are Unix UTC epoch seconds unless a field documents nanoseconds;
remote scan and document modified_at values use epoch nanoseconds. Integers keep
payloads timezone-independent and avoid runtime-specific datetime serialization.
"""

from __future__ import annotations

import hashlib
import json
import unicodedata
from enum import Enum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, JsonValue, field_validator, model_validator

PROTOCOL_VERSION = 3
MINIMUM_SUPPORTED_PROTOCOL_VERSION = PROTOCOL_VERSION
REMOTE_MAX_SNAPSHOT_BYTES = 100 * 1024 * 1024
REMOTE_MAX_BATCH_DOCUMENTS = 100
REMOTE_MAX_BATCH_BYTES = 1_000_000
REMOTE_MAX_MANIFEST_PAGE_ENTRIES = 1_000
REMOTE_MAX_MANIFEST_PAGE_BYTES = 2 * 1024 * 1024
REMOTE_MAX_ENTRIES_PER_DIRECTORY = 100_000
REMOTE_MAX_BROWSE_DIRECTORIES = 500
REMOTE_JOB_HEARTBEAT_SECONDS = 20


def _strip_nonempty(value: object) -> object:
    if isinstance(value, str):
        value = value.strip()
        if not value:
            raise ValueError("must not be blank")
    return value


def remote_path_hash(canonical_relative: str) -> str:
    """Return the stable SHA-256 identity for a canonical relative path."""
    return hashlib.sha256(canonical_relative.encode("utf-8")).hexdigest()


def _reject_surrounding_whitespace(value: object) -> object:
    if isinstance(value, str):
        if not value.strip():
            raise ValueError("must not be blank")
        if value != value.strip():
            raise ValueError("must not contain surrounding whitespace")
    return value


class WireModel(BaseModel):
    """Base for JSON messages that rejects fields unknown to this protocol."""

    model_config = ConfigDict(extra="forbid", allow_inf_nan=False, strict=True)


def canonical_wire_bytes(model: WireModel) -> bytes:
    return json.dumps(
        model.model_dump(mode="json"), sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")


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
    update_report: AgentUpdateReport | None = None

    @field_validator("agent_version", "platform", mode="before")
    @classmethod
    def normalize_identity(cls, value: object) -> object:
        return _strip_nonempty(value)


class AgentUpdateReport(WireModel):
    """Sanitized, locally-authoritative release-check state sent with a heartbeat."""

    auto_update: bool
    runtime_kind: Literal["native", "docker"]
    status: Literal["not_checked", "current", "available", "error", "not_configured"]
    available_version: str | None = Field(default=None, max_length=40, pattern=r"^\d+\.\d+\.\d+$")
    checked_at: int = Field(ge=0)
    error_code: Literal[
        "network", "invalid_manifest", "incompatible", "install_unavailable", "install_failed"
    ] | None = None

    @model_validator(mode="after")
    def validate_state(self) -> AgentUpdateReport:
        if self.status == "available" and self.available_version is None:
            raise ValueError("available update reports require a version")
        if self.status != "available" and self.available_version is not None:
            raise ValueError("only available update reports include a version")
        if self.status == "error" and self.error_code is None:
            raise ValueError("error update reports require an error code")
        if self.status != "error" and self.error_code is not None:
            raise ValueError("only error update reports include an error code")
        return self


class AgentJobLease(WireModel):
    id: str = Field(min_length=1)
    # WireModel is strict, which disables enum coercion from the JSON string the
    # server sends over the wire. The client validates a parsed dict (json()), so
    # strict=False is required here or every claimed lease fails to deserialize.
    kind: JobKind = Field(strict=False)
    source_id: str | None = Field(default=None, min_length=1)
    processing_mode: ProcessingMode | None = Field(default=None, strict=False)
    payload: dict[str, JsonValue] = Field(default_factory=dict)
    lease_token: str = Field(min_length=1)


class AgentJobStatusResponse(WireModel):
    job_id: str = Field(min_length=1)
    status: Literal[
        "pending", "claimed", "running", "cancelling", "completed", "failed", "cancelled"
    ]
    handoff_released: bool = False


class AllowedRoot(WireModel):
    root_id: str = Field(min_length=1)
    path: str = Field(min_length=1)
    display_name: str | None = None
    read_only: bool = True

    @field_validator("root_id", mode="before")
    @classmethod
    def normalize_root_id(cls, value: object) -> object:
        return _strip_nonempty(value)

    @field_validator("path", mode="before")
    @classmethod
    def validate_path(cls, value: object) -> object:
        return _reject_surrounding_whitespace(value)


class AgentEnrollmentRequest(WireModel):
    protocol_version: int = Field(default=PROTOCOL_VERSION, ge=1)
    enrollment_token: str = Field(min_length=1)
    agent_name: str = Field(min_length=1, max_length=120)
    agent_version: str = Field(min_length=1, max_length=40)
    platform: str = Field(min_length=1, max_length=80)
    allowed_roots: list[AllowedRoot] = Field(min_length=1)

    @field_validator("agent_name", "agent_version", "platform", mode="before")
    @classmethod
    def normalize_identity(cls, value: object) -> object:
        return _strip_nonempty(value)


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


def _canonical_relative_path(value: object, *, allow_empty: bool) -> str:
    if not isinstance(value, str):
        raise ValueError("must be a string")
    if value == "" and allow_empty:
        return value
    if not value or value != value.strip() or value.startswith(("/", "\\")) or "\\" in value:
        raise ValueError("must be a canonical relative path")
    if any(unicodedata.category(character) == "Cc" for character in value):
        raise ValueError("must not contain control characters")
    parts = value.split("/")
    if any(part in {"", ".", ".."} for part in parts):
        raise ValueError("must be a canonical relative path")
    return value


class BrowseDirectoryEntry(WireModel):
    """A directory-only child returned by a bounded administrative browse."""

    name: str = Field(min_length=1, max_length=255)
    path: str = Field(min_length=1, max_length=4096)

    @field_validator("name", mode="before")
    @classmethod
    def validate_name(cls, value: object) -> object:
        if not isinstance(value, str) or value != value.strip() or value in {"", ".", ".."}:
            raise ValueError("must be a directory name")
        if "/" in value or "\\" in value:
            raise ValueError("must be a directory name")
        if any(unicodedata.category(character) == "Cc" for character in value):
            raise ValueError("must not contain control characters")
        return value

    @field_validator("path", mode="before")
    @classmethod
    def validate_path(cls, value: object) -> object:
        return _canonical_relative_path(value, allow_empty=False)


class BrowseResult(WireModel):
    root_id: str = Field(min_length=1, max_length=120)
    path: str = Field(default="", max_length=4096)
    entries: list[BrowseDirectoryEntry] = Field(
        default_factory=list, max_length=REMOTE_MAX_BROWSE_DIRECTORIES
    )
    truncated: bool

    @field_validator("path", mode="before")
    @classmethod
    def validate_path(cls, value: object) -> object:
        return _canonical_relative_path(value, allow_empty=True)

    @model_validator(mode="after")
    def validate_entries(self) -> BrowseResult:
        paths = [entry.path for entry in self.entries]
        if len(paths) != len(set(paths)):
            raise ValueError("browse entries must be unique")
        return self


class ScanFile(WireModel):
    path: str = Field(min_length=1)
    path_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    size_bytes: int = Field(ge=0)
    modified_at: int = Field(ge=0)
    content_hash: str | None = None


class ScanCheckpoint(WireModel):
    cursor: str = Field(min_length=1)
    scanned_count: int = Field(ge=0)


class ScanManifestPagePayload(WireModel):
    job_id: str = Field(min_length=1)
    source_id: str = Field(min_length=1)
    sequence: int = Field(ge=0)
    files: list[ScanFile] = Field(default_factory=list, max_length=REMOTE_MAX_MANIFEST_PAGE_ENTRIES)
    checkpoint: ScanCheckpoint
    final: bool = False

    @model_validator(mode="after")
    def validate_files(self) -> ScanManifestPagePayload:
        paths = [item.path for item in self.files]
        if len(paths) != len(set(paths)):
            raise ValueError("manifest page file paths must be unique")
        if not self.final and not self.files:
            raise ValueError("non-final manifest pages must contain files")
        return self


class ScanManifestPage(WireModel):
    checksum: str = Field(pattern=r"^[0-9a-f]{64}$")
    page: ScanManifestPagePayload

    @model_validator(mode="after")
    def validate_checksum(self) -> ScanManifestPage:
        expected = hashlib.sha256(canonical_wire_bytes(self.page)).hexdigest()
        if self.checksum != expected:
            raise ValueError("manifest page checksum mismatch")
        return self


class ScanManifestPageAck(WireModel):
    job_id: str = Field(min_length=1)
    sequence: int = Field(ge=0)
    checksum: str = Field(pattern=r"^[0-9a-f]{64}$")
    accepted_count: int = Field(ge=0, le=REMOTE_MAX_MANIFEST_PAGE_ENTRIES)
    changed_paths: list[str] = Field(
        default_factory=list, max_length=REMOTE_MAX_MANIFEST_PAGE_ENTRIES
    )
    duplicate: bool = False
    checkpoint: ScanCheckpoint

    @model_validator(mode="after")
    def validate_changed_paths(self) -> ScanManifestPageAck:
        if len(self.changed_paths) != len(set(self.changed_paths)):
            raise ValueError("manifest page changed paths must be unique")
        return self


class ScanPathOutcomeStatus(str, Enum):
    INDEXED = "indexed"
    SKIPPED = "skipped"
    FAILED = "failed"


class ScanPathOutcome(WireModel):
    path: str = Field(min_length=1)
    status: ScanPathOutcomeStatus
    error: str | None = Field(default=None, max_length=500)

    @field_validator("status", mode="before")
    @classmethod
    def parse_status(cls, value: object) -> object:
        return ScanPathOutcomeStatus(value) if isinstance(value, str) else value

    @field_validator("error", mode="before")
    @classmethod
    def normalize_error(cls, value: object) -> object:
        return _strip_nonempty(value)

    @model_validator(mode="after")
    def validate_error(self) -> ScanPathOutcome:
        if self.status is ScanPathOutcomeStatus.FAILED and self.error is None:
            raise ValueError("failed scan path outcomes require an error")
        if self.status is not ScanPathOutcomeStatus.FAILED and self.error is not None:
            raise ValueError("only failed scan path outcomes may include an error")
        return self


class ScanPageOutcomePayload(WireModel):
    job_id: str = Field(min_length=1)
    source_id: str = Field(min_length=1)
    sequence: int = Field(ge=0)
    page_checksum: str = Field(pattern=r"^[0-9a-f]{64}$")
    results: list[ScanPathOutcome] = Field(
        default_factory=list, max_length=REMOTE_MAX_MANIFEST_PAGE_ENTRIES
    )

    @model_validator(mode="after")
    def validate_results(self) -> ScanPageOutcomePayload:
        paths = [item.path for item in self.results]
        if len(paths) != len(set(paths)):
            raise ValueError("scan page outcome paths must be unique")
        return self


class ScanPageOutcome(WireModel):
    checksum: str = Field(pattern=r"^[0-9a-f]{64}$")
    outcome: ScanPageOutcomePayload

    @model_validator(mode="after")
    def validate_checksum(self) -> ScanPageOutcome:
        expected = hashlib.sha256(canonical_wire_bytes(self.outcome)).hexdigest()
        if self.checksum != expected:
            raise ValueError("scan page outcome checksum mismatch")
        return self


class ScanPageOutcomeAck(WireModel):
    job_id: str = Field(min_length=1)
    sequence: int = Field(ge=0)
    checksum: str = Field(pattern=r"^[0-9a-f]{64}$")
    settled_count: int = Field(ge=0, le=REMOTE_MAX_MANIFEST_PAGE_ENTRIES)
    duplicate: bool = False
    checkpoint: ScanCheckpoint


class NormalizedRemoteDocument(WireModel):
    source_id: str = Field(min_length=1)
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
    documents: list[NormalizedRemoteDocument] = Field(
        default_factory=list, max_length=REMOTE_MAX_BATCH_DOCUMENTS
    )
    checkpoint: ScanCheckpoint | None = None


class BatchAck(WireModel):
    batch_id: str = Field(min_length=1)
    accepted_count: int = Field(ge=0)
    rejected_paths: dict[str, str] = Field(default_factory=dict)
    duplicate: bool = False


class JobProgress(WireModel):
    job_id: str = Field(min_length=1)
    completed_items: int = Field(ge=0)
    total_items: int | None = Field(default=None, ge=0)
    message: str | None = None


class JobCompletion(WireModel):
    job_id: str = Field(min_length=1)
    status: JobStatus
    reason: JobFailureReason | None = None
    detail: str | None = Field(default=None, max_length=2048)
    checkpoint: ScanCheckpoint | None = None
    browse_result: BrowseResult | None = None

    @field_validator("status", mode="before")
    @classmethod
    def parse_status(cls, value: object) -> object:
        return JobStatus(value) if isinstance(value, str) else value

    @field_validator("reason", mode="before")
    @classmethod
    def parse_reason(cls, value: object) -> object:
        return JobFailureReason(value) if isinstance(value, str) else value

    @model_validator(mode="after")
    def validate_browse_result(self) -> JobCompletion:
        if self.browse_result is not None and self.status != JobStatus.SUCCEEDED:
            raise ValueError("browse_result is only allowed for succeeded jobs")
        return self


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
