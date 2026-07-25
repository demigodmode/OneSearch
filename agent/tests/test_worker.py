import asyncio
from pathlib import Path

import onesearch_agent.worker as worker_module
import pytest
from onesearch_agent.worker import ExtractionError, batch_documents, extract_confined
from onesearch_shared import AllowedRoot, DocumentBatch, NormalizedRemoteDocument, ScanFile


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
    expected = ScanFile(path="note.txt", size_bytes=stat.st_size, modified_at=stat.st_mtime_ns)
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
    expected = ScanFile(path="note.unknown", size_bytes=stat.st_size, modified_at=stat.st_mtime_ns)
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
    changed = ScanFile(path="note.unknown", size_bytes=999, modified_at=stat.st_mtime_ns)
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
    expected = ScanFile(path=file.name, size_bytes=1, modified_at=info.st_mtime_ns)
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
    expected = ScanFile(path=file.name, size_bytes=1, modified_at=info.st_mtime_ns)
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
            expected=ScanFile(path="x.txt", size_bytes=5, modified_at=1),
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
    expected = ScanFile(path="note.txt", size_bytes=info.st_size, modified_at=info.st_mtime_ns)
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
            "root_id": "r",
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
                path="large.txt", size_bytes=info.st_size, modified_at=info.st_mtime_ns
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
        expected=ScanFile(path="x.txt", size_bytes=1, modified_at=info.st_mtime_ns),
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
        payload={"root_id": "r", "known_files": {}, "extraction": extraction(), "limits": limits},
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
