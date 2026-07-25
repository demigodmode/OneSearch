import asyncio
from pathlib import Path

import onesearch_agent.worker as worker_module
import pytest
from onesearch_agent.worker import ExtractionError, batch_documents, extract_confined
from onesearch_shared import (
    AllowedRoot,
    DocumentBatch,
    NormalizedRemoteDocument,
    ScanFile,
    remote_path_hash,
)


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
async def test_fake_extractor_receives_private_original_basename(tmp_path, monkeypatch):
    file = tmp_path / "name.with.dot.txt"
    file.write_text("x")
    info = file.stat()
    expected = ScanFile(
        path=file.name,
        path_hash=remote_path_hash(file.name),
        size_bytes=1,
        modified_at=info.st_mtime_ns,
    )
    seen = []

    class Fake:
        async def extract_with_timeout(self, value):
            seen.append(Path(value))
            from app.schemas import Document

            return Document(
                id="x",
                source_id="s",
                source_name="source",
                path=value,
                basename=Path(value).name,
                extension="txt",
                type="text",
                size_bytes=1,
                modified_at=1,
                indexed_at=1,
                content="x",
            )

    monkeypatch.setattr(worker_module, "choose_extractor", lambda *args: Fake())
    await extract_confined(
        "r",
        file.name,
        [AllowedRoot(root_id="r", path=str(tmp_path))],
        expected=expected,
        source_id="s",
        extraction=extraction(),
        max_snapshot_bytes=10,
    )
    assert seen[0].name == file.name and not seen[0].parent.exists()


