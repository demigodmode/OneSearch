import asyncio
import multiprocessing
import time
from pathlib import Path

import onesearch_agent.worker as worker_module
import pytest
from onesearch_agent.scan_spool import ScanSpool
from onesearch_agent.worker import ExtractionError, batch_documents, extract_confined
from onesearch_shared import (
    AllowedRoot,
    DocumentBatch,
    NormalizedRemoteDocument,
    ScanFile,
    canonical_wire_bytes,
    remote_path_hash,
)


def blocking_extractor_process(_snapshot, _source_id, _extraction, _connection):
    """Picklable test extractor entrypoint that never returns on its own."""
    while True:
        time.sleep(0.1)


def extraction(source_name="source", policy="metadata_only"):
    return {
        "source_name": source_name,
        "unsupported_file_policy": policy,
        "index_gps_metadata": False,
        "max_text_file_size_mb": 10,
        "max_pdf_file_size_mb": 50,
        "max_office_file_size_mb": 50,
        "image_metadata_max_size_mb": 100,
        "raw_metadata_mode": "auto",
        "epub_extraction_max_size_mb": 100,
        "comic_extraction_max_size_mb": 100,
        "media_metadata_mode": "auto",
        "media_probe_max_size_mb": 0,
        "text_extraction_timeout": 5,
        "pdf_extraction_timeout": 30,
        "office_extraction_timeout": 30,
        "raw_metadata_timeout_seconds": 10,
    }


@pytest.mark.asyncio
async def test_extract_confined_normalizes_logical_metadata(tmp_path: Path):
    file = tmp_path / "note.txt"
    file.write_text("hello")
    stat = file.stat()
    expected = ScanFile(
        path="note.txt",
        path_hash=remote_path_hash("note.txt"),
        size_bytes=stat.st_size,
        modified_at=stat.st_mtime_ns,
    )
    doc = await extract_confined(
        "r",
        "note.txt",
        [AllowedRoot(root_id="r", path=str(tmp_path))],
        expected=expected,
        source_id="s",
        extraction=extraction(),
        max_snapshot_bytes=1024,
    )
    assert (
        doc.path == "note.txt"
        and doc.source_id == "s"
        and doc.size_bytes == stat.st_size
        and doc.modified_at == stat.st_mtime_ns
    )


@pytest.mark.asyncio
async def test_extract_confined_opens_nested_source_file_but_keeps_source_relative_identity(
    tmp_path: Path,
):
    source = tmp_path / "team"
    source.mkdir()
    file = source / "note.txt"
    file.write_text("hello")
    info = file.stat()

    document = await extract_confined(
        "r",
        "note.txt",
        [AllowedRoot(root_id="r", path=str(tmp_path))],
        source_prefix="team",
        expected=ScanFile(
            path="note.txt",
            path_hash=remote_path_hash("note.txt"),
            size_bytes=info.st_size,
            modified_at=info.st_mtime_ns,
        ),
        source_id="s",
        extraction=extraction(),
        max_snapshot_bytes=1024,
    )

    assert document is not None
    assert document.path == "note.txt" and document.content == "hello"


@pytest.mark.asyncio
async def test_extract_confined_skips_and_rejects_changed_or_oversize(tmp_path: Path):
    file = tmp_path / "note.unknown"
    file.write_text("hello")
    stat = file.stat()
    expected = ScanFile(
        path="note.unknown",
        path_hash=remote_path_hash("note.unknown"),
        size_bytes=stat.st_size,
        modified_at=stat.st_mtime_ns,
    )
    roots = [AllowedRoot(root_id="r", path=str(tmp_path))]
    assert (
        await extract_confined(
            "r",
            "note.unknown",
            roots,
            expected=expected,
            source_id="s",
            extraction=extraction(policy="skip"),
            max_snapshot_bytes=1024,
        )
        is None
    )
    with pytest.raises(ExtractionError):
        await extract_confined(
            "r",
            "note.unknown",
            roots,
            expected=expected,
            source_id="s",
            extraction=extraction(),
            max_snapshot_bytes=1,
        )
    metadata = await extract_confined(
        "r",
        "note.unknown",
        roots,
        expected=expected,
        source_id="s",
        extraction=extraction(),
        max_snapshot_bytes=1024,
    )
    assert metadata is not None and metadata.path == "note.unknown"
    changed = ScanFile(
        path="note.unknown",
        path_hash=remote_path_hash("note.unknown"),
        size_bytes=999,
        modified_at=stat.st_mtime_ns,
    )
    with pytest.raises(ExtractionError):
        await extract_confined(
            "r",
            "note.unknown",
            roots,
            expected=changed,
            source_id="s",
            extraction=extraction(),
            max_snapshot_bytes=1024,
        )


def test_batches_are_bounded_and_deterministic():
    docs = [
        NormalizedRemoteDocument(source_id="s", path=f"{n}.txt", content="x" * 20, modified_at=1)
        for n in range(3)
    ]
    batches = list(batch_documents("job", docs, max_documents=2, max_bytes=10_000))

    assert [len(batch.documents) for batch in batches] == [2, 1]
    assert batches[0].batch_id.startswith("job:0:")


@pytest.mark.asyncio
async def test_process_extractor_preserves_logical_original_basename(tmp_path):
    file = tmp_path / "name.with.dot.txt"
    file.write_text("x")
    info = file.stat()
    expected = ScanFile(
        path=file.name,
        path_hash=remote_path_hash(file.name),
        size_bytes=1,
        modified_at=info.st_mtime_ns,
    )
    document = await extract_confined(
        "r",
        file.name,
        [AllowedRoot(root_id="r", path=str(tmp_path))],
        expected=expected,
        source_id="s",
        extraction=extraction(),
        max_snapshot_bytes=10,
    )
    assert document.path == file.name and document.title == "x"


