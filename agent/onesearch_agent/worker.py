"""On-agent scan job worker with bounded, replay-safe document batches."""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import stat
import tempfile
from collections.abc import Iterator
from contextlib import suppress
from pathlib import Path
from typing import Literal

from onesearch_shared import (
    REMOTE_JOB_HEARTBEAT_SECONDS,
    REMOTE_MAX_BATCH_BYTES,
    REMOTE_MAX_BATCH_DOCUMENTS,
    REMOTE_MAX_BROWSE_DIRECTORIES,
    REMOTE_MAX_ENTRIES_PER_DIRECTORY,
    REMOTE_MAX_MANIFEST_PAGE_BYTES,
    REMOTE_MAX_MANIFEST_PAGE_ENTRIES,
    REMOTE_MAX_SNAPSHOT_BYTES,
    BrowseDirectoryEntry,
    BrowseResult,
    DocumentBatch,
    JobCompletion,
    JobFailureReason,
    JobProgress,
    JobStatus,
    NormalizedRemoteDocument,
    ScanFile,
    ScanPageOutcome,
    ScanPageOutcomePayload,
    ScanPathOutcome,
    ScanPathOutcomeStatus,
    canonical_wire_bytes,
)
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StrictBool,
    StrictInt,
    StrictStr,
    ValidationError,
)

from app.services.extractor_config import choose_extractor
from app.services.remote_files import RemoteExtractionError, extract_in_process, extraction_process

from .client import AgentAmbiguousResultError, JobConflict, JobLeaseError
from .paths import (
    ConfinedFileMissing,
    PathOutsideAllowedRoots,
    confined_relative,
    list_confined_browse_directories_page,
    list_confined_entries_page,
    open_confined_file,
    resolve_allowed_path,
    resolve_source_prefix,
)
from .scan_spool import ScanSpool
from .scanner import RemoteScanner


class BatchBuildError(ValueError):
    pass


