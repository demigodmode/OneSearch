"""On-agent scan job worker with bounded, replay-safe document batches."""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from collections.abc import Iterator
from pathlib import Path

from onesearch_shared import (
    DocumentBatch,
    JobCompletion,
    JobStatus,
    NormalizedRemoteDocument,
    ScanFile,
)

from app.services.extractor_config import choose_extractor

from .paths import open_confined_file
from .scanner import RemoteScanner


def batch_documents(
    job_id: str,
    documents: list[NormalizedRemoteDocument],
    *,
    max_documents=100,
    max_bytes=1_000_000,
) -> Iterator[DocumentBatch]:
    """Yield stable batches bounded by count and serialized wire size."""
    current: list[NormalizedRemoteDocument] = []
    sequence = 0
    for document in documents:
        candidate = current + [document]
        encoded = json.dumps(
            [item.model_dump(mode="json") for item in candidate],
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
        if current and (len(candidate) > max_documents or len(encoded) > max_bytes):
            payload = DocumentBatch(job_id=job_id, batch_id="pending", documents=current)
            checksum = hashlib.sha256(payload.model_dump_json().encode()).hexdigest()
            yield payload.model_copy(update={"batch_id": f"{job_id}:{sequence}:{checksum}"})
            sequence, current = sequence + 1, [document]
        else:
            current = candidate
    if current:
        payload = DocumentBatch(job_id=job_id, batch_id="pending", documents=current)
        checksum = hashlib.sha256(payload.model_dump_json().encode()).hexdigest()
        yield payload.model_copy(update={"batch_id": f"{job_id}:{sequence}:{checksum}"})


class ExtractionError(RuntimeError):
    pass


async def extract_confined(
    root_id, path, roots, *, expected: ScanFile, source_id, extraction, max_snapshot_bytes
) -> NormalizedRemoteDocument | None:
    """Snapshot a pinned read handle before passing a path to legacy extractors."""
    if expected.size_bytes > max_snapshot_bytes:
        raise ExtractionError("file exceeds snapshot limit")
    with tempfile.TemporaryDirectory(prefix="onesearch-agent-") as directory:
        snapshot = Path(directory) / Path(path).name
        with open_confined_file(root_id, path, roots) as handle, snapshot.open("wb") as output:
            before = os.fstat(handle.fileno())
            if before.st_size != expected.size_bytes or before.st_mtime_ns != expected.modified_at:
                raise ExtractionError("file changed since scan")
            copied = 0
            while block := handle.read(64 * 1024):
                copied += len(block)
                if copied > max_snapshot_bytes:
                    raise ExtractionError("file exceeds snapshot limit")
                output.write(block)
            after = os.fstat(handle.fileno())
            if (
                copied != expected.size_bytes
                or after.st_size != before.st_size
                or after.st_mtime_ns != before.st_mtime_ns
            ):
                raise ExtractionError("file changed during snapshot")
        extractor = choose_extractor(
            str(snapshot), source_id, extraction["source_name"], extraction
        )
        if extractor is None:
            return None
        document = await extractor.extract_with_timeout(str(snapshot))
    return NormalizedRemoteDocument(
        source_id=source_id,
        path=path,
        title=document.title,
        content=document.content,
        size_bytes=expected.size_bytes,
        modified_at=expected.modified_at,
        metadata={**document.metadata, "type": document.type},
    )


async def run_scan_job(lease, client, *, roots) -> None:
    """Execute only on-agent scan leases; individual files never abort a scan."""
    if (
        lease.kind.value != "scan"
        or lease.processing_mode is None
        or lease.processing_mode.value != "on_agent"
    ):
        return
    payload, root_id = lease.payload, lease.payload.get("root_id")
    if not root_id or not lease.source_id:
        await client.complete(
            lease.id,
            JobCompletion(job_id=lease.id, status=JobStatus.FAILED, detail="invalid scan payload"),
            lease.lease_token,
        )
        return
    scanner = RemoteScanner(
        root_id,
        roots,
        include_patterns=payload.get("include_patterns"),
        exclude_patterns=payload.get("exclude_patterns"),
        known=payload.get("known_files"),
    )
    manifest = scanner.scan(job_id=lease.id, source_id=lease.source_id)
    expected = {item.path: item for item in manifest.files}
    documents = []
    for path in scanner.changed_paths:
        try:
            document = await extract_confined(
                root_id,
                path,
                roots,
                expected=expected[path],
                source_id=lease.source_id,
                extraction=payload.get("extraction", {"source_name": lease.source_id}),
                max_snapshot_bytes=payload.get("limits", {}).get(
                    "max_snapshot_bytes", 100 * 1024 * 1024
                ),
            )
            if document is not None:
                documents.append(document)
        except Exception:
            # The terminal manifest remains complete; this file will have no success receipt.
            continue
    for batch in batch_documents(lease.id, documents):
        await client.submit_batch(lease.id, batch, lease.lease_token)
    await client.complete(
        lease.id, JobCompletion(job_id=lease.id, status=JobStatus.SUCCEEDED), lease.lease_token
    )