@pytest.mark.asyncio
async def test_blocking_process_extractor_times_out_cleans_snapshot_and_allows_next_file(
    tmp_path, monkeypatch
):
    file = tmp_path / "x.txt"
    file.write_text("x")
    info = file.stat()
    expected = ScanFile(
        path=file.name,
        path_hash=remote_path_hash(file.name),
        size_bytes=1,
        modified_at=info.st_mtime_ns,
    )
    created, process_ids = [], []
    temporary_directory = worker_module.tempfile.TemporaryDirectory

    class TrackedTemporaryDirectory:
        def __init__(self, *args, **kwargs):
            self.inner = temporary_directory(*args, dir=tmp_path, **kwargs)

        def __enter__(self):
            directory = self.inner.__enter__()
            created.append(Path(directory))
            return directory

        def __exit__(self, *args):
            return self.inner.__exit__(*args)

    monkeypatch.setattr(worker_module.tempfile, "TemporaryDirectory", TrackedTemporaryDirectory)
    config = extraction()
    config["text_extraction_timeout"] = 1
    with pytest.raises(ExtractionError, match="timed out"):
        await extract_confined(
            "r",
            file.name,
            [AllowedRoot(root_id="r", path=str(tmp_path))],
            expected=expected,
            source_id="s",
            extraction=config,
            max_snapshot_bytes=10,
            _process_target=blocking_extractor_process,
            _on_process_start=process_ids.append,
        )
    assert created and not created[0].exists()
    assert process_ids and all(
        child.pid != process_ids[0] for child in multiprocessing.active_children()
    )
    succeeding_config = extraction()
    succeeding_config["text_extraction_timeout"] = 5
    document = await extract_confined(
        "r",
        file.name,
        [AllowedRoot(root_id="r", path=str(tmp_path))],
        expected=expected,
        source_id="s",
        extraction=succeeding_config,
        max_snapshot_bytes=10,
    )
    assert document is not None and document.path == file.name


@pytest.mark.asyncio
async def test_cancelling_blocking_process_extraction_leaves_no_child(tmp_path):
    file = tmp_path / "cancel.txt"
    file.write_text("x")
    info = file.stat()
    process_ids = []
    task = asyncio.create_task(
        extract_confined(
            "r",
            file.name,
            [AllowedRoot(root_id="r", path=str(tmp_path))],
            expected=ScanFile(
                path=file.name,
                path_hash=remote_path_hash(file.name),
                size_bytes=1,
                modified_at=info.st_mtime_ns,
            ),
            source_id="s",
            extraction=extraction(),
            max_snapshot_bytes=10,
            _process_target=blocking_extractor_process,
            _on_process_start=process_ids.append,
        )
    )
    for _ in range(100):
        if process_ids:
            break
        await asyncio.sleep(0.01)
    assert process_ids
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert all(child.pid != process_ids[0] for child in multiprocessing.active_children())


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("chunks", "after_mtime"),
    [([b"abcdef"], 1), ([b"abc"], 1), ([b"abcde"], 2)],
)
async def test_pinned_copy_races_reject_before_extractor(
    tmp_path, monkeypatch, chunks, after_mtime
):
    import contextlib
    import stat as stat_module
    from types import SimpleNamespace

    class Handle:
        def __init__(self):
            self.chunks = list(chunks)

        def fileno(self):
            return 77

        def read(self, size):
            return self.chunks.pop(0) if self.chunks else b""

    handle = Handle()
    calls = []

    @contextlib.contextmanager
    def opened(*args, **kwargs):
        yield handle

    states = [
        SimpleNamespace(st_mode=stat_module.S_IFREG, st_size=5, st_mtime_ns=1),
        SimpleNamespace(st_mode=stat_module.S_IFREG, st_size=5, st_mtime_ns=after_mtime),
    ]
    real_fstat = worker_module.os.fstat

    def controlled_fstat(fd):
        return states.pop(0) if fd == 77 else real_fstat(fd)

    monkeypatch.setattr(worker_module, "open_confined_file", opened)
    monkeypatch.setattr(worker_module.os, "fstat", controlled_fstat)
    monkeypatch.setattr(worker_module, "choose_extractor", lambda *args: calls.append(args))
    with pytest.raises(ExtractionError):
        await extract_confined(
            "r",
            "x.txt",
            [],
            expected=ScanFile(
                path="x.txt", path_hash=remote_path_hash("x.txt"), size_bytes=5, modified_at=1
            ),
            source_id="s",
            extraction=extraction(),
            max_snapshot_bytes=5,
        )
    assert calls == []


@pytest.mark.asyncio
async def test_text_snapshot_matches_backend_without_temp_path_leak(tmp_path, monkeypatch):
    file = tmp_path / "note.txt"
    file.write_text("hello parity")
    info = file.stat()
    expected = ScanFile(
        path="note.txt",
        path_hash=remote_path_hash("note.txt"),
        size_bytes=info.st_size,
        modified_at=info.st_mtime_ns,
    )
    from app.services.extractor_config import choose_extractor as real_choose

    backend = real_choose(str(file), "s", "source", extraction())
    original = await backend.extract_with_timeout(str(file))
    captured = []

    def choose(path, *args):
        captured.append(Path(path))
        return real_choose(path, *args)

    monkeypatch.setattr(worker_module, "choose_extractor", choose)
    remote = await extract_confined(
        "r",
        "note.txt",
        [AllowedRoot(root_id="r", path=str(tmp_path))],
        expected=expected,
        source_id="s",
        extraction=extraction(),
        max_snapshot_bytes=1024,
    )
    assert remote.content == original.content and remote.title == original.title
    rendered = str({"title": remote.title, "content": remote.content, "metadata": remote.metadata})
    assert str(captured[0]) not in rendered and str(captured[0].parent) not in rendered


def test_streaming_builder_splits_by_count():
    from onesearch_agent.worker import StreamingBatchBuilder

    builder = StreamingBatchBuilder("job", max_documents=2, max_bytes=10000)
    docs = [
        NormalizedRemoteDocument(source_id="s", path=f"{n}.txt", content="x", modified_at=1)
        for n in range(3)
    ]
    emitted = []
    for doc in docs:
        emitted.extend(builder.add(doc))
    emitted.extend(builder.finish())
    assert [len(batch.documents) for batch in emitted] == [2, 1]


def test_streaming_builder_rejects_oversized_single_document():
    from onesearch_agent.worker import OversizedDocumentError, StreamingBatchBuilder

    builder = StreamingBatchBuilder("job", max_bytes=20)
    with pytest.raises(OversizedDocumentError, match="huge.txt"):
        builder.add(
            NormalizedRemoteDocument(
                source_id="s", path="huge.txt", content="x" * 100, modified_at=1
            )
        )
    assert builder.finish() == []


