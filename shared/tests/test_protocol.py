import pytest
from onesearch_shared.protocol import (
    PROTOCOL_VERSION,
    AgentEnrollmentRequest,
    AgentEnrollmentResponse,
    AgentHeartbeat,
    AgentJobLease,
    AllowedRoot,
    BatchAck,
    BrowseRequest,
    BrowseResponse,
    DirectoryEntry,
    DocumentBatch,
    JobCompletion,
    JobFailureReason,
    JobKind,
    JobProgress,
    JobStatus,
    NormalizedRemoteDocument,
    ProcessingMode,
    ProtocolCompatibilityResponse,
    ProtocolVersionRange,
    ScanCheckpoint,
    ScanFile,
    ScanManifest,
)
from pydantic import ValidationError


def assert_json_round_trip(model):
    assert type(model).model_validate_json(model.model_dump_json()) == model


def test_heartbeat_defaults_to_current_protocol_and_round_trips_strictly():
    heartbeat = AgentHeartbeat(agent_version="1.4.0", platform="windows-amd64")

    assert heartbeat.protocol_version == PROTOCOL_VERSION == 1
    assert_json_round_trip(heartbeat)

    with pytest.raises(ValidationError, match="extra_forbidden"):
        AgentHeartbeat.model_validate(
            {
                "agent_version": "1.4.0",
                "platform": "windows-amd64",
                "unexpected": True,
            }
        )


def test_wire_enum_values_are_stable():
    assert {mode.value for mode in ProcessingMode} == {"on_agent", "on_server"}
    assert {kind.value for kind in JobKind} == {
        "scan",
        "browse",
        "extract_file",
        "stream_file",
    }
    assert {status.value for status in JobStatus} == {"succeeded", "failed", "cancelled"}


def test_enrollment_round_trip_includes_allowed_roots():
    request = AgentEnrollmentRequest(
        enrollment_token="enroll-secret",
        agent_name="office-pc",
        agent_version="1.4.0",
        platform="windows-amd64",
    )
    response = AgentEnrollmentResponse(
        agent_id="agent-1",
        agent_token="agent-secret",
        allowed_roots=[
            AllowedRoot(root_id="documents", path="C:/Users/Ada/Documents", display_name="Documents")
        ],
    )

    assert_json_round_trip(request)
    assert_json_round_trip(response)
    assert response.protocol_version == PROTOCOL_VERSION


def test_browse_round_trip_preserves_directory_entries():
    request = BrowseRequest(root_id="documents", path="reports")
    response = BrowseResponse(
        root_id="documents",
        path="reports",
        entries=[
            DirectoryEntry(
                name="annual.pdf",
                path="reports/annual.pdf",
                is_directory=False,
                size_bytes=4096,
                modified_at=1_721_234_567,
            )
        ],
    )

    assert_json_round_trip(request)
    assert_json_round_trip(response)


def test_scan_manifest_round_trip_preserves_checkpoint():
    manifest = ScanManifest(
        job_id="job-1",
        source_id=7,
        files=[
            ScanFile(
                path="reports/annual.pdf",
                size_bytes=4096,
                modified_at=1_721_234_567,
                content_hash="sha256:abc123",
            )
        ],
        checkpoint=ScanCheckpoint(cursor="page:1", scanned_count=1),
        complete=False,
    )

    assert_json_round_trip(manifest)


def test_document_batch_and_ack_round_trip():
    batch = DocumentBatch(
        job_id="job-2",
        batch_id="batch-1",
        documents=[
            NormalizedRemoteDocument(
                source_id=7,
                path="notes/readme.md",
                title="Read me",
                content="Remote content",
                mime_type="text/markdown",
                modified_at=1_721_234_567,
                metadata={"author": "Ada", "page_count": 1},
            )
        ],
        checkpoint=ScanCheckpoint(cursor="document:1", scanned_count=1),
    )
    acknowledgement = BatchAck(batch_id="batch-1", accepted_count=1)

    assert_json_round_trip(batch)
    assert_json_round_trip(acknowledgement)


def test_progress_and_completion_round_trip():
    progress = JobProgress(job_id="job-2", completed_items=1, total_items=2, message="Indexing")
    completion = JobCompletion(
        job_id="job-2",
        status=JobStatus.FAILED,
        reason=JobFailureReason.EXTRACTION_FAILED,
        detail="Unsupported document",
        checkpoint=ScanCheckpoint(cursor="document:1", scanned_count=1),
    )

    assert_json_round_trip(progress)
    assert_json_round_trip(completion)


def test_mutable_defaults_are_independent():
    first_lease = AgentJobLease(id="job-1", kind=JobKind.SCAN, lease_token="lease-1")
    second_lease = AgentJobLease(id="job-2", kind=JobKind.SCAN, lease_token="lease-2")
    first_batch = DocumentBatch(job_id="job-1", batch_id="batch-1")
    second_batch = DocumentBatch(job_id="job-2", batch_id="batch-2")

    first_lease.payload["cursor"] = "next"
    first_batch.documents.append(
        NormalizedRemoteDocument(source_id=7, path="a.txt", content="A", modified_at=1)
    )

    assert second_lease.payload == {}
    assert second_batch.documents == []


def test_open_ended_payloads_still_require_json_values():
    with pytest.raises(ValidationError):
        AgentJobLease(
            id="job-1",
            kind=JobKind.SCAN,
            lease_token="lease-1",
            payload={"paths": {"not", "json"}},
        )


@pytest.mark.parametrize("value", [float("nan"), float("inf"), float("-inf")])
def test_job_payload_rejects_non_finite_numbers(value):
    with pytest.raises(ValidationError):
        AgentJobLease(
            id="job-1",
            kind=JobKind.SCAN,
            lease_token="lease-1",
            payload={"score": value},
        )


@pytest.mark.parametrize("value", [float("nan"), float("inf"), float("-inf")])
def test_document_metadata_rejects_non_finite_numbers(value):
    with pytest.raises(ValidationError):
        NormalizedRemoteDocument(
            source_id=7,
            path="a.txt",
            content="A",
            modified_at=1,
            metadata={"score": value},
        )


def test_protocol_compatibility_reports_incompatible_versions():
    supported = ProtocolVersionRange(minimum_version=1, maximum_version=1)

    response = ProtocolCompatibilityResponse.for_version(2, supported)

    assert response.compatible is False
    assert response.agent_protocol_version == 2
    assert response.supported_range == supported
    assert_json_round_trip(response)


def test_protocol_version_range_rejects_reversed_bounds():
    with pytest.raises(ValidationError, match="maximum_version"):
        ProtocolVersionRange(minimum_version=2, maximum_version=1)