class ExtractionPayload(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    source_name: StrictStr = Field(min_length=1)
    unsupported_file_policy: Literal["skip", "metadata_only"]
    media_metadata_mode: Literal["auto", "off"]
    raw_metadata_mode: Literal["auto", "off"]
    index_gps_metadata: StrictBool
    max_text_file_size_mb: StrictInt = Field(gt=0)
    max_pdf_file_size_mb: StrictInt = Field(gt=0)
    max_office_file_size_mb: StrictInt = Field(gt=0)
    image_metadata_max_size_mb: StrictInt = Field(gt=0)
    epub_extraction_max_size_mb: StrictInt = Field(gt=0)
    comic_extraction_max_size_mb: StrictInt = Field(gt=0)
    media_probe_max_size_mb: StrictInt = Field(ge=0)
    text_extraction_timeout: StrictInt = Field(gt=0)
    pdf_extraction_timeout: StrictInt = Field(gt=0)
    office_extraction_timeout: StrictInt = Field(gt=0)
    raw_metadata_timeout_seconds: StrictInt = Field(gt=0)


class V3ScanLimits(BaseModel):
    """Paged scans bound each manifest page, not the complete inventory."""

    model_config = ConfigDict(extra="forbid", strict=True)

    max_snapshot_bytes: StrictInt = Field(gt=0, le=REMOTE_MAX_SNAPSHOT_BYTES)
    max_batch_documents: StrictInt = Field(gt=0, le=REMOTE_MAX_BATCH_DOCUMENTS)
    max_batch_bytes: StrictInt = Field(gt=0, le=REMOTE_MAX_BATCH_BYTES)
    max_entries_per_directory: StrictInt = Field(gt=0, le=REMOTE_MAX_ENTRIES_PER_DIRECTORY)
    max_manifest_page_entries: StrictInt = Field(
        ge=REMOTE_MAX_MANIFEST_PAGE_ENTRIES, le=REMOTE_MAX_MANIFEST_PAGE_ENTRIES
    )
    max_manifest_page_bytes: StrictInt = Field(
        ge=REMOTE_MAX_MANIFEST_PAGE_BYTES, le=REMOTE_MAX_MANIFEST_PAGE_BYTES
    )


class ScanPayload(BaseModel):
    """Strict server-issued scan contract; agents never infer missing defaults."""

    model_config = ConfigDict(extra="forbid", strict=True)

    full: StrictBool
    protocol_version: StrictInt = Field(ge=3, le=3)
    root_id: StrictStr = Field(min_length=1)
    root_path: StrictStr = Field(min_length=1)
    include_patterns: list[StrictStr] | None
    exclude_patterns: list[StrictStr] | None
    extraction: ExtractionPayload
    limits: V3ScanLimits


def _batch_wire_bytes(batch) -> bytes:
    """Exact submitted DocumentBatch wire representation."""
    return canonical_wire_bytes(batch)


class OversizedDocumentError(BatchBuildError):
    pass


class StreamingBatchBuilder:
    def __init__(self, job_id, *, max_documents=100, max_bytes=1_000_000, batch_prefix=None):
        if max_documents < 1 or max_bytes < 1:
            raise BatchBuildError("batch limits must be positive")
        (
            self.job_id,
            self.max_documents,
            self.max_bytes,
            self.batch_prefix,
            self.sequence,
            self.current,
        ) = (
            job_id,
            max_documents,
            max_bytes,
            batch_prefix or job_id,
            0,
            [],
        )

    def _emit(self):
        docs = list(self.current)
        seed = DocumentBatch(
            job_id=self.job_id,
            batch_id=f"{self.batch_prefix}:{self.sequence}:{'0' * 64}",
            documents=docs,
        )
        digest = hashlib.sha256(_batch_wire_bytes(seed)).hexdigest()
        batch = DocumentBatch(
            job_id=self.job_id,
            batch_id=f"{self.batch_prefix}:{self.sequence}:{digest}",
            documents=docs,
        )
        self.sequence += 1
        self.current = []
        return batch

    def _fits(self, docs, sequence=None):
        sequence = self.sequence if sequence is None else sequence
        seed = DocumentBatch(
            job_id=self.job_id,
            batch_id=f"{self.batch_prefix}:{sequence}:{'0' * 64}",
            documents=list(docs),
        )
        return len(docs) <= self.max_documents and len(_batch_wire_bytes(seed)) <= self.max_bytes

    def add(self, doc):
        candidate = self.current + [doc]
        if len(candidate) <= self.max_documents and self._fits(candidate):
            self.current = candidate
            return []
        if not self.current or not self._fits([doc], self.sequence + 1):
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


_extract_snapshot_process = extraction_process


async def _extract_snapshot_in_process(*args, **kwargs):
    try:
        return await extract_in_process(*args, **kwargs)
    except RemoteExtractionError as error:
        raise ExtractionError(str(error)) from error


class ScanCancelled(RuntimeError):  # noqa: N818
    pass


def _safe_failure(error, fallback="extraction failed"):
    if isinstance(error, ExtractionError):
        value = str(error)
    else:
        value = f"{fallback}: {type(error).__name__}"
    return "".join(char for char in value if char >= " " and char not in "\x7f")[:500] or fallback


async def _submit_idempotent(operation, *, attempts=3, sleep=asyncio.sleep):
    """Retry only uncertain results for operations with an idempotency contract."""
    if attempts < 1:
        raise ValueError("attempts must be positive")
    for attempt in range(attempts):
        try:
            return await operation()
        except AgentAmbiguousResultError:
            if attempt == attempts - 1:
                raise
            await sleep(min(5, 2**attempt))


async def _complete_with_recovery(client, lease, completion):
    async def status_matches():
        status = await client.job_status(lease.id)
        expected = {
            JobStatus.SUCCEEDED: "completed",
            JobStatus.FAILED: "failed",
            JobStatus.CANCELLED: "cancelled",
        }[completion.status]
        # An on-server scan releases its own lease after durable manifest handoff;
        # its parent remains running while server-owned child extraction settles.
        released_parent = (
            completion.status is JobStatus.SUCCEEDED
            and getattr(getattr(lease, "kind", None), "value", None) == "scan"
            and getattr(getattr(lease, "processing_mode", None), "value", None) == "on_server"
            and status.handoff_released
        )
        return status.status, status.status == expected or (released_parent and status.status == "running")

    try:
        await client.complete(lease.id, completion, lease.lease_token)
        return
    except AgentAmbiguousResultError as error:
        first = error
    try:
        status, matches = await status_matches()
        if matches:
            return
    except Exception as error:
        raise AgentAmbiguousResultError("terminal completion unresolved") from error
    if status not in {"claimed", "running"}:
        raise AgentAmbiguousResultError("terminal completion unresolved") from first
    try:
        await client.complete(lease.id, completion, lease.lease_token)
        return
    except (AgentAmbiguousResultError, JobLeaseError, JobConflict) as error:
        try:
            _status, matches = await status_matches()
            if matches:
                return
        except Exception as query_error:
            raise AgentAmbiguousResultError("terminal completion unresolved") from query_error
        raise AgentAmbiguousResultError("terminal completion unresolved") from error


class LeaseKeeper:
    """Own serialized lease heartbeats while a scan job is in flight."""

    def __init__(
        self,
        lease,
        client,
        *,
        attempts=3,
        interval=REMOTE_JOB_HEARTBEAT_SECONDS,
        sleep=asyncio.sleep,
    ):
        self.lease, self.client = lease, client
        self.attempts, self.interval, self.sleep = attempts, interval, sleep
        self.completed, self.total, self.error = 0, None, None
        self.cancelled, self._cancel_acknowledged = False, False
        self._lock = asyncio.Lock()
        self._task = None

    async def _heartbeat(self):
        async with self._lock:
            try:
                await _submit_idempotent(
                    lambda: self.client.job_heartbeat(
                        self.lease.id,
                        JobProgress(
                            job_id=self.lease.id,
                            completed_items=self.completed,
                            total_items=self.total,
                        ),
                        self.lease.lease_token,
                    ),
                    attempts=self.attempts,
                    sleep=self.sleep,
                )
            except JobConflict:
                await self.cancel_after_conflict()

    async def start(self):
        await self._heartbeat()
        await self.check()
        self._task = asyncio.create_task(self._run())

    def set_total(self, total):
        self.total = total if self.total is None else max(self.total, total)

    async def advance(self):
        self.completed += 1
        await self._heartbeat()
        await self.check()

    async def check(self):
        if self.cancelled:
            raise ScanCancelled()
        if self.error is not None:
            raise self.error

    async def cancel_after_conflict(self):
        if self._cancel_acknowledged:
            return
        self._cancel_acknowledged = True
        await self.client.cancel_ack(self.lease.id, self.lease.lease_token)
        self.cancelled = True

    async def _run(self):
        try:
            while True:
                await self.sleep(self.interval)
                await self._heartbeat()
        except asyncio.CancelledError:
            raise
        except Exception as error:
            self.error = error

    async def close(self):
        if self._task is not None:
            self._task.cancel()
            with suppress(asyncio.CancelledError):
                await self._task


async def _submit_or_cancel(keeper, operation, *, attempts, sleep):
    try:
        return await _submit_idempotent(operation, attempts=attempts, sleep=sleep)
    except JobConflict:
        await keeper.cancel_after_conflict()
        await keeper.check()


async def _submit_file_upload(keeper, operation, *, terminal=False):
    """Raw chunk uploads are single-attempt; only terminal ambiguity is queryable."""
    try:
        return await operation()
    except JobConflict:
        await keeper.cancel_after_conflict()
        await keeper.check()
    except AgentAmbiguousResultError:
        if terminal:
            status = await keeper.client.job_status(keeper.lease.id)
            if status.status == "completed":
                return
        raise


async def _maybe_upload_preview(
    client,
    lease,
    path: str,
    modified_at_ns: int,
    local_path: str | Path,
    *,
    mutation_attempts: int = 3,
    sleep=asyncio.sleep,
) -> None:
    """Generate and upload preview for browser-displayable images.

    Suppresses all exceptions to avoid failing the scan due to preview generation.
    """
    from app.services.preview_assets import is_browser_displayable_image

    extension = Path(path).suffix.lstrip(".").lower()
    if not is_browser_displayable_image(extension):
        return

    with suppress(Exception):
        from app.services.preview_assets import generate_derived_jpeg_preview

        preview_bytes = await asyncio.to_thread(
            generate_derived_jpeg_preview, str(local_path)
        )
        if preview_bytes is not None:
            await _submit_idempotent(
                lambda data=preview_bytes: client.upload_preview(
                    lease.id,
                    lease.lease_token,
                    path=path,
                    modified_at_ns=modified_at_ns,
                    preview_bytes=data,
                    checksum=hashlib.sha256(data).hexdigest(),
                ),
                attempts=mutation_attempts,
                sleep=sleep,
            )


async def _maybe_upload_confined_preview(
    client,
    lease,
    path: str,
    expected: ScanFile,
    *,
    root_id,
    roots,
    source_prefix,
    max_snapshot_bytes,
    mutation_attempts: int = 3,
    sleep=asyncio.sleep,
) -> None:
    """Create a preview from a no-follow snapshot of a source-relative file."""
    with suppress(Exception):
        if max_snapshot_bytes <= 0 or expected.size_bytes > max_snapshot_bytes:
            return
        confined_path = confined_relative(source_prefix, path)
        with tempfile.TemporaryDirectory(prefix="onesearch-agent-preview-") as directory:
            snapshot = Path(directory) / Path(path).name
            with (
                open_confined_file(root_id, confined_path, roots) as handle,
                snapshot.open("wb") as output,
            ):
                before = os.fstat(handle.fileno())
                if (
                    not stat.S_ISREG(before.st_mode)
                    or before.st_size != expected.size_bytes
                    or before.st_mtime_ns != expected.modified_at
                ):
                    return
                copied = 0
                while block := handle.read(64 * 1024):
                    copied += len(block)
                    if copied > max_snapshot_bytes:
                        return
                    output.write(block)
                after = os.fstat(handle.fileno())
                if (
                    copied != before.st_size
                    or after.st_size != before.st_size
                    or after.st_mtime_ns != before.st_mtime_ns
                ):
                    return
            await _maybe_upload_preview(
                client,
                lease,
                path,
                expected.modified_at,
                snapshot,
                mutation_attempts=mutation_attempts,
                sleep=sleep,
            )


async def extract_confined(
    root_id,
    path,
    roots,
    *,
    source_prefix="",
    expected: ScanFile,
    source_id,
    extraction,
    max_snapshot_bytes,
    _process_target=_extract_snapshot_process,
    _on_process_start=None,
) -> NormalizedRemoteDocument | None:
    """Snapshot a pinned read handle before passing a path to legacy extractors."""
    if max_snapshot_bytes <= 0 or expected.size_bytes > max_snapshot_bytes:
        raise ExtractionError("file exceeds snapshot limit")
    with tempfile.TemporaryDirectory(prefix="onesearch-agent-") as directory:
        snapshot = Path(directory) / Path(path).name
        confined_path = confined_relative(source_prefix, path)
        with (
            open_confined_file(root_id, confined_path, roots) as handle,
            snapshot.open("wb") as output,
        ):
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
        document = await _extract_snapshot_in_process(
            str(snapshot),
            source_id,
            extraction,
            extractor._extraction_timeout,
            process_target=_process_target,
            on_process_start=_on_process_start,
        )
        if document is None:
            return None
    return NormalizedRemoteDocument(
        source_id=source_id,
        path=path,
        title=document.title,
        content=document.content,
        size_bytes=expected.size_bytes,
        modified_at=expected.modified_at,
        metadata={**document.metadata, "type": document.type},
    )



async def run_scan_job(
    lease,
    client,
    *,
    roots,
    _mutation_attempts=3,
    _sleep=asyncio.sleep,
    _lease_interval=REMOTE_JOB_HEARTBEAT_SECONDS,
    _lease_sleep=asyncio.sleep,
    state_dir: Path | None = None,
) -> None:
    """Execute a scan, preserving per-file failures in the terminal manifest."""
    raw_payload = getattr(lease, "payload", None)
    if not isinstance(raw_payload, dict) or raw_payload.get("protocol_version") != 3:
        await _complete_with_recovery(
            client,
            lease,
            JobCompletion(
                job_id=lease.id,
                status=JobStatus.FAILED,
                reason=JobFailureReason.PROTOCOL_INCOMPATIBLE,
                detail="scan job requires protocol version 3",
            ),
        )
        return
    try:
        payload = ScanPayload.model_validate(raw_payload)
    except ValidationError:
        payload = None
    source_prefix = None
    if payload is not None:
        with suppress(PathOutsideAllowedRoots):
            source_prefix = resolve_source_prefix(payload.root_id, payload.root_path, roots)
    invalid = (
        getattr(getattr(lease, "kind", None), "value", None) != "scan"
        or getattr(getattr(lease, "processing_mode", None), "value", None)
        not in {"on_agent", "on_server"}
        or not isinstance(getattr(lease, "source_id", None), str)
        or not lease.source_id
        or payload is None
        or source_prefix is None
    )
    if invalid:
        await _complete_with_recovery(
            client,
            lease,
            JobCompletion(
                job_id=lease.id,
                status=JobStatus.FAILED,
                reason=JobFailureReason.INVALID_REQUEST,
                detail="invalid scan payload",
            ),
        )
        return
    root_id, limits = payload.root_id, payload.limits
    extraction = payload.extraction.model_dump()
    scanner = RemoteScanner(
        root_id,
        roots,
        include_patterns=payload.include_patterns,
        exclude_patterns=payload.exclude_patterns,
        source_prefix=source_prefix,
        max_entries_per_directory=limits.max_entries_per_directory,
    )
    keeper = LeaseKeeper(
        lease,
        client,
        attempts=_mutation_attempts,
        interval=_lease_interval,
        sleep=_lease_sleep,
    )
    await keeper.start()
    try:
        if state_dir is None:
            await _complete_with_recovery(
                client,
                lease,
                JobCompletion(
                    job_id=lease.id,
                    status=JobStatus.FAILED,
                    reason=JobFailureReason.PROTOCOL_INCOMPATIBLE,
                    detail="protocol v3 requires durable state",
                ),
            )
            return
        await _run_v3_scan_job(
            lease,
            client,
            keeper=keeper,
            scanner=scanner,
            root_id=root_id,
            roots=roots,
            source_prefix=source_prefix,
            extraction=extraction,
            limits=limits,
            state_dir=state_dir,
            mutation_attempts=_mutation_attempts,
            sleep=_sleep,
        )
    except ScanCancelled:
        return
    finally:
        await keeper.close()


def _v3_payload_identity(lease, payload: ScanPayload) -> str:
    """Bind durable work to the exact issued job/source/root/checkpoint contract."""
    value = {
        "job_id": lease.id,
        "source_id": lease.source_id,
        "root_id": payload.root_id,
        "root_path": payload.root_path,
        "payload": lease.payload,
    }
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
    ).hexdigest()