def test_streaming_batches_are_canonical_utf8_and_deterministic():
    from onesearch_agent.worker import StreamingBatchBuilder, _batch_wire_bytes

    first = NormalizedRemoteDocument(
        source_id="s", path="ü.txt", content="\u0000é", modified_at=1, metadata={"b": 2, "a": 1}
    )
    second = NormalizedRemoteDocument(
        source_id="s", path="ü.txt", content="\u0000é", modified_at=1, metadata={"a": 1, "b": 2}
    )
    assert _batch_wire_bytes(
        DocumentBatch(job_id="j", batch_id="j:0:" + "0" * 64, documents=[first])
    ) == _batch_wire_bytes(
        DocumentBatch(job_id="j", batch_id="j:0:" + "0" * 64, documents=[second])
    )
    one = StreamingBatchBuilder("j", max_bytes=10_000)
    two = StreamingBatchBuilder("j", max_bytes=10_000)
    assert one.add(first) == two.add(second) == []
    assert one.finish()[0].batch_id == two.finish()[0].batch_id


def test_streaming_exact_boundary_and_nonpositive_caps():
    from onesearch_agent.worker import BatchBuildError, StreamingBatchBuilder, _batch_wire_bytes

    doc = NormalizedRemoteDocument(source_id="s", path="x", content="x", modified_at=1)
    size = len(
        _batch_wire_bytes(DocumentBatch(job_id="j", batch_id="j:0:" + "0" * 64, documents=[doc]))
    )
    assert StreamingBatchBuilder("j", max_bytes=size).add(doc) == []
    from onesearch_agent.worker import OversizedDocumentError

    with pytest.raises(OversizedDocumentError):
        StreamingBatchBuilder("j", max_bytes=size - 1).add(doc)
    with pytest.raises(BatchBuildError):
        StreamingBatchBuilder("j", max_bytes=0)


@pytest.mark.asyncio
async def test_batch_ambiguity_retries_the_identical_batch_body():
    from onesearch_agent.client import AgentAmbiguousResultError

    batch = DocumentBatch(
        job_id="j",
        batch_id="j:0:" + "a" * 64,
        documents=[NormalizedRemoteDocument(source_id="s", path="a.txt", content="x", modified_at=1)],
    )
    submitted = []

    async def submit():
        submitted.append(canonical_wire_bytes(batch))
        if len(submitted) == 1:
            raise AgentAmbiguousResultError("receipt lost")

    await worker_module._submit_idempotent(submit, attempts=2, sleep=lambda _: asyncio.sleep(0))
    assert submitted == [canonical_wire_bytes(batch), canonical_wire_bytes(batch)]


@pytest.mark.asyncio
async def test_lease_keeper_heartbeats_and_closes_cleanly():
    from types import SimpleNamespace

    progress = []

    async def heartbeat(_job_id, item, _token):
        progress.append(item.completed_items)

    keeper = worker_module.LeaseKeeper(
        SimpleNamespace(id="j", lease_token="t"),
        SimpleNamespace(job_heartbeat=heartbeat),
    )
    await keeper.start()
    await keeper.advance()
    await keeper.close()
    assert progress == [0, 1]
    assert keeper._task.done()


@pytest.mark.asyncio
async def test_lease_keeper_surfaces_background_lease_loss():
    from types import SimpleNamespace

    from onesearch_agent.client import JobLeaseError

    calls = 0

    async def heartbeat(*_args):
        nonlocal calls
        calls += 1
        if calls > 1:
            raise JobLeaseError("lost")

    async def tick(_interval):
        await asyncio.sleep(0)

    keeper = worker_module.LeaseKeeper(
        SimpleNamespace(id="j", lease_token="t"),
        SimpleNamespace(job_heartbeat=heartbeat),
        interval=1,
        sleep=tick,
    )
    await keeper.start()
    for _ in range(10):
        await asyncio.sleep(0)
        if keeper.error is not None:
            break
    with pytest.raises(JobLeaseError):
        await keeper.check()
    await keeper.close()



@pytest.mark.asyncio
async def test_agent_honors_configured_text_size_limit(tmp_path):
    file = tmp_path / "large.txt"
    with file.open("wb") as handle:
        handle.seek(1024 * 1024)
        handle.write(b"x")
    info = file.stat()
    config = extraction()
    config["max_text_file_size_mb"] = 1
    from app.services.extractor_config import choose_extractor

    backend = choose_extractor(str(file), "s", "source", config)
    with pytest.raises(ValueError, match="too large"):
        await backend.extract_with_timeout(str(file))
    with pytest.raises(ValueError, match="too large"):
        await extract_confined(
            "r",
            "large.txt",
            [AllowedRoot(root_id="r", path=str(tmp_path))],
            expected=ScanFile(
                path="large.txt",
                path_hash=remote_path_hash("large.txt"),
                size_bytes=info.st_size,
                modified_at=info.st_mtime_ns,
            ),
            source_id="s",
            extraction=config,
            max_snapshot_bytes=2 * 1024 * 1024,
        )


@pytest.mark.asyncio
@pytest.mark.skipif(__import__("os").name == "nt", reason="POSIX modes")
async def test_snapshot_directory_is_private_on_posix(tmp_path, monkeypatch):
    file = tmp_path / "x.txt"
    file.write_text("x")
    info = file.stat()
    seen = []
    temporary_directory = worker_module.tempfile.TemporaryDirectory

    class TrackedTemporaryDirectory:
        def __init__(self, *args, **kwargs):
            self.inner = temporary_directory(*args, **kwargs)

        def __enter__(self):
            directory = self.inner.__enter__()
            seen.append(Path(directory).stat().st_mode & 0o777)
            return directory

        def __exit__(self, *args):
            return self.inner.__exit__(*args)

    monkeypatch.setattr(worker_module.tempfile, "TemporaryDirectory", TrackedTemporaryDirectory)
    await extract_confined(
        "r",
        "x.txt",
        [AllowedRoot(root_id="r", path=str(tmp_path))],
        expected=ScanFile(
            path="x.txt",
            path_hash=remote_path_hash("x.txt"),
            size_bytes=1,
            modified_at=info.st_mtime_ns,
        ),
        source_id="s",
        extraction=extraction(),
        max_snapshot_bytes=10,
    )
    assert seen == [0o700]



@pytest.mark.asyncio
async def test_run_invalid_payload_only_fails():
    from types import SimpleNamespace

    from onesearch_agent.worker import run_scan_job
    from onesearch_shared import JobFailureReason, JobKind, ProcessingMode

    lease = SimpleNamespace(
        id="j",
        kind=JobKind.SCAN,
        processing_mode=ProcessingMode.ON_AGENT,
        source_id="s",
        lease_token="t",
        payload={},
    )

    class C:
        def __init__(self):
            self.calls = []

        async def complete(self, *a):
            self.calls.append(a[1])

    c = C()
    await run_scan_job(lease, c, roots=[])
    assert len(c.calls) == 1 and c.calls[0].reason is JobFailureReason.PROTOCOL_INCOMPATIBLE