@pytest.mark.asyncio
@pytest.mark.parametrize("error", [RuntimeError("boom"), asyncio.CancelledError()])
async def test_snapshot_is_cleaned_for_extractor_error_and_cancellation(
    tmp_path, monkeypatch, error
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
    seen = []

    class Fake:
        async def extract_with_timeout(self, value):
            seen.append(Path(value))
            raise error

    monkeypatch.setattr(worker_module, "choose_extractor", lambda *args: Fake())
    with pytest.raises(type(error)):
        await extract_confined(
            "r",
            file.name,
            [AllowedRoot(root_id="r", path=str(tmp_path))],
            expected=expected,
            source_id="s",
            extraction=extraction(),
            max_snapshot_bytes=10,
        )
    assert not seen[0].parent.exists()


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
    monkeypatch.setattr(worker_module, "open_confined_file", opened)
    monkeypatch.setattr(worker_module.os, "fstat", lambda fd: states.pop(0))
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
async def test_run_scan_job_unchanged_submits_manifest_before_success(tmp_path):
    from types import SimpleNamespace

    from onesearch_agent.worker import run_scan_job
    from onesearch_shared import JobKind, ProcessingMode

    file = tmp_path / "a.txt"
    file.write_text("x")
    info = file.stat()
    limits = {
        "max_snapshot_bytes": 1024,
        "max_batch_documents": 10,
        "max_batch_bytes": 1024,
        "max_scan_files": 10,
        "max_entries_per_directory": 10,
    }
    lease = SimpleNamespace(
        id="j",
        kind=JobKind.SCAN,
        processing_mode=ProcessingMode.ON_AGENT,
        source_id="s",
        lease_token="t",
        payload={
            "full": False,
            "root_id": "r",
            "root_path": "/remote/root",
            "include_patterns": None,
            "exclude_patterns": None,
            "known_files": {"a.txt": {"size_bytes": 1, "modified_at": info.st_mtime_ns}},
            "extraction": extraction(),
            "limits": limits,
        },
    )

    class Client:
        def __init__(self):
            self.calls = []

        async def job_heartbeat(self, *args):
            self.calls.append("heartbeat")

        async def submit_batch(self, *args):
            self.calls.append("batch")

        async def submit_manifest(self, *args):
            self.calls.append("manifest")

        async def complete(self, *args):
            self.calls.append(("complete", args[1].status))

    client = Client()
    await run_scan_job(lease, client, roots=[AllowedRoot(root_id="r", path=str(tmp_path))])
    assert "batch" not in client.calls and client.calls.index("manifest") < next(
        i for i, value in enumerate(client.calls) if value[0] == "complete"
    )


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

    class Fake:
        async def extract_with_timeout(self, value):
            seen.append(Path(value).parent.stat().st_mode & 0o777)
            from app.schemas import Document

            return Document(
                id="x",
                source_id="s",
                source_name="source",
                path=value,
                basename="x.txt",
                extension="txt",
                type="text",
                size_bytes=1,
                modified_at=1,
                indexed_at=1,
                content="x",
            )

    monkeypatch.setattr(worker_module, "choose_extractor", lambda *args: Fake())
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
async def test_run_changed_orders_batch_manifest_success(tmp_path):
    from types import SimpleNamespace

    from onesearch_agent.worker import run_scan_job
    from onesearch_shared import JobKind, ProcessingMode

    (tmp_path / "a.txt").write_text("x")
    limits = {
        "max_snapshot_bytes": 1024,
        "max_batch_documents": 10,
        "max_batch_bytes": 1024,
        "max_scan_files": 10,
        "max_entries_per_directory": 10,
    }
    lease = SimpleNamespace(
        id="j",
        kind=JobKind.SCAN,
        processing_mode=ProcessingMode.ON_AGENT,
        source_id="s",
        lease_token="t",
        payload={
            "full": True,
            "root_id": "r",
            "root_path": "/remote/root",
            "include_patterns": None,
            "exclude_patterns": None,
            "known_files": {},
            "extraction": extraction(),
            "limits": limits,
        },
    )

    class C:
        def __init__(self):
            self.calls = []

        async def job_heartbeat(self, *a):
            self.calls.append("heartbeat")

        async def submit_batch(self, *a):
            self.calls.append("batch")

        async def submit_manifest(self, *a):
            self.calls.append("manifest")

        async def complete(self, *a):
            self.calls.append("complete")

    c = C()
    await run_scan_job(lease, c, roots=[AllowedRoot(root_id="r", path=str(tmp_path))])
    assert c.calls.index("batch") < c.calls.index("manifest") < c.calls.index("complete")


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
    assert len(c.calls) == 1 and c.calls[0].reason is JobFailureReason.INVALID_REQUEST


def _scan_lease(*, limits=None):
    from types import SimpleNamespace

    from onesearch_shared import JobKind, ProcessingMode

    return SimpleNamespace(
        id="j",
        kind=JobKind.SCAN,
        processing_mode=ProcessingMode.ON_AGENT,
        source_id="s",
        lease_token="t",
        payload={
            "full": True,
            "root_id": "r",
            "root_path": "/remote/root",
            "include_patterns": None,
            "exclude_patterns": None,
            "known_files": {},
            "extraction": extraction(),
            "limits": {
                "max_snapshot_bytes": 1024,
                "max_batch_documents": 10,
                "max_batch_bytes": 10_000,
                "max_scan_files": 10,
                "max_entries_per_directory": 10,
                **(limits or {}),
            },
        },
    )


@pytest.mark.asyncio
async def test_incomplete_manifest_is_submitted_then_failed_with_checkpoint(monkeypatch, tmp_path):
    from onesearch_shared import JobFailureReason, ScanCheckpoint, ScanManifest

    class Scanner:
        changed_paths = []

        def __init__(self, *args, **kwargs):
            pass

        def scan(self, **kwargs):
            return ScanManifest(
                **kwargs,
                complete=False,
                checkpoint=ScanCheckpoint(cursor="page-2", scanned_count=4),
            )

    class Client:
        def __init__(self):
            self.calls = []

        async def job_heartbeat(self, *args):
            self.calls.append(("progress", args[1]))

        async def submit_manifest(self, *args):
            self.calls.append(("manifest", args[1]))

        async def complete(self, *args):
            self.calls.append(("complete", args[1]))

    monkeypatch.setattr(worker_module, "RemoteScanner", Scanner)
    client = Client()
    await worker_module.run_scan_job(
        _scan_lease(), client, roots=[AllowedRoot(root_id="r", path=str(tmp_path))]
    )
    assert [kind for kind, _ in client.calls] == ["progress", "manifest", "complete"]
    completion = client.calls[-1][1]
    assert completion.status.value == "failed"
    assert completion.reason is JobFailureReason.INTERNAL_ERROR
    assert completion.checkpoint.cursor == "page-2"


@pytest.mark.asyncio
async def test_extraction_failure_is_manifested_but_scan_succeeds(monkeypatch, tmp_path):
    from onesearch_shared import ScanFile, ScanManifest

    class Scanner:
        changed_paths = ["a.txt"]

        def __init__(self, *args, **kwargs):
            pass

        def scan(self, **kwargs):
            return ScanManifest(
                **kwargs,
                files=[
                    ScanFile(
                        path="a.txt",
                        path_hash=remote_path_hash("a.txt"),
                        size_bytes=1,
                        modified_at=1,
                    )
                ],
                complete=True,
            )

    class Client:
        def __init__(self):
            self.manifest = self.completion = None

        async def job_heartbeat(self, *args):
            pass

        async def submit_batch(self, *args):
            raise AssertionError("failed extraction must not submit a batch")

        async def submit_manifest(self, *args):
            self.manifest = args[1]

        async def complete(self, *args):
            self.completion = args[1]

    async def fail(*args, **kwargs):
        raise ExtractionError("stable extraction failure")

    monkeypatch.setattr(worker_module, "RemoteScanner", Scanner)
    monkeypatch.setattr(worker_module, "extract_confined", fail)
    client = Client()
    await worker_module.run_scan_job(
        _scan_lease(), client, roots=[AllowedRoot(root_id="r", path=str(tmp_path))]
    )
    assert client.manifest.failures[0].path == "a.txt"
    assert client.manifest.failures[0].error == "stable extraction failure"
    assert client.completion.status.value == "succeeded"


@pytest.mark.asyncio
async def test_unknown_extraction_error_does_not_leak_path_or_controls(monkeypatch, tmp_path):
    from onesearch_shared import ScanFile, ScanManifest

    class Scanner:
        changed_paths = ["a.txt"]

        def __init__(self, *args, **kwargs):
            pass

        def scan(self, **kwargs):
            return ScanManifest(
                **kwargs,
                files=[
                    ScanFile(
                        path="a.txt",
                        path_hash=remote_path_hash("a.txt"),
                        size_bytes=1,
                        modified_at=1,
                    )
                ],
                complete=True,
            )

    class Client:
        async def job_heartbeat(self, *args):
            pass

        async def submit_manifest(self, *args):
            self.manifest = args[1]

        async def complete(self, *args):
            pass

    async def fail(*args, **kwargs):
        raise RuntimeError(f"{tmp_path}\\x00secret\\n")

    monkeypatch.setattr(worker_module, "RemoteScanner", Scanner)
    monkeypatch.setattr(worker_module, "extract_confined", fail)
    client = Client()
    await worker_module.run_scan_job(
        _scan_lease(), client, roots=[AllowedRoot(root_id="r", path=str(tmp_path))]
    )
    error = client.manifest.failures[0].error
    assert error == "extraction failed: RuntimeError"
    assert str(tmp_path) not in error and all(ord(char) >= 32 and char != "\x7f" for char in error)


@pytest.mark.asyncio
async def test_oversized_document_keeps_buffered_batch_and_reports_failure(monkeypatch, tmp_path):
    from onesearch_agent.worker import _batch_wire_bytes
    from onesearch_shared import ScanFile, ScanManifest

    first = NormalizedRemoteDocument(source_id="s", path="a.txt", content="x", modified_at=1)
    second = NormalizedRemoteDocument(
        source_id="s", path="b.txt", content="x" * 5_000, modified_at=1
    )
    cap = len(
        _batch_wire_bytes(DocumentBatch(job_id="j", batch_id="j:0:" + "0" * 64, documents=[first]))
    )

    class Scanner:
        changed_paths = ["a.txt", "b.txt"]

        def __init__(self, *args, **kwargs):
            pass

        def scan(self, **kwargs):
            return ScanManifest(
                **kwargs,
                files=[
                    ScanFile(
                        path="a.txt",
                        path_hash=remote_path_hash("a.txt"),
                        size_bytes=1,
                        modified_at=1,
                    ),
                    ScanFile(
                        path="b.txt",
                        path_hash=remote_path_hash("b.txt"),
                        size_bytes=1,
                        modified_at=1,
                    ),
                ],
                complete=True,
            )

    class Client:
        def __init__(self):
            self.batches, self.progress, self.manifest = [], [], None

        async def job_heartbeat(self, *args):
            self.progress.append(args[1].completed_items)

        async def submit_batch(self, *args):
            self.batches.append(args[1])

        async def submit_manifest(self, *args):
            self.manifest = args[1]

        async def complete(self, *args):
            pass

    async def documents(*args, **kwargs):
        return {"a.txt": first, "b.txt": second}[args[1]]

    monkeypatch.setattr(worker_module, "RemoteScanner", Scanner)
    monkeypatch.setattr(worker_module, "extract_confined", documents)
    client = Client()
    await worker_module.run_scan_job(
        _scan_lease(limits={"max_batch_bytes": cap}),
        client,
        roots=[AllowedRoot(root_id="r", path=str(tmp_path))],
    )
    assert [[document.path for document in batch.documents] for batch in client.batches] == [
        ["a.txt"]
    ]
    assert [(failure.path, failure.error) for failure in client.manifest.failures] == [
        ("b.txt", "extraction failed: OversizedDocumentError")
    ]
    assert client.progress == [0, 1, 2]


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
        lambda payload: payload["limits"].update(max_scan_files=100_001),
        lambda payload: payload["extraction"].update(unsupported_file_policy="execute"),
        lambda payload: payload["extraction"].update(media_metadata_mode="always"),
        lambda payload: payload.update(known_files=[]),
        lambda payload: payload.update(known_files={"a.txt": []}),
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
    lease = _scan_lease()
    mutate(lease.payload)
    client = Client()
    await worker_module.run_scan_job(
        lease, client, roots=[AllowedRoot(root_id="r", path=str(tmp_path))]
    )
    assert len(client.completions) == 1
    assert client.completions[0].reason.value == "invalid_request"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "kind,mode", [(None, "on_agent"), ("delete", "on_agent"), ("scan", None), ("scan", "on_server")]
)
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

    lease = _scan_lease()
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
async def test_run_scan_job_accepts_exact_server_hard_cap_defaults(monkeypatch, tmp_path):
    from onesearch_shared import (
        REMOTE_MAX_BATCH_BYTES,
        REMOTE_MAX_BATCH_DOCUMENTS,
        REMOTE_MAX_ENTRIES_PER_DIRECTORY,
        REMOTE_MAX_SCAN_FILES,
        REMOTE_MAX_SNAPSHOT_BYTES,
        ScanManifest,
    )

    captured = {}

    class Scanner:
        changed_paths = []

        def __init__(self, *args, **kwargs):
            captured.update(kwargs)

        def scan(self, **kwargs):
            return ScanManifest(**kwargs, complete=True)

    class Client:
        async def job_heartbeat(self, *args):
            pass

        async def submit_manifest(self, *args):
            pass

        async def complete(self, *args):
            self.completion = args[1]

    monkeypatch.setattr(worker_module, "RemoteScanner", Scanner)
    client = Client()
    await worker_module.run_scan_job(
        _scan_lease(
            limits={
                "max_snapshot_bytes": REMOTE_MAX_SNAPSHOT_BYTES,
                "max_batch_documents": REMOTE_MAX_BATCH_DOCUMENTS,
                "max_batch_bytes": REMOTE_MAX_BATCH_BYTES,
                "max_scan_files": REMOTE_MAX_SCAN_FILES,
                "max_entries_per_directory": REMOTE_MAX_ENTRIES_PER_DIRECTORY,
            }
        ),
        client,
        roots=[AllowedRoot(root_id="r", path=str(tmp_path))],
    )
    assert captured["max_files"] == REMOTE_MAX_SCAN_FILES
    assert captured["max_entries_per_directory"] == REMOTE_MAX_ENTRIES_PER_DIRECTORY
    assert client.completion.status.value == "succeeded"