async def _run_v3_scan_job(
    lease,
    client,
    *,
    keeper,
    scanner,
    root_id,
    roots,
    source_prefix,
    extraction,
    limits,
    state_dir,
    mutation_attempts,
    sleep,
):
    """Replay sealed v3 pages until each receipt and outcome is durably accepted."""
    payload = ScanPayload.model_validate(lease.payload)
    identity = _v3_payload_identity(lease, payload)
    spool = None
    completed = False
    try:
        spool = scanner.scan_v3(
            state_dir=Path(state_dir),
            job_id=lease.id,
            source_id=lease.source_id,
            payload_identity=identity,
            resume=ScanSpool.lifecycle_exists(Path(state_dir), lease.id),
        )
        keeper.set_total(spool.file_count)
        sequence = 0
        while True:
            await keeper.check()
            page = spool.page(sequence)
            ack = await _submit_or_cancel(
                keeper,
                lambda page=page: client.submit_manifest_page(lease.id, page, lease.lease_token),
                attempts=mutation_attempts,
                sleep=sleep,
            )
            if (
                ack.job_id != lease.id
                or ack.sequence != page.page.sequence
                or ack.checksum != page.checksum
                or set(ack.changed_paths) - {item.path for item in page.page.files}
            ):
                raise JobConflict("invalid manifest page acknowledgement")
            if lease.processing_mode.value == "on_server":
                # The server owns extraction for this mode.  A persisted manifest page
                # fans out its changed entries into child transfer jobs; the agent must
                # neither extract nor settle per-path outcomes.
                await keeper.advance()
                if page.page.final:
                    break
                sequence += 1
                continue
            outcomes, documents = [], []
            expected = {item.path: item for item in page.page.files}
            for path in ack.changed_paths:
                await keeper.check()
                try:
                    document = await extract_confined(
                        root_id,
                        path,
                        roots,
                        source_prefix=source_prefix,
                        expected=expected[path],
                        source_id=lease.source_id,
                        extraction=extraction,
                        max_snapshot_bytes=limits.max_snapshot_bytes,
                    )
                except asyncio.CancelledError:
                    raise
                except Exception as error:
                    outcomes.append(
                        ScanPathOutcome(
                            path=path,
                            status=ScanPathOutcomeStatus.FAILED,
                            error=_safe_failure(error),
                        )
                    )
                else:
                    if document is None:
                        outcomes.append(
                            ScanPathOutcome(path=path, status=ScanPathOutcomeStatus.SKIPPED)
                        )
                    else:
                        documents.append(document)
            rejected = {}
            builder = StreamingBatchBuilder(
                lease.id,
                max_documents=limits.max_batch_documents,
                max_bytes=limits.max_batch_bytes,
                batch_prefix=f"{lease.id}:v3:{page.page.sequence}",
            )
            for document in documents:
                for batch in builder.add(document):
                    response = await _submit_or_cancel(
                        keeper,
                        lambda batch=batch: client.submit_batch(lease.id, batch, lease.lease_token),
                        attempts=mutation_attempts,
                        sleep=sleep,
                    )
                    rejected.update(response.rejected_paths)
            for batch in builder.finish():
                response = await _submit_or_cancel(
                    keeper,
                    lambda batch=batch: client.submit_batch(lease.id, batch, lease.lease_token),
                    attempts=mutation_attempts,
                    sleep=sleep,
                )
                rejected.update(response.rejected_paths)
            for document in documents:
                if document.path in rejected:
                    outcomes.append(
                        ScanPathOutcome(
                            path=document.path,
                            status=ScanPathOutcomeStatus.FAILED,
                            error=_safe_failure(ExtractionError(rejected[document.path])),
                        )
                    )
                else:
                    outcomes.append(
                        ScanPathOutcome(path=document.path, status=ScanPathOutcomeStatus.INDEXED)
                    )
                    # Generate and upload preview for browser-displayable images
                    await _maybe_upload_confined_preview(
                        client,
                        lease,
                        document.path,
                        expected[document.path],
                        root_id=root_id,
                        roots=roots,
                        source_prefix=source_prefix,
                        max_snapshot_bytes=limits.max_snapshot_bytes,
                        mutation_attempts=mutation_attempts,
                        sleep=sleep,
                    )
            outcome_payload = ScanPageOutcomePayload(
                job_id=lease.id,
                source_id=lease.source_id,
                sequence=page.page.sequence,
                page_checksum=page.checksum,
                results=sorted(outcomes, key=lambda item: item.path),
            )
            outcome = ScanPageOutcome(
                checksum=hashlib.sha256(canonical_wire_bytes(outcome_payload)).hexdigest(),
                outcome=outcome_payload,
            )
            outcome_ack = await _submit_or_cancel(
                keeper,
                lambda outcome=outcome: client.submit_page_outcome(
                    lease.id, outcome, lease.lease_token
                ),
                attempts=mutation_attempts,
                sleep=sleep,
            )
            if (
                outcome_ack.job_id != lease.id
                or outcome_ack.sequence != page.page.sequence
                or outcome_ack.checksum != outcome.checksum
            ):
                raise JobConflict("invalid scan page outcome acknowledgement")
            await keeper.advance()
            if page.page.final:
                break
            sequence += 1
        await keeper.check()
        await _complete_with_recovery(
            client, lease, JobCompletion(job_id=lease.id, status=JobStatus.SUCCEEDED)
        )
        completed = True
    finally:
        if spool is not None:
            spool.close()
        if completed:
            ScanSpool.cleanup(
                Path(state_dir),
                job_id=lease.id,
                payload_identity=identity,
                source_id=lease.source_id,
            )