@pytest.mark.asyncio
@pytest.mark.parametrize("version", [1, 2, 4])
async def test_run_scan_job_rejects_every_non_v3_protocol_before_scanning(tmp_path, version):
    from onesearch_shared import JobFailureReason

    lease = _scan_lease(root_path=str(tmp_path))
    lease.payload["protocol_version"] = version

    class Client:
        def __init__(self):
            self.completions = []

        async def complete(self, _job_id, completion, _token):
            self.completions.append(completion)

    client = Client()
    await worker_module.run_scan_job(
        lease, client, roots=[AllowedRoot(root_id="r", path=str(tmp_path))]
    )
    assert [item.reason for item in client.completions] == [JobFailureReason.PROTOCOL_INCOMPATIBLE]


def _scan_lease(*, limits=None, root_path="/remote/root"):
    from types import SimpleNamespace

    from onesearch_shared import (
        REMOTE_MAX_MANIFEST_PAGE_BYTES,
        REMOTE_MAX_MANIFEST_PAGE_ENTRIES,
        JobKind,
        ProcessingMode,
    )

    return SimpleNamespace(
        id="j",
        kind=JobKind.SCAN,
        processing_mode=ProcessingMode.ON_AGENT,
        source_id="s",
        lease_token="t",
        payload={
            "protocol_version": 3,
            "full": True,
            "root_id": "r",
            "root_path": root_path,
            "include_patterns": None,
            "exclude_patterns": None,
            "extraction": extraction(),
            "limits": {
                "max_snapshot_bytes": 1024,
                "max_batch_documents": 10,
                "max_batch_bytes": 10_000,
                "max_entries_per_directory": 10,
                "max_manifest_page_entries": REMOTE_MAX_MANIFEST_PAGE_ENTRIES,
                "max_manifest_page_bytes": REMOTE_MAX_MANIFEST_PAGE_BYTES,
                **(limits or {}),
            },
        },
    )


def _v3_scan_lease(*, root_path="/remote/root"):
    return _scan_lease(root_path=root_path)


@pytest.mark.parametrize(
    "mutate",
    [
        lambda payload: payload.update(known_files={}),
        lambda payload: payload["limits"].update(max_scan_files=1),
        lambda payload: payload["limits"].update(max_manifest_page_entries=999),
    ],
)
def test_v3_scan_payload_rejects_legacy_and_noncanonical_limits(mutate):
    from onesearch_agent.worker import ScanPayload
    from pydantic import ValidationError

    lease = _v3_scan_lease()
    mutate(lease.payload)

    with pytest.raises(ValidationError):
        ScanPayload.model_validate(lease.payload)



@pytest.mark.asyncio
async def test_run_scan_job_rejects_non_most_specific_root_id(tmp_path, monkeypatch):
    from onesearch_shared import JobFailureReason

    source = tmp_path / "team"
    source.mkdir()
    lease = _scan_lease(root_path=str(source))

    class Client:
        def __init__(self):
            self.completions = []

        async def complete(self, _job_id, completion, _token):
            self.completions.append(completion)

    monkeypatch.setattr(
        worker_module,
        "RemoteScanner",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("must not scan")),
    )
    client = Client()
    await worker_module.run_scan_job(
        lease,
        client,
        roots=[
            AllowedRoot(root_id="r", path=str(tmp_path)),
            AllowedRoot(root_id="team", path=str(source)),
        ],
    )

    assert client.completions[0].reason is JobFailureReason.INVALID_REQUEST


def _browse_lease(path: Path, *, operation="validate"):
    from types import SimpleNamespace

    from onesearch_shared import JobKind

    return SimpleNamespace(
        id="browse-job",
        kind=JobKind.BROWSE,
        lease_token="browse-token",
        payload={"operation": operation, "root_path": str(path)},
    )


class _BrowseClient:
    def __init__(self):
        self.completions = []

    async def complete(self, _job_id, completion, _lease_token):
        self.completions.append(completion)


@pytest.mark.asyncio
async def test_dispatch_routes_scan_jobs(monkeypatch):
    called = []

    async def scan(lease, client, *, roots):
        called.append((lease, client, roots))

    monkeypatch.setattr(worker_module, "run_scan_job", scan)
    lease = _scan_lease()
    client = object()
    await worker_module.dispatch_job(lease, client, roots=[])
    assert called == [(lease, client, [])]


@pytest.mark.asyncio
@pytest.mark.parametrize("nested", [False, True])
async def test_browse_validation_accepts_exact_root_and_nested_directory(tmp_path, nested):
    target = tmp_path / "nested" if nested else tmp_path
    target.mkdir(exist_ok=True)
    client = _BrowseClient()

    await worker_module.run_browse_job(
        _browse_lease(target),
        client,
        roots=[AllowedRoot(root_id="root", path=str(tmp_path))],
    )

    assert [completion.status.value for completion in client.completions] == ["succeeded"]


@pytest.mark.asyncio
@pytest.mark.parametrize("case", ["outside", "missing", "malformed"])
async def test_browse_validation_rejects_bad_payloads_without_host_paths(tmp_path, case):
    target = {
        "outside": tmp_path.parent,
        "missing": tmp_path / "missing",
        "malformed": tmp_path,
    }[case]
    client = _BrowseClient()
    lease = _browse_lease(target, operation="unexpected" if case == "malformed" else "validate")

    await worker_module.run_browse_job(
        lease, client, roots=[AllowedRoot(root_id="root", path=str(tmp_path))]
    )

    completion = client.completions[0]
    assert completion.status.value == "failed"
    assert completion.detail == "invalid browse payload"
    assert str(tmp_path) not in completion.detail


@pytest.mark.asyncio
async def test_browse_validation_rejects_unreadable_directory_without_host_path(
    monkeypatch, tmp_path
):
    client = _BrowseClient()

    def unreadable(*_args, **_kwargs):
        raise OSError(f"permission denied: {tmp_path}")

    monkeypatch.setattr(worker_module, "list_confined_entries_page", unreadable)
    await worker_module.run_browse_job(
        _browse_lease(tmp_path),
        client,
        roots=[AllowedRoot(root_id="root", path=str(tmp_path))],
    )

    completion = client.completions[0]
    assert completion.status.value == "failed"
    assert completion.detail == "invalid browse payload"
    assert str(tmp_path) not in completion.detail