@pytest.mark.asyncio
async def test_streaming_submits_early_batches_before_final_extraction(monkeypatch, tmp_path):
    from onesearch_shared import ScanFile, ScanManifest

    class Scanner:
        changed_paths = ["a.txt", "b.txt", "c.txt"]

        def __init__(self, *args, **kwargs):
            pass

        def scan(self, **kwargs):
            return ScanManifest(
                **kwargs,
                complete=True,
                files=[
                    ScanFile(
                        path=path, path_hash=remote_path_hash(path), size_bytes=1, modified_at=1
                    )
                    for path in self.changed_paths
                ],
            )

    class Client:
        def __init__(self):
            self.calls = []

        async def job_heartbeat(self, *args):
            self.calls.append("progress")

        async def submit_batch(self, *args):
            self.calls.append(f"batch:{args[1].documents[0].path}")

        async def submit_manifest(self, *args):
            self.calls.append("manifest")

        async def complete(self, *args):
            self.calls.append(f"complete:{args[1].status.value}")

    async def extract(*args, **kwargs):
        path = args[1]
        client.calls.append(f"extract:{path}")
        return NormalizedRemoteDocument(source_id="s", path=path, content="x", modified_at=1)

    monkeypatch.setattr(worker_module, "RemoteScanner", Scanner)
    monkeypatch.setattr(worker_module, "extract_confined", extract)
    client = Client()
    await worker_module.run_scan_job(
        _scan_lease(limits={"max_batch_documents": 1}),
        client,
        roots=[AllowedRoot(root_id="r", path=str(tmp_path))],
    )
    assert client.calls.index("batch:a.txt") < client.calls.index("extract:c.txt")
    assert (
        client.calls.index("batch:c.txt")
        < client.calls.index("manifest")
        < client.calls.index("complete:succeeded")
    )


