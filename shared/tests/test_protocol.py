import pytest
from onesearch_shared.protocol import (
    PROTOCOL_VERSION,
    REMOTE_JOB_HEARTBEAT_SECONDS,
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
    ScanFailure,
    ScanFile,
    ScanManifest,
    remote_path_hash,
)
from pydantic import ValidationError


def assert_json_round_trip(model):
    assert type(model).model_validate_json(model.model_dump_json()) == model


def test_heartbeat_defaults_to_current_protocol_and_round_trips_strictly():
    heartbeat = AgentHeartbeat(agent_version="1.4.0", platform="windows-amd64")

    assert heartbeat.protocol_version == PROTOCOL_VERSION == 1
    assert_json_round_trip(heartbeat)


def test_remote_job_heartbeat_interval_is_shorter_than_the_server_lease():
    assert REMOTE_JOB_HEARTBEAT_SECONDS == 20 < 60


def test_remote_path_hash_is_stable_lowercase_utf8_sha256():
    value = remote_path_hash("café/資料.txt")
    assert value == remote_path_hash("café/資料.txt")
    assert len(value) == 64 and value == value.lower()

    with pytest.raises(ValidationError, match="extra_forbidden"):
        AgentHeartbeat.model_validate(
            {
                "agent_version": "1.4.0",
                "platform": "windows-amd64",
                "unexpected": True,
            }
        )


@pytest.mark.parametrize(
    ("model_type", "data"),
    [
        (
            AgentHeartbeat,
            {"protocol_version": "1", "agent_version": "1.4.0", "platform": "windows-amd64"},
        ),
        (
            NormalizedRemoteDocument,
            {"source_id": 7, "path": "a.txt", "content": "A", "modified_at": 1},
        ),
    ],
)
def test_python_inputs_do_not_coerce_numeric_strings(model_type, data):
    with pytest.raises(ValidationError):
        model_type.model_validate(data)


@pytest.mark.parametrize(
    ("model_type", "data"),
    [
        (
            AgentHeartbeat,
            {"protocol_version": 0, "agent_version": "1.4.0", "platform": "windows-amd64"},
        ),
        (
            AgentEnrollmentRequest,
            {
                "protocol_version": 0,
                "enrollment_token": "enroll-secret",
                "agent_name": "office-pc",
                "agent_version": "1.4.0",
                "platform": "windows-amd64",
            },
        ),
        (
            AgentEnrollmentResponse,
            {"protocol_version": 0, "agent_id": "agent-1", "agent_token": "agent-secret"},
        ),
    ],
)
def test_protocol_versions_must_be_positive(model_type, data):
    with pytest.raises(ValidationError):
        model_type.model_validate(data)


def test_strict_models_parse_correct_json_enum_values():
    lease = AgentJobLease.model_validate_json(
        '{"id":"job-1","kind":"scan","processing_mode":"on_agent","lease_token":"lease-1"}'
    )

    assert lease.kind is JobKind.SCAN
    assert lease.processing_mode is ProcessingMode.ON_AGENT


def test_job_lease_uses_the_string_source_identifier_used_by_the_database():
    lease = AgentJobLease(
        id="job-1", kind=JobKind.SCAN, source_id="remote-source", lease_token="lease-1"
    )

    assert lease.source_id == "remote-source"


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
        allowed_roots=[AllowedRoot(root_id="documents", path="C:/Users/Ada/Documents")],
    )
    response = AgentEnrollmentResponse(
        agent_id="agent-1",
        agent_token="agent-secret",
        allowed_roots=[
            AllowedRoot(
                root_id="documents", path="C:/Users/Ada/Documents", display_name="Documents"
            )
        ],
    )

    assert_json_round_trip(request)
    assert_json_round_trip(response)
    assert response.protocol_version == PROTOCOL_VERSION


def test_enrollment_requires_at_least_one_allowed_root():
    with pytest.raises(ValidationError, match="allowed_roots"):
        AgentEnrollmentRequest(
            enrollment_token="enroll-secret",
            agent_name="office-pc",
            agent_version="1.4.0",
            platform="windows-amd64",
            allowed_roots=[],
        )


@pytest.mark.parametrize(
    ("model_type", "field", "value"),
    [
        (AgentEnrollmentRequest, "agent_name", "a" * 121),
        (AgentEnrollmentRequest, "agent_version", "v" * 41),
        (AgentEnrollmentRequest, "platform", "p" * 81),
        (AgentHeartbeat, "agent_version", "v" * 41),
        (AgentHeartbeat, "platform", "p" * 81),
    ],
)
def test_agent_identity_fields_match_server_storage_limits(model_type, field, value):
    data = {"agent_version": "1.4.0", "platform": "windows-amd64"}
    if model_type is AgentEnrollmentRequest:
        data.update(
            {
                "enrollment_token": "enroll-secret",
                "agent_name": "office-pc",
                "allowed_roots": [AllowedRoot(root_id="documents", path="C:/Documents")],
            }
        )
    data[field] = value

    with pytest.raises(ValidationError):
        model_type.model_validate(data)


def test_agent_identity_and_root_id_fields_are_trimmed():
    request = AgentEnrollmentRequest(
        enrollment_token="enroll-secret",
        agent_name="  office-pc  ",
        agent_version="  1.4.0  ",
        platform="  windows-amd64  ",
        allowed_roots=[AllowedRoot(root_id="  documents  ", path="C:/My Documents")],
    )
    heartbeat = AgentHeartbeat(agent_version="  1.4.0  ", platform="  windows-amd64  ")

    assert request.agent_name == "office-pc"
    assert request.agent_version == heartbeat.agent_version == "1.4.0"
    assert request.platform == heartbeat.platform == "windows-amd64"
    assert request.allowed_roots[0].root_id == "documents"
    assert request.allowed_roots[0].path == "C:/My Documents"