@pytest.mark.asyncio
async def test_dispatch_browse_never_calls_scan_job(monkeypatch, tmp_path):
    async def scan(*_args, **_kwargs):
        raise AssertionError("browse must not run scan")

    monkeypatch.setattr(worker_module, "run_scan_job", scan)
    client = _BrowseClient()
    await worker_module.dispatch_job(
        _browse_lease(tmp_path),
        client,
        roots=[AllowedRoot(root_id="root", path=str(tmp_path))],
    )
    assert client.completions[0].status.value == "succeeded"


@pytest.mark.asyncio
async def test_dispatch_unknown_kind_does_not_complete_job():
    from types import SimpleNamespace

    class Client:
        async def complete(self, *_args):
            raise AssertionError("unsupported job must remain uncompleted")

    lease = SimpleNamespace(kind=SimpleNamespace(value="unknown_kind"))
    with pytest.raises(ValueError, match="unsupported job kind"):
        await worker_module.dispatch_job(lease, Client(), roots=[])






@pytest.mark.asyncio
@pytest.mark.parametrize(
    "mutate",
    [
        lambda payload: payload.update(full=1),
        lambda payload: payload.update(root_path=None),
        lambda payload: payload["extraction"].pop("max_pdf_file_size_mb"),
        lambda payload: payload["extraction"].update(unexpected=True),
        lambda payload: payload["extraction"].update(index_gps_metadata=1),
        lambda payload: payload["extraction"].update(media_probe_max_size_mb=-1),
        lambda payload: payload["limits"].pop("max_batch_bytes"),
        lambda payload: payload["limits"].update(unexpected=1),
        lambda payload: payload["limits"].update(max_batch_bytes=True),
        lambda payload: payload["limits"].update(max_batch_bytes=0),
        lambda payload: payload["extraction"].update(unsupported_file_policy="execute"),
        lambda payload: payload["extraction"].update(media_metadata_mode="always"),
        lambda payload: payload.update(include_patterns="**/*"),
        lambda payload: payload.update(exclude_patterns=[1]),
        lambda payload: payload.update(root_id="missing"),
    ],
)
async def test_run_scan_job_rejects_malformed_payload_without_starting(
    monkeypatch, tmp_path, mutate
):
    class Scanner:
        def __init__(self, *args, **kwargs):
            raise AssertionError("invalid payload must not scan")

    class Client:
        def __init__(self):
            self.completions = []

        async def complete(self, *args):
            self.completions.append(args[1])

        async def job_heartbeat(self, *args):
            raise AssertionError("invalid payload must not heartbeat")

    monkeypatch.setattr(worker_module, "RemoteScanner", Scanner)
    lease = _scan_lease(root_path=str(tmp_path))
    mutate(lease.payload)
    client = Client()
    await worker_module.run_scan_job(
        lease, client, roots=[AllowedRoot(root_id="r", path=str(tmp_path))]
    )
    assert len(client.completions) == 1
    assert client.completions[0].reason.value == "invalid_request"


@pytest.mark.asyncio
@pytest.mark.parametrize("kind,mode", [(None, "on_agent"), ("delete", "on_agent"), ("scan", None)])
async def test_run_scan_job_rejects_unsupported_kind_or_mode_without_starting(
    monkeypatch, tmp_path, kind, mode
):
    from types import SimpleNamespace

    class Scanner:
        def __init__(self, *args, **kwargs):
            raise AssertionError("unsupported kind or mode must not scan")

    class Client:
        def __init__(self):
            self.completions = []

        async def complete(self, *args):
            self.completions.append(args[1])

        async def job_heartbeat(self, *args):
            raise AssertionError("unsupported kind or mode must not heartbeat")

    lease = _scan_lease(root_path=str(tmp_path))
    lease.kind = SimpleNamespace(value=kind) if kind is not None else None
    lease.processing_mode = SimpleNamespace(value=mode) if mode is not None else None
    monkeypatch.setattr(worker_module, "RemoteScanner", Scanner)
    client = Client()
    await worker_module.run_scan_job(
        lease, client, roots=[AllowedRoot(root_id="r", path=str(tmp_path))]
    )
    assert len(client.completions) == 1
    assert client.completions[0].reason.value == "invalid_request"




@pytest.mark.asyncio
@pytest.mark.parametrize(
    "outcomes,statuses,calls,raises",
    [
        (["ambiguous"], ["completed"], 1, None),
        (["ambiguous", None], ["running"], 2, None),
        (["ambiguous", "ambiguous"], ["running", "completed"], 2, None),
        (["ambiguous"], ["failed"], 1, "ambiguous"),
        (["ambiguous"], ["pending"], 1, "ambiguous"),
        (["ambiguous"], [RuntimeError("status down")], 1, "ambiguous"),
    ],
)
async def test_complete_recovery_is_bounded_and_never_reverses(outcomes, statuses, calls, raises):
    from types import SimpleNamespace

    from onesearch_agent.client import AgentAmbiguousResultError
    from onesearch_agent.worker import _complete_with_recovery
    from onesearch_shared import JobCompletion, JobStatus

    class Client:
        def __init__(self):
            self.outcomes, self.statuses, self.completions = list(outcomes), list(statuses), []

        async def complete(self, *args):
            self.completions.append(args[1])
            outcome = self.outcomes.pop(0)
            if outcome == "ambiguous":
                raise AgentAmbiguousResultError("lost")

        async def job_status(self, job_id):
            outcome = self.statuses.pop(0)
            if isinstance(outcome, Exception):
                raise outcome
            return SimpleNamespace(status=outcome)

    client = Client()
    lease = SimpleNamespace(id="j", lease_token="t")
    completion = JobCompletion(job_id="j", status=JobStatus.SUCCEEDED)
    if raises:
        with pytest.raises(AgentAmbiguousResultError):
            await _complete_with_recovery(client, lease, completion)
    else:
        await _complete_with_recovery(client, lease, completion)
    assert len(client.completions) == calls and all(
        item is completion for item in client.completions
    )


@pytest.mark.asyncio
async def test_on_server_scan_completion_recovery_accepts_released_parent():
    from types import SimpleNamespace

    from onesearch_agent.client import AgentAmbiguousResultError
    from onesearch_agent.worker import _complete_with_recovery
    from onesearch_shared import JobCompletion, JobKind, JobStatus, ProcessingMode

    class Client:
        def __init__(self):
            self.completions = 0

        async def complete(self, *_args):
            self.completions += 1
            raise AgentAmbiguousResultError("lost completion receipt")

        async def job_status(self, _job_id):
            return SimpleNamespace(status="running", handoff_released=True)

    lease = SimpleNamespace(
        id="j",
        lease_token="t",
        kind=JobKind.SCAN,
        processing_mode=ProcessingMode.ON_SERVER,
    )
    client = Client()
    await _complete_with_recovery(
        client, lease, JobCompletion(job_id="j", status=JobStatus.SUCCEEDED)
    )
    assert client.completions == 1