async def run_browse_job(lease, client, *, roots) -> None:
    payload = getattr(lease, "payload", {})
    try:
        if lease.kind.value != "browse":
            raise ValueError("invalid browse payload")
        if payload.get("operation") == "validate":
            target = resolve_allowed_path(payload["root_path"], roots)
            if not target.is_dir():
                raise ValueError("browse root is not a directory")
            candidates = []
            for root in roots:
                root_path = Path(root.path).resolve()
                try:
                    candidates.append((len(root_path.parts), root, target.relative_to(root_path)))
                except ValueError:
                    continue
            _depth, root, relative = max(candidates, key=lambda item: item[0])
            list_confined_entries_page(root.root_id, relative.as_posix(), roots, max_entries=1)
            completion = JobCompletion(job_id=lease.id, status=JobStatus.SUCCEEDED)
        elif payload.get("operation") == "list":
            root_id, relative = payload["root_id"], payload["path"]
            if not isinstance(root_id, str) or not isinstance(relative, str):
                raise ValueError("invalid browse payload")
            # The scanner primitive resolves each component with no-follow handles. It is
            # deliberately capped independently from the small UI response limit.
            keeper = LeaseKeeper(lease, client)
            try:
                await keeper.start()
                page = await asyncio.to_thread(
                    list_confined_browse_directories_page,
                    root_id,
                    relative,
                    roots,
                    max_entries=REMOTE_MAX_BROWSE_DIRECTORIES,
                )
                await keeper.check()
            finally:
                await keeper.close()
            completion = JobCompletion(
                job_id=lease.id,
                status=JobStatus.SUCCEEDED,
                browse_result=BrowseResult(
                    root_id=root_id,
                    path=relative,
                    entries=[
                        BrowseDirectoryEntry(name=entry.name, path=entry.relative_path)
                        for entry in page.entries
                    ],
                    truncated=page.truncated,
                ),
            )
        else:
            raise ValueError("invalid browse payload")
    except ScanCancelled:
        # cancel_ack made the server terminal; never race it with a failed completion.
        return
    except JobLeaseError:
        # A 401 means this worker no longer owns the job (expired or requeued).
        return
    except Exception:
        completion = JobCompletion(
            job_id=lease.id,
            status=JobStatus.FAILED,
            reason=JobFailureReason.INVALID_REQUEST,
            detail="invalid browse payload",
        )
    await _complete_with_recovery(client, lease, completion)


