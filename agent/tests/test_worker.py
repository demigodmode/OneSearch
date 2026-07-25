import hashlib
from pathlib import Path

import pytest
from onesearch_agent.worker import ExtractionError, batch_documents, extract_confined
from onesearch_shared import AllowedRoot, NormalizedRemoteDocument, ScanFile


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
    batches = list(batch_documents("job", docs, max_documents=2, max_bytes=300))

    assert [len(batch.documents) for batch in batches] == [2, 1]
    payload = batches[0].model_copy(update={"batch_id": "pending"}).model_dump_json()
    assert batches[0].batch_id == f"job:0:{hashlib.sha256(payload.encode()).hexdigest()}"