@pytest.mark.asyncio
async def test_on_server_scan_completion_retries_when_running_parent_has_not_handed_off():
    from types import SimpleNamespace

    from onesearch_agent.client import AgentAmbiguousResultError
    from onesearch_agent.worker import _complete_with_recovery
    from onesearch_shared import JobCompletion, JobKind, JobStatus, ProcessingMode

    class Client:
        def __init__(self):
            self.completions = 0

        async def complete(self, *_args):
            self.completions += 1
            if self.completions == 1:
                raise AgentAmbiguousResultError("request failed before server mutation")

        async def job_status(self, _job_id):
            return SimpleNamespace(status="running", handoff_released=False)

    lease = SimpleNamespace(
        id="j",
        lease_token="t",
        kind=JobKind.SCAN,
        processing_mode=ProcessingMode.ON_SERVER,
    )
    client = Client()
    await _complete_with_recovery(
        client, lease, JobCompletion(job_id="j", status=JobStatus.SUCCEEDED)
    )
    assert client.completions == 2



@pytest.mark.asyncio
async def test_v3_scan_pages_only_changed_files_and_submits_outcomes(monkeypatch, tmp_path):
    from onesearch_shared import (
        ScanManifestPageAck,
        ScanPageOutcomeAck,
    )

    (tmp_path / "changed.txt").write_text("changed")
    (tmp_path / "unchanged.txt").write_text("unchanged")

    class Client:
        def __init__(self):
            self.pages, self.batches, self.outcomes, self.completions = [], [], [], []

        async def job_heartbeat(self, *args):
            pass

        async def submit_manifest_page(self, _job, page, _token):
            self.pages.append(page)
            return ScanManifestPageAck(
                job_id="j",
                sequence=page.page.sequence,
                checksum=page.checksum,
                accepted_count=len(page.page.files),
                changed_paths=["changed.txt"],
                checkpoint=page.page.checkpoint,
            )

        async def submit_batch(self, _job, batch, _token):
            self.batches.append(batch)
            return __import__("onesearch_shared").BatchAck(
                batch_id=batch.batch_id, accepted_count=len(batch.documents)
            )

        async def submit_page_outcome(self, _job, outcome, _token):
            self.outcomes.append(outcome)
            return ScanPageOutcomeAck(
                job_id="j",
                sequence=outcome.outcome.sequence,
                checksum=outcome.checksum,
                settled_count=len(outcome.outcome.results),
                checkpoint=__import__("onesearch_shared").ScanCheckpoint(
                    cursor="page:0", scanned_count=2
                ),
            )

        async def complete(self, _job, completion, _token):
            self.completions.append(completion)

    lease = _v3_scan_lease(root_path=str(tmp_path))
    client = Client()
    await worker_module.run_scan_job(
        lease,
        client,
        roots=[AllowedRoot(root_id="r", path=str(tmp_path))],
        state_dir=tmp_path.parent / f"{tmp_path.name}-state",
    )
    assert [[file.path for file in page.page.files] for page in client.pages] == [
        ["changed.txt", "unchanged.txt"]
    ]
    assert [[doc.path for batch in client.batches for doc in batch.documents]] == [["changed.txt"]]
    assert [
        (result.path, result.status.value) for result in client.outcomes[0].outcome.results
    ] == [("changed.txt", "indexed")]
    assert [completion.status.value for completion in client.completions] == ["succeeded"]


@pytest.mark.asyncio
async def test_v3_restart_replays_persisted_page_after_interrupted_outcome(tmp_path):
    from onesearch_agent.client import AgentAmbiguousResultError
    from onesearch_shared import (
        ScanCheckpoint,
        ScanManifestPageAck,
        ScanPageOutcomeAck,
    )

    (tmp_path / "changed.txt").write_text("changed")
    state_dir = tmp_path.parent / f"{tmp_path.name}-state"
    lease = _v3_scan_lease(root_path=str(tmp_path))

    class Client:
        def __init__(self):
            self.pages, self.outcomes, self.batches, self.completions = [], [], [], []

        async def job_heartbeat(self, *args):
            pass

        async def submit_manifest_page(self, _job, page, _token):
            self.pages.append(page)
            return ScanManifestPageAck(
                job_id="j",
                sequence=page.page.sequence,
                checksum=page.checksum,
                accepted_count=1,
                changed_paths=["changed.txt"],
                duplicate=len(self.pages) > 1,
                checkpoint=page.page.checkpoint,
            )

        async def submit_batch(self, _job, batch, _token):
            self.batches.append(batch)
            return __import__("onesearch_shared").BatchAck(
                batch_id=batch.batch_id,
                accepted_count=len(batch.documents),
                duplicate=len(self.batches) > 1,
            )

        async def submit_page_outcome(self, _job, outcome, _token):
            self.outcomes.append(outcome)
            if len(self.outcomes) == 1:
                raise AgentAmbiguousResultError("lost outcome receipt")
            return ScanPageOutcomeAck(
                job_id="j",
                sequence=0,
                checksum=outcome.checksum,
                settled_count=1,
                duplicate=True,
                checkpoint=ScanCheckpoint(cursor="page:0", scanned_count=1),
            )

        async def complete(self, _job, completion, _token):
            self.completions.append(completion)

    client = Client()
    with pytest.raises(AgentAmbiguousResultError):
        await worker_module.run_scan_job(
            lease,
            client,
            roots=[AllowedRoot(root_id="r", path=str(tmp_path))],
            state_dir=state_dir,
            _mutation_attempts=1,
        )
    await worker_module.run_scan_job(
        lease, client, roots=[AllowedRoot(root_id="r", path=str(tmp_path))], state_dir=state_dir
    )
    assert len(client.pages) == len(client.outcomes) == 2
    assert client.pages[0].checksum == client.pages[1].checksum
    assert client.outcomes[0].checksum == client.outcomes[1].checksum
    assert [item.status.value for item in client.completions] == ["succeeded"]
    assert not ScanSpool.lifecycle_exists(state_dir, "j")