async def _run_file_transfer_job(
    lease, client, *, roots, expected_kind, chunk_bytes=512 * 1024
) -> None:
    """Revalidate a pinned remote file then upload it in bounded raw chunks."""
    payload = getattr(lease, "payload", {})
    keeper = LeaseKeeper(lease, client)
    try:
        if (
            lease.kind.value != expected_kind
            or lease.processing_mode.value != "on_server"
            or not payload.get("root_id")
            or not payload.get("root_path")
            or not payload.get("path")
        ):
            raise ExtractionError("invalid extraction payload")
        source_prefix = resolve_source_prefix(payload["root_id"], payload["root_path"], roots)
        confined_path = confined_relative(source_prefix, payload["path"])
        await keeper.start()
        await keeper.check()
        with open_confined_file(payload["root_id"], confined_path, roots) as handle:
            before = os.fstat(handle.fileno())
            if (
                not stat.S_ISREG(before.st_mode)
                or before.st_size != payload["size_bytes"]
                or before.st_mtime_ns != payload["modified_at"]
            ):
                raise ExtractionError("file changed since scan")
            digest, sequence, copied = hashlib.sha256(), 0, 0
            while chunk := handle.read(chunk_bytes):
                await keeper.check()
                copied += len(chunk)
                if copied > payload["maximum_size"]:
                    raise ExtractionError("file exceeds transfer limit")
                digest.update(chunk)
                await _submit_file_upload(
                    keeper,
                    lambda chunk=chunk, sequence=sequence: client.upload_file_chunk(
                        lease.id,
                        lease.lease_token,
                        sequence=sequence,
                        data=chunk,
                        checksum=hashlib.sha256(chunk).hexdigest(),
                    ),
                )
                sequence += 1
            after = os.fstat(handle.fileno())
            if (
                copied != before.st_size
                or after.st_size != before.st_size
                or after.st_mtime_ns != before.st_mtime_ns
            ):
                raise ExtractionError("file changed during transfer")
        if payload.get("content_hash") and digest.hexdigest() != payload["content_hash"]:
            raise ExtractionError("file content changed since scan")
        await _submit_file_upload(
            keeper,
            lambda: client.upload_file_chunk(
                lease.id,
                lease.lease_token,
                sequence=sequence,
                complete=True,
                stream_checksum=digest.hexdigest(),
            ),
            terminal=True,
        )
    except asyncio.CancelledError:
        raise
    except ScanCancelled:
        return
    except JobConflict:
        await client.cancel_ack(lease.id, lease.lease_token)
        return
    except Exception as error:
        missing = isinstance(error, (FileNotFoundError, ConfinedFileMissing))
        changed = isinstance(error, ExtractionError) and "changed" in str(error)
        invalid = isinstance(error, PathOutsideAllowedRoots)
        await _complete_with_recovery(
            client,
            lease,
            JobCompletion(
                job_id=lease.id,
                status=JobStatus.FAILED,
                reason=(
                    JobFailureReason.NOT_FOUND
                    if missing
                    else JobFailureReason.INVALID_REQUEST
                    if changed or invalid
                    else JobFailureReason.EXTRACTION_FAILED
                ),
                detail=(
                    "remote_file_missing"
                    if missing
                    else "remote_file_changed"
                    if changed
                    else "invalid extraction payload"
                    if invalid
                    else _safe_failure(error)
                ),
            ),
        )
    finally:
        await keeper.close()


async def run_extract_file_job(lease, client, *, roots, chunk_bytes=512 * 1024) -> None:
    await _run_file_transfer_job(
        lease, client, roots=roots, expected_kind="extract_file", chunk_bytes=chunk_bytes
    )


async def run_stream_file_job(lease, client, *, roots, chunk_bytes=512 * 1024) -> None:
    await _run_file_transfer_job(
        lease, client, roots=roots, expected_kind="stream_file", chunk_bytes=chunk_bytes
    )


async def dispatch_job(lease, client, *, roots, state_dir=None) -> None:
    if getattr(getattr(lease, "kind", None), "value", None) == "scan":
        if state_dir is None:
            await run_scan_job(lease, client, roots=roots)
        else:
            await run_scan_job(lease, client, roots=roots, state_dir=state_dir)
    elif getattr(getattr(lease, "kind", None), "value", None) == "browse":
        await run_browse_job(lease, client, roots=roots)
    elif getattr(getattr(lease, "kind", None), "value", None) == "extract_file":
        await run_extract_file_job(lease, client, roots=roots)
    elif getattr(getattr(lease, "kind", None), "value", None) == "stream_file":
        await run_stream_file_job(lease, client, roots=roots)
    else:
        raise ValueError("unsupported job kind")