def _changed_scanner(paths, *, complete=True):
    from onesearch_shared import ScanFile, ScanManifest

    class Scanner:
        changed_paths = paths

        def __init__(self, *args, **kwargs):
            pass

        def scan(self, **kwargs):
            return ScanManifest(
                **kwargs,
                complete=complete,
                files=[
                    ScanFile(
                        path=path, path_hash=remote_path_hash(path), size_bytes=1, modified_at=1
                    )
                    for path in self.changed_paths
                ],
            )

    return Scanner


@pytest.mark.asyncio
async def test_batch_ambiguity_retries_identical_body_without_reordering(monkeypatch, tmp_path):
    from onesearch_agent.client import AgentAmbiguousResultError

    class Client:
        def __init__(self):
            self.calls, self.batches = [], []

        async def job_heartbeat(self, *args):
            pass

        async def submit_batch(self, *args):
            batch = args[1]
            self.calls.append(f"batch:{batch.documents[0].path}")
            self.batches.append(batch)
            if len(self.batches) == 1:
                raise AgentAmbiguousResultError("unknown")

        async def submit_manifest(self, *args):
            self.calls.append("manifest")

        async def complete(self, *args):
            self.calls.append("complete")

    async def extract(*args, **kwargs):
        path = args[1]
        return NormalizedRemoteDocument(source_id="s", path=path, content="x", modified_at=1)

    monkeypatch.setattr(worker_module, "RemoteScanner", _changed_scanner(["a.txt", "b.txt"]))
    monkeypatch.setattr(worker_module, "extract_confined", extract)
    client = Client()
    await worker_module.run_scan_job(
        _scan_lease(limits={"max_batch_documents": 1}),
        client,
        roots=[AllowedRoot(root_id="r", path=str(tmp_path))],
        _sleep=lambda _: asyncio.sleep(0),
    )
    assert client.calls == ["batch:a.txt", "batch:a.txt", "batch:b.txt", "manifest", "complete"]
    assert client.batches[0] is client.batches[1]
    assert client.batches[0].batch_id == client.batches[1].batch_id