@pytest.mark.asyncio
async def test_v3_on_server_scan_submits_durable_pages_without_local_extraction(tmp_path):
    from onesearch_shared import ProcessingMode, ScanManifestPageAck

    lease = _v3_scan_lease(root_path=str(tmp_path))
    lease.processing_mode = ProcessingMode.ON_SERVER
    (tmp_path / "report.txt").write_text("report")

    class Client:
        def __init__(self):
            self.pages, self.completions = [], []

        async def job_heartbeat(self, *args):
            pass

        async def submit_manifest_page(self, _job, page, _token):
            self.pages.append(page)
            return ScanManifestPageAck(
                job_id=lease.id,
                sequence=page.page.sequence,
                checksum=page.checksum,
                accepted_count=len(page.page.files),
                changed_paths=[file.path for file in page.page.files],
                checkpoint=page.page.checkpoint,
            )

        async def complete(self, _job, completion, _token):
            self.completions.append(completion)

    client = Client()
    state_dir = tmp_path.parent / f"{tmp_path.name}-state"
    await worker_module.run_scan_job(
        lease, client, roots=[AllowedRoot(root_id="r", path=str(tmp_path))], state_dir=state_dir
    )
    assert [[file.path for file in page.page.files] for page in client.pages] == [["report.txt"]]
    assert [item.status.value for item in client.completions] == ["succeeded"]
    assert not ScanSpool.lifecycle_exists(state_dir, "j")


@pytest.mark.asyncio
async def test_v3_on_server_retry_replays_page_and_keeps_spool_until_completion(tmp_path):
    from onesearch_agent.client import AgentAmbiguousResultError
    from onesearch_shared import ProcessingMode, ScanManifestPageAck

    (tmp_path / "report.txt").write_text("report")
    state_dir = tmp_path.parent / f"{tmp_path.name}-state"
    lease = _v3_scan_lease(root_path=str(tmp_path))
    lease.processing_mode = ProcessingMode.ON_SERVER

    class Client:
        def __init__(self):
            self.pages, self.completions = [], []

        async def job_heartbeat(self, *args):
            pass

        async def submit_manifest_page(self, _job, page, _token):
            self.pages.append(page)
            if len(self.pages) == 1:
                raise AgentAmbiguousResultError("lost page receipt")
            return ScanManifestPageAck(
                job_id=lease.id,
                sequence=page.page.sequence,
                checksum=page.checksum,
                accepted_count=len(page.page.files),
                changed_paths=[file.path for file in page.page.files],
                duplicate=True,
                checkpoint=page.page.checkpoint,
            )

        async def complete(self, _job, completion, _token):
            self.completions.append(completion)

    client = Client()
    with pytest.raises(AgentAmbiguousResultError):
        await worker_module.run_scan_job(
            lease,
            client,
            roots=[AllowedRoot(root_id="r", path=str(tmp_path))],
            state_dir=state_dir,
            _mutation_attempts=1,
        )
    assert ScanSpool.lifecycle_exists(state_dir, lease.id)

    await worker_module.run_scan_job(
        lease,
        client,
        roots=[AllowedRoot(root_id="r", path=str(tmp_path))],
        state_dir=state_dir,
    )

    assert client.pages[0].checksum == client.pages[1].checksum
    assert [item.status.value for item in client.completions] == ["succeeded"]
    assert not ScanSpool.lifecycle_exists(state_dir, lease.id)


@pytest.mark.asyncio
async def test_extract_file_conflict_acks_once_without_failed_completion(tmp_path):
    from types import SimpleNamespace

    from onesearch_agent.client import JobConflict
    from onesearch_shared import ProcessingMode

    file_path = tmp_path / "a.txt"
    file_path.write_text("x")
    lease = SimpleNamespace(
        id="extract-1",
        kind=SimpleNamespace(value="extract_file"),
        processing_mode=ProcessingMode.ON_SERVER,
        source_id="s",
        lease_token="token",
        payload={
            "root_id": "r",
            "root_path": str(tmp_path),
            "path": "a.txt",
            "size_bytes": 1,
            "modified_at": file_path.stat().st_mtime_ns,
            "maximum_size": 1,
        },
    )

    class Client:
        def __init__(self):
            self.uploads = self.acks = self.completions = 0

        async def job_heartbeat(self, *args):
            pass

        async def upload_file_chunk(self, *args, **kwargs):
            self.uploads += 1
            raise JobConflict("cancel")

        async def cancel_ack(self, *args):
            self.acks += 1

        async def complete(self, *args):
            self.completions += 1

    client = Client()
    await worker_module.run_extract_file_job(
        lease, client, roots=[AllowedRoot(root_id="r", path=str(tmp_path))]
    )
    assert (client.uploads, client.acks, client.completions) == (1, 1, 0)


@pytest.mark.asyncio
async def test_stream_file_uploads_bounded_chunks_and_final_checksum(tmp_path):
    from types import SimpleNamespace

    from onesearch_shared import ProcessingMode

    file_path = tmp_path / "a.txt"
    file_path.write_bytes(b"abcde")
    lease = SimpleNamespace(
        id="stream-1",
        kind=SimpleNamespace(value="stream_file"),
        processing_mode=ProcessingMode.ON_SERVER,
        source_id="s",
        lease_token="token",
        payload={
            "root_id": "r",
            "root_path": str(tmp_path),
            "path": "a.txt",
            "size_bytes": 5,
            "modified_at": file_path.stat().st_mtime_ns,
            "maximum_size": 5,
        },
    )

    class Client:
        def __init__(self):
            self.calls = []

        async def job_heartbeat(self, *args):
            pass

        async def upload_file_chunk(self, *args, **kwargs):
            self.calls.append(kwargs)

    client = Client()
    await worker_module.run_stream_file_job(
        lease, client, roots=[AllowedRoot(root_id="r", path=str(tmp_path))], chunk_bytes=3
    )
    assert [call.get("data") for call in client.calls] == [b"abc", b"de", None]
    assert [call["sequence"] for call in client.calls] == [0, 1, 2]
    assert client.calls[-1]["complete"] is True


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "runner", [worker_module.run_extract_file_job, worker_module.run_stream_file_job]
)
async def test_nested_file_transfer_opens_source_subtree(runner, tmp_path):
    from types import SimpleNamespace

    from onesearch_shared import ProcessingMode

    source = tmp_path / "team"
    source.mkdir()
    file = source / "report.txt"
    file.write_bytes(b"inside")
    info = file.stat()
    kind = "extract_file" if runner is worker_module.run_extract_file_job else "stream_file"
    lease = SimpleNamespace(
        id=f"{kind}-nested",
        kind=SimpleNamespace(value=kind),
        processing_mode=ProcessingMode.ON_SERVER,
        source_id="s",
        lease_token="token",
        payload={
            "root_id": "r",
            "root_path": str(source),
            "path": "report.txt",
            "size_bytes": info.st_size,
            "modified_at": info.st_mtime_ns,
            "maximum_size": info.st_size,
        },
    )

    class Client:
        def __init__(self):
            self.uploads = []

        async def job_heartbeat(self, *args):
            pass

        async def upload_file_chunk(self, *args, **kwargs):
            self.uploads.append(kwargs)

        async def complete(self, *args):
            raise AssertionError("nested file should transfer")

    client = Client()
    await runner(lease, client, roots=[AllowedRoot(root_id="r", path=str(tmp_path))])

    assert b"".join(item.get("data", b"") for item in client.uploads) == b"inside"


