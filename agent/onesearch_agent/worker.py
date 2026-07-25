"""On-agent scan job worker with bounded, replay-safe document batches."""

from __future__ import annotations

import hashlib
import json
import shutil
import tempfile
from collections.abc import Iterator
from pathlib import Path

from onesearch_shared import DocumentBatch, JobCompletion, JobStatus, NormalizedRemoteDocument

from app.extractors import MetadataOnlyExtractor, extractor_registry

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


def extract_confined(root_id, path, roots, *, source_id, source_name) -> NormalizedRemoteDocument:
    """Snapshot a pinned read handle before passing a path to legacy extractors."""
    suffix = Path(path).suffix
    with tempfile.TemporaryDirectory(prefix="onesearch-agent-") as directory:
        snapshot = Path(directory) / (Path(path).stem + suffix)
        with open_confined_file(root_id, path, roots) as handle, snapshot.open("wb") as output:
            shutil.copyfileobj(handle, output, length=64 * 1024)
        extractor = extractor_registry.get_extractor(str(snapshot), source_id, source_name)
        document = (extractor or MetadataOnlyExtractor(source_id, source_name)).extract(
            str(snapshot)
        )
    return NormalizedRemoteDocument(
        source_id=source_id,
        path=path,
        title=document.title,
        content=document.content,
        size_bytes=document.size_bytes,
        modified_at=document.modified_at,
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
    scanner.scan(job_id=lease.id, source_id=lease.source_id)
    documents = []
    for path in scanner.changed_paths:
        try:
            documents.append(
                extract_confined(
                    root_id,
                    path,
                    roots,
                    source_id=lease.source_id,
                    source_name=payload.get("extraction", {}).get("source_name", lease.source_id),
                )
            )
        except Exception:
            # The terminal manifest remains complete; this file will have no success receipt.
            continue
    for batch in batch_documents(lease.id, documents):
        await client.submit_batch(lease.id, batch, lease.lease_token)
    await client.complete(
        lease.id, JobCompletion(job_id=lease.id, status=JobStatus.SUCCEEDED), lease.lease_token
    )