@pytest.mark.asyncio
async def test_batch_ambiguity_exhaustion_aborts_before_manifest_or_success(monkeypatch, tmp_path):
    from onesearch_agent.client import AgentAmbiguousResultError

    class Client:
        def __init__(self):
            self.batch_calls = self.manifests = self.completions = 0

        async def job_heartbeat(self, *args):
            pass

        async def submit_batch(self, *args):
            self.batch_calls += 1
            raise AgentAmbiguousResultError("unknown")

        async def submit_manifest(self, *args):
            self.manifests += 1

        async def complete(self, *args):
            self.completions += 1

    async def extract(*args, **kwargs):
        return NormalizedRemoteDocument(source_id="s", path="a.txt", content="x", modified_at=1)

    monkeypatch.setattr(worker_module, "RemoteScanner", _changed_scanner(["a.txt"]))
    monkeypatch.setattr(worker_module, "extract_confined", extract)
    client = Client()
    with pytest.raises(AgentAmbiguousResultError):
        await worker_module.run_scan_job(
            _scan_lease(),
            client,
            roots=[AllowedRoot(root_id="r", path=str(tmp_path))],
            _sleep=lambda _: asyncio.sleep(0),
        )
    assert (client.batch_calls, client.manifests, client.completions) == (3, 0, 0)


