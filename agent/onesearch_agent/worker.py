"""On-agent scan job worker with bounded, replay-safe document batches."""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import stat
import tempfile
from collections.abc import Iterator
from pathlib import Path

from onesearch_shared import (
    DocumentBatch,
    JobCompletion,
    JobFailureReason,
    JobStatus,
    NormalizedRemoteDocument,
    ScanFailure,
    ScanFile,
)

from app.services.extractor_config import choose_extractor

from .paths import open_confined_file
from .scanner import RemoteScanner


class BatchBuildError(ValueError):
    pass


def _batch_wire_bytes(batch) -> bytes:
    """Exact submitted DocumentBatch wire representation."""
    return json.dumps(
        batch.model_dump(mode="json"),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")


class OversizedDocumentError(BatchBuildError):
    pass


class StreamingBatchBuilder:
    def __init__(self, job_id, *, max_documents=100, max_bytes=1_000_000):
        if max_documents < 1 or max_bytes < 1:
            raise BatchBuildError("batch limits must be positive")
        self.job_id, self.max_documents, self.max_bytes, self.sequence, self.current = (
            job_id,
            max_documents,
            max_bytes,
            0,
            [],
        )

    def _emit(self):
        docs = list(self.current)
        seed = DocumentBatch(
            job_id=self.job_id, batch_id=f"{self.job_id}:{self.sequence}:{'0' * 64}", documents=docs
        )
        digest = hashlib.sha256(_batch_wire_bytes(seed)).hexdigest()
        batch = DocumentBatch(
            job_id=self.job_id, batch_id=f"{self.job_id}:{self.sequence}:{digest}", documents=docs
        )
        self.sequence += 1
        self.current = []
        return batch

    def _fits(self, docs):
        seed = DocumentBatch(
            job_id=self.job_id,
            batch_id=f"{self.job_id}:{self.sequence}:{'0' * 64}",
            documents=list(docs),
        )
        return len(docs) <= self.max_documents and len(_batch_wire_bytes(seed)) <= self.max_bytes

    def add(self, doc):
        candidate = self.current + [doc]
        if len(candidate) <= self.max_documents and self._fits(candidate):
            self.current = candidate
            return []
        if not self.current or not self._fits([doc]):
            raise OversizedDocumentError(doc.path[:200])
        emitted = self._emit()
        self.current = [doc]
        return [emitted]

    def finish(self):
        return [self._emit()] if self.current else []


def batch_documents(
    job_id, documents, *, max_documents=100, max_bytes=1_000_000
) -> Iterator[DocumentBatch]:
    builder = StreamingBatchBuilder(job_id, max_documents=max_documents, max_bytes=max_bytes)
    for document in documents:
        yield from builder.add(document)
    yield from builder.finish()


class ExtractionError(RuntimeError):
    pass


def _safe_failure(error, fallback="extraction failed"):
    if isinstance(error, ExtractionError):
        value = str(error)
    else:
        value = f"{fallback}: {type(error).__name__}"
    return "".join(char for char in value if char >= " " and char not in "\x7f")[:500] or fallback


async def extract_confined(
    root_id, path, roots, *, expected: ScanFile, source_id, extraction, max_snapshot_bytes
) -> NormalizedRemoteDocument | None:
    """Snapshot a pinned read handle before passing a path to legacy extractors."""
    if max_snapshot_bytes <= 0 or expected.size_bytes > max_snapshot_bytes:
        raise ExtractionError("file exceeds snapshot limit")
    with tempfile.TemporaryDirectory(prefix="onesearch-agent-") as directory:
        snapshot = Path(directory) / Path(path).name
        with open_confined_file(root_id, path, roots) as handle, snapshot.open("wb") as output:
            before = os.fstat(handle.fileno())
            if not stat.S_ISREG(before.st_mode):
                raise ExtractionError("source is not a regular file")
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
    """Execute a scan, preserving per-file failures in the terminal manifest."""
    invalid = (
        lease.kind.value != "scan"
        or lease.processing_mode is None
        or lease.processing_mode.value != "on_agent"
    )
    payload, root_id = lease.payload, lease.payload.get("root_id")
    limits = payload.get("limits", {})
    required = {"source_name", "unsupported_file_policy", "max_text_file_size_mb"}
    invalid = (
        invalid
        or not root_id
        or not lease.source_id
        or root_id not in {root.root_id for root in roots}
        or not required <= set(payload.get("extraction", {}))
        or any(not isinstance(value, int) or value <= 0 for value in limits.values())
    )
    if invalid:
        await client.complete(
            lease.id,
            JobCompletion(
                job_id=lease.id,
                status=JobStatus.FAILED,
                reason=JobFailureReason.INVALID_REQUEST,
                detail="invalid scan payload",
            ),
            lease.lease_token,
        )
        return
    scanner = RemoteScanner(
        root_id,
        roots,
        include_patterns=payload.get("include_patterns"),
        exclude_patterns=payload.get("exclude_patterns"),
        known=payload.get("known_files"),
        max_files=limits.get("max_scan_files", 100000),
        max_entries_per_directory=limits.get("max_entries_per_directory", 100000),
    )
    manifest = scanner.scan(job_id=lease.id, source_id=lease.source_id)
    failures = {failure.path: failure for failure in manifest.failures}
    expected = {item.path: item for item in manifest.files}
    await client.job_heartbeat(
        lease.id,
        __import__("onesearch_shared").JobProgress(
            job_id=lease.id, completed_items=0, total_items=len(scanner.changed_paths)
        ),
        lease.lease_token,
    )
    builder = StreamingBatchBuilder(
        lease.id,
        max_documents=limits.get("max_batch_documents", 100),
        max_bytes=limits.get("max_batch_bytes", 1_000_000),
    )
    completed = 0
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
                for batch in builder.add(document):
                    await client.submit_batch(lease.id, batch, lease.lease_token)
        except asyncio.CancelledError:
            raise
        except Exception as error:
            failures[path] = ScanFailure(path=path, error=_safe_failure(error))
        finally:
            completed += 1
            await client.job_heartbeat(
                lease.id,
                __import__("onesearch_shared").JobProgress(
                    job_id=lease.id,
                    completed_items=completed,
                    total_items=len(scanner.changed_paths),
                ),
                lease.lease_token,
            )
    for batch in builder.finish():
        await client.submit_batch(lease.id, batch, lease.lease_token)
    manifest = manifest.model_copy(
        update={"failures": [failures[path] for path in sorted(failures)]}
    )
    await client.submit_manifest(lease.id, manifest, lease.lease_token)
    if not manifest.complete:
        await client.complete(
            lease.id,
            JobCompletion(job_id=lease.id, status=JobStatus.FAILED, detail="incomplete scan"),
            lease.lease_token,
        )
        return
    await client.complete(
        lease.id, JobCompletion(job_id=lease.id, status=JobStatus.SUCCEEDED), lease.lease_token
    )