@pytest.mark.asyncio
async def test_file_transfer_classifies_root_contract_mismatch_as_invalid_request(tmp_path):
    from types import SimpleNamespace

    from onesearch_shared import ProcessingMode

    outside = tmp_path.parent / "outside"
    lease = SimpleNamespace(
        id="stream-invalid-root",
        kind=SimpleNamespace(value="stream_file"),
        processing_mode=ProcessingMode.ON_SERVER,
        source_id="s",
        lease_token="token",
        payload={
            "root_id": "r",
            "root_path": str(outside),
            "path": "report.txt",
            "size_bytes": 1,
            "modified_at": 1,
            "maximum_size": 1,
        },
    )

    class Client:
        def __init__(self):
            self.completions = []

        async def complete(self, _job_id, completion, _token):
            self.completions.append(completion)

    client = Client()
    await worker_module.run_stream_file_job(
        lease, client, roots=[AllowedRoot(root_id="r", path=str(tmp_path))]
    )

    assert client.completions[0].reason.value == "invalid_request"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("terminal_status", "expected_failed"),
    [(None, True), ("completed", False), ("claimed", True)],
)
async def test_ambiguous_file_upload_is_never_retried(tmp_path, terminal_status, expected_failed):
    from types import SimpleNamespace

    from onesearch_agent.client import AgentAmbiguousResultError
    from onesearch_shared import ProcessingMode

    path = tmp_path / "a.txt"
    path.write_bytes(b"x")
    lease = SimpleNamespace(
        id="transfer-ambiguous",
        kind=SimpleNamespace(value="stream_file"),
        processing_mode=ProcessingMode.ON_SERVER,
        source_id="s",
        lease_token="token",
        payload={
            "root_id": "r",
            "root_path": str(tmp_path),
            "path": "a.txt",
            "size_bytes": 1,
            "modified_at": path.stat().st_mtime_ns,
            "maximum_size": 1,
        },
    )

    class Client:
        def __init__(self):
            self.uploads, self.completions = [], []

        async def job_heartbeat(self, *args):
            pass

        async def upload_file_chunk(self, *args, **kwargs):
            self.uploads.append(kwargs)
            if terminal_status is None and not kwargs.get("complete"):
                raise AgentAmbiguousResultError("lost response")
            if terminal_status is not None and kwargs.get("complete"):
                raise AgentAmbiguousResultError("lost response")

        async def job_status(self, _job_id):
            return SimpleNamespace(status=terminal_status)

        async def complete(self, _job_id, completion, _token):
            self.completions.append(completion)

    client = Client()
    await worker_module.run_stream_file_job(
        lease, client, roots=[AllowedRoot(root_id="r", path=str(tmp_path))]
    )
    assert len(client.uploads) == (1 if terminal_status is None else 2)
    assert [item["sequence"] for item in client.uploads] == list(range(len(client.uploads)))
    assert [item.status.value for item in client.completions] == (
        ["failed"] if expected_failed else []
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("path", "size", "modified", "reason", "detail"),
    [
        ("missing.txt", 1, 1, "not_found", "remote_file_missing"),
        ("a.txt", 2, 1, "invalid_request", "remote_file_changed"),
    ],
)
async def test_stream_file_maps_missing_and_changed_without_path_leak(
    tmp_path, path, size, modified, reason, detail
):
    from types import SimpleNamespace

    from onesearch_shared import ProcessingMode

    (tmp_path / "a.txt").write_text("x")
    lease = SimpleNamespace(
        id="stream-fail",
        kind=SimpleNamespace(value="stream_file"),
        processing_mode=ProcessingMode.ON_SERVER,
        source_id="s",
        lease_token="token",
        payload={
            "root_id": "r",
            "root_path": str(tmp_path),
            "path": path,
            "size_bytes": size,
            "modified_at": modified,
            "maximum_size": 2,
        },
    )

    class Client:
        def __init__(self):
            self.completions = []

        async def job_heartbeat(self, *args):
            pass

        async def complete(self, *args):
            self.completions.append(args[1])

    client = Client()
    await worker_module.run_stream_file_job(
        lease, client, roots=[AllowedRoot(root_id="r", path=str(tmp_path))]
    )
    completion = client.completions[0]
    assert completion.reason.value == reason and completion.detail == detail
    assert str(tmp_path) not in completion.detail


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("root_id", "path", "expected_reason", "expected_detail"),
    [
        ("r", "missing.txt", "not_found", "remote_file_missing"),
        ("r", "../outside.txt", "invalid_request", "invalid extraction payload"),
        (
            "unknown-root",
            "a.txt",
            "invalid_request",
            "invalid extraction payload",
        ),
    ],
)
async def test_stream_file_only_classifies_confined_missing_as_not_found(
    tmp_path, root_id, path, expected_reason, expected_detail
):
    from types import SimpleNamespace

    from onesearch_shared import ProcessingMode

    lease = SimpleNamespace(
        id=f"stream-classify-{root_id}",
        kind=SimpleNamespace(value="stream_file"),
        processing_mode=ProcessingMode.ON_SERVER,
        source_id="s",
        lease_token="token",
        payload={
            "root_id": root_id,
            "root_path": str(tmp_path),
            "path": path,
            "size_bytes": 1,
            "modified_at": 1,
            "maximum_size": 1,
        },
    )

    class Client:
        def __init__(self):
            self.completions = []

        async def job_heartbeat(self, *args):
            pass

        async def complete(self, *args):
            self.completions.append(args[1])

    client = Client()
    await worker_module.run_stream_file_job(
        lease, client, roots=[AllowedRoot(root_id="r", path=str(tmp_path))]
    )
    completion = client.completions[0]
    assert completion.reason.value == expected_reason
    assert completion.detail == expected_detail
    assert "outside.txt" not in completion.detail and str(tmp_path) not in completion.detail