@pytest.mark.asyncio
async def test_manifest_ambiguity_retries_identical_manifest_before_success(monkeypatch, tmp_path):
    from onesearch_agent.client import AgentAmbiguousResultError

    class Client:
        def __init__(self):
            self.manifests, self.completions = [], 0

        async def job_heartbeat(self, *args):
            pass

        async def submit_manifest(self, *args):
            self.manifests.append(args[1])
            if len(self.manifests) == 1:
                raise AgentAmbiguousResultError("unknown")

        async def complete(self, *args):
            self.completions += 1

    monkeypatch.setattr(worker_module, "RemoteScanner", _changed_scanner([]))
    client = Client()
    await worker_module.run_scan_job(
        _scan_lease(),
        client,
        roots=[AllowedRoot(root_id="r", path=str(tmp_path))],
        _sleep=lambda _: asyncio.sleep(0),
    )
    assert client.manifests[0] is client.manifests[1]
    assert client.completions == 1


@pytest.mark.asyncio
async def test_manifest_ambiguity_exhaustion_never_completes_success(monkeypatch, tmp_path):
    from onesearch_agent.client import AgentAmbiguousResultError

    class Client:
        def __init__(self):
            self.manifests = self.completions = 0

        async def job_heartbeat(self, *args):
            pass

        async def submit_manifest(self, *args):
            self.manifests += 1
            raise AgentAmbiguousResultError("unknown")

        async def complete(self, *args):
            self.completions += 1

    monkeypatch.setattr(worker_module, "RemoteScanner", _changed_scanner([]))
    client = Client()
    with pytest.raises(AgentAmbiguousResultError):
        await worker_module.run_scan_job(
            _scan_lease(),
            client,
            roots=[AllowedRoot(root_id="r", path=str(tmp_path))],
            _sleep=lambda _: asyncio.sleep(0),
        )
    assert (client.manifests, client.completions) == (3, 0)


@pytest.mark.asyncio
async def test_job_conflict_is_not_retried(monkeypatch, tmp_path):
    from onesearch_agent.client import JobConflict

    class Client:
        def __init__(self):
            self.batches = self.manifests = 0

        async def job_heartbeat(self, *args):
            pass

        async def submit_batch(self, *args):
            self.batches += 1
            raise JobConflict("conflict")

        async def submit_manifest(self, *args):
            self.manifests += 1

        async def cancel_ack(self, *args):
            self.cancelled = getattr(self, "cancelled", 0) + 1

    async def extract(*args, **kwargs):
        return NormalizedRemoteDocument(source_id="s", path="a.txt", content="x", modified_at=1)

    monkeypatch.setattr(worker_module, "RemoteScanner", _changed_scanner(["a.txt"]))
    monkeypatch.setattr(worker_module, "extract_confined", extract)
    client = Client()
    await worker_module.run_scan_job(
        _scan_lease(), client, roots=[AllowedRoot(root_id="r", path=str(tmp_path))]
    )
    assert (client.batches, client.manifests, client.cancelled) == (1, 0, 1)


@pytest.mark.asyncio
@pytest.mark.parametrize(("complete", "expected"), [(True, "succeeded"), (False, "failed")])
async def test_terminal_completion_ambiguity_is_not_retried_or_reversed(
    monkeypatch, tmp_path, complete, expected
):
    from onesearch_agent.client import AgentAmbiguousResultError

    class Client:
        def __init__(self):
            self.manifests, self.completions = 0, []

        async def job_heartbeat(self, *args):
            pass

        async def submit_manifest(self, *args):
            self.manifests += 1

        async def complete(self, *args):
            self.completions.append(args[1])
            raise AgentAmbiguousResultError("unknown")

    monkeypatch.setattr(worker_module, "RemoteScanner", _changed_scanner([], complete=complete))
    client = Client()
    with pytest.raises(AgentAmbiguousResultError):
        await worker_module.run_scan_job(
            _scan_lease(), client, roots=[AllowedRoot(root_id="r", path=str(tmp_path))]
        )
    assert client.manifests == 1
    assert [completion.status.value for completion in client.completions] == [expected]