@pytest.mark.parametrize("path", [" C:/Documents", "C:/Documents "])
def test_allowed_root_path_rejects_surrounding_whitespace(path):
    with pytest.raises(ValidationError):
        AllowedRoot(root_id="documents", path=path)


@pytest.mark.parametrize(
    ("model_type", "field"),
    [
        (AgentEnrollmentRequest, "agent_name"),
        (AgentEnrollmentRequest, "agent_version"),
        (AgentEnrollmentRequest, "platform"),
        (AgentHeartbeat, "agent_version"),
        (AgentHeartbeat, "platform"),
        (AllowedRoot, "root_id"),
        (AllowedRoot, "path"),
    ],
)
def test_agent_identity_and_allowed_root_fields_reject_whitespace_only(model_type, field):
    if model_type is AgentEnrollmentRequest:
        data = {
            "enrollment_token": "enroll-secret",
            "agent_name": "office-pc",
            "agent_version": "1.4.0",
            "platform": "windows-amd64",
            "allowed_roots": [AllowedRoot(root_id="documents", path="C:/Documents")],
        }
    elif model_type is AgentHeartbeat:
        data = {"agent_version": "1.4.0", "platform": "windows-amd64"}
    else:
        data = {"root_id": "documents", "path": "C:/Documents"}
    data[field] = "   "

    with pytest.raises(ValidationError):
        model_type.model_validate(data)


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
        source_id="remote-1",
        files=[
            ScanFile(
                path="reports/annual.pdf",
                path_hash=remote_path_hash("reports/annual.pdf"),
                size_bytes=4096,
                modified_at=1_721_234_567,
                content_hash="sha256:abc123",
            )
        ],
        checkpoint=ScanCheckpoint(cursor="page:1", scanned_count=1),
        complete=False,
    )

    assert_json_round_trip(manifest)


def test_complete_manifest_carries_bounded_file_failures_and_rejects_duplicate_paths():
    manifest = ScanManifest(
        job_id="job-1",
        source_id="remote-1",
        files=[
            ScanFile(path="a.txt", path_hash=remote_path_hash("a.txt"), size_bytes=1, modified_at=1)
        ],
        failures=[ScanFailure(path="a.txt", error="extract failed")],
        complete=True,
    )
    assert_json_round_trip(manifest)
    with pytest.raises(ValidationError):
        ScanManifest(
            job_id="job-1",
            source_id="remote-1",
            files=[
                ScanFile(
                    path="a.txt", path_hash=remote_path_hash("a.txt"), size_bytes=1, modified_at=1
                ),
                ScanFile(
                    path="a.txt", path_hash=remote_path_hash("a.txt"), size_bytes=1, modified_at=1
                ),
            ],
        )


def test_document_batch_and_ack_round_trip():
    batch = DocumentBatch(
        job_id="job-2",
        batch_id="batch-1",
        documents=[
            NormalizedRemoteDocument(
                source_id="remote-1",
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
    acknowledgement = BatchAck(batch_id="batch-1", accepted_count=1, duplicate=False)

    assert_json_round_trip(batch)
    assert_json_round_trip(acknowledgement)


def test_remote_document_and_manifest_accept_string_source_ids_from_the_database():
    document = NormalizedRemoteDocument(
        source_id="remote-1", path="a.txt", content="A", modified_at=1
    )
    manifest = ScanManifest(job_id="job-1", source_id="remote-1")
    assert document.source_id == manifest.source_id == "remote-1"


def test_batch_ack_reports_when_a_retry_was_already_accepted():
    assert BatchAck(batch_id="batch-1", accepted_count=1, duplicate=True).duplicate is True


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


def test_completion_parses_failure_reason_from_ordinary_json():
    completion = JobCompletion.model_validate_json(
        '{"job_id":"job-1","status":"failed","reason":"internal_error","detail":"boom"}'
    )
    assert completion.reason is JobFailureReason.INTERNAL_ERROR


def test_mutable_defaults_are_independent():
    first_lease = AgentJobLease(id="job-1", kind=JobKind.SCAN, lease_token="lease-1")
    second_lease = AgentJobLease(id="job-2", kind=JobKind.SCAN, lease_token="lease-2")
    first_batch = DocumentBatch(job_id="job-1", batch_id="batch-1")
    second_batch = DocumentBatch(job_id="job-2", batch_id="batch-2")

    first_lease.payload["cursor"] = "next"
    first_batch.documents.append(
        NormalizedRemoteDocument(source_id="remote-1", path="a.txt", content="A", modified_at=1)
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
            source_id="remote-1",
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


def test_protocol_compatibility_rejects_contradictory_model_input():
    with pytest.raises(ValidationError, match="compatible"):
        ProtocolCompatibilityResponse(
            agent_protocol_version=2,
            supported_range=ProtocolVersionRange(minimum_version=1, maximum_version=1),
            compatible=True,
        )


def test_protocol_compatibility_rejects_contradictory_json_input():
    with pytest.raises(ValidationError, match="compatible"):
        ProtocolCompatibilityResponse.model_validate_json(
            '{"agent_protocol_version":1,"supported_range":'
            '{"minimum_version":1,"maximum_version":1},"compatible":false}'
        )


def test_protocol_version_range_rejects_reversed_bounds():
    with pytest.raises(ValidationError, match="maximum_version"):
        ProtocolVersionRange(minimum_version=2, maximum_version=1)