@pytest.mark.asyncio
async def test_lease_keeper_heartbeats_while_threaded_scan_is_blocked(monkeypatch, tmp_path):
    import threading

    from onesearch_shared import ScanManifest

    started, release = threading.Event(), threading.Event()

    class Scanner:
        changed_paths = []

        def __init__(self, *args, **kwargs):
            pass

        def scan(self, **kwargs):
            started.set()
            assert release.wait(2)
            return ScanManifest(**kwargs, complete=True)

    class Client:
        def __init__(self):
            self.progress = []

        async def job_heartbeat(self, *args):
            self.progress.append(args[1])
            if len(self.progress) == 2:
                release.set()

        async def submit_manifest(self, *args):
            pass

        async def complete(self, *args):
            pass

    async def fast_periodic(_):
        await asyncio.sleep(0)

    monkeypatch.setattr(worker_module, "RemoteScanner", Scanner)
    client = Client()
    await worker_module.run_scan_job(
        _scan_lease(),
        client,
        roots=[AllowedRoot(root_id="r", path=str(tmp_path))],
        _lease_interval=1,
        _lease_sleep=fast_periodic,
    )
    assert started.is_set() and len(client.progress) >= 2


@pytest.mark.asyncio
async def test_lease_loss_during_threaded_scan_surfaces_before_submission(monkeypatch, tmp_path):
    import threading

    from onesearch_agent.client import JobLeaseError
    from onesearch_shared import ScanManifest

    release = threading.Event()

    class Scanner:
        changed_paths = []

        def __init__(self, *args, **kwargs):
            pass

        def scan(self, **kwargs):
            assert release.wait(2)
            return ScanManifest(**kwargs, complete=True)

    class Client:
        def __init__(self):
            self.heartbeats = self.manifests = self.completions = 0

        async def job_heartbeat(self, *args):
            self.heartbeats += 1
            if self.heartbeats == 2:
                release.set()
                raise JobLeaseError("lost")

        async def submit_manifest(self, *args):
            self.manifests += 1

        async def complete(self, *args):
            self.completions += 1

    async def fast_periodic(_):
        await asyncio.sleep(0)

    monkeypatch.setattr(worker_module, "RemoteScanner", Scanner)
    client = Client()
    with pytest.raises(JobLeaseError):
        await worker_module.run_scan_job(
            _scan_lease(),
            client,
            roots=[AllowedRoot(root_id="r", path=str(tmp_path))],
            _lease_interval=1,
            _lease_sleep=fast_periodic,
        )
    assert (client.manifests, client.completions) == (0, 0)


@pytest.mark.asyncio
async def test_worker_cancellation_closes_lease_keeper(monkeypatch, tmp_path):
    import threading

    from onesearch_shared import ScanManifest

    started, release = threading.Event(), threading.Event()

    class Scanner:
        changed_paths = []

        def __init__(self, *args, **kwargs):
            pass

        def scan(self, **kwargs):
            started.set()
            release.wait(2)
            return ScanManifest(**kwargs, complete=True)

    class Client:
        async def job_heartbeat(self, *args):
            pass

    monkeypatch.setattr(worker_module, "RemoteScanner", Scanner)
    before = set(asyncio.all_tasks())
    task = asyncio.create_task(
        worker_module.run_scan_job(
            _scan_lease(),
            Client(),
            roots=[AllowedRoot(root_id="r", path=str(tmp_path))],
            _lease_interval=60,
        )
    )
    assert await asyncio.to_thread(started.wait, 1)
    task.cancel()
    release.set()
    with pytest.raises(asyncio.CancelledError):
        await task
    await asyncio.sleep(0)
    assert not [
        pending
        for pending in asyncio.all_tasks() - before
        if "LeaseKeeper._run" in repr(pending.get_coro()) and not pending.done()
    ]
