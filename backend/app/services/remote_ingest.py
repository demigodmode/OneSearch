"""Validation and durable ingestion boundary for on-agent document batches."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone

from onesearch_shared import (
    REMOTE_MAX_BATCH_BYTES,
    REMOTE_MAX_MANIFEST_BYTES,
    REMOTE_MAX_MANIFEST_PAGE_BYTES,
    BatchAck,
    DocumentBatch,
    ScanCheckpoint,
    ScanManifest,
    ScanManifestPage,
    ScanManifestPageAck,
    ScanPageOutcome,
    ScanPageOutcomeAck,
    ScanPathOutcomeStatus,
    canonical_wire_bytes,
    remote_path_hash,
)
from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError

from ..models import (
    Agent,
    AgentBatch,
    AgentJob,
    AgentScanEntry,
    AgentScanPage,
    IndexedFile,
    Source,
)
from ..schemas import Document
from .agent_jobs import AgentJobService, JobConflict


def canonical_remote_path(path: str) -> str:
    if (
        not path
        or path.startswith("/")
        or "\\" in path
        or any(part in {"", ".", ".."} for part in path.split("/"))
    ):
        raise JobConflict("invalid remote document path")
    return path


def remote_document_id(source_id: str, path: str) -> str:
    return f"{source_id}--{remote_path_hash(path)[:12]}"


class RemoteIngestService:
    def __init__(self, db, search_service):
        self.db, self.search_service = db, search_service

    def _paged_scan_job(self, agent_id: str, job_id: str, lease_token: str) -> AgentJob:
        job = AgentJobService(self.db).lock_active_lease(agent_id, job_id, lease_token)
        agent = self.db.get(Agent, agent_id)
        try:
            payload = json.loads(job.payload)
        except (TypeError, json.JSONDecodeError) as error:
            raise JobConflict("invalid paged scan job") from error
        protocol_version = payload.get("protocol_version") if isinstance(payload, dict) else None
        if (
            job.kind != "scan"
            or job.source_id is None
            or job.processing_mode not in {"on_agent", "on_server"}
            or agent is None
            or agent.protocol_version < 3
            or type(protocol_version) is not int
            or protocol_version < 3
        ):
            raise JobConflict("invalid paged scan job")
        return job

    def _page_ack(self, page: AgentScanPage, *, duplicate: bool) -> ScanManifestPageAck:
        changed_paths = list(
            self.db.scalars(
                select(AgentScanEntry.path)
                .where(
                    AgentScanEntry.job_id == page.job_id,
                    AgentScanEntry.page_sequence == page.sequence,
                    AgentScanEntry.needs_processing.is_(True),
                )
                .order_by(AgentScanEntry.path)
            )
        )
        return ScanManifestPageAck(
            job_id=page.job_id,
            sequence=page.sequence,
            checksum=page.checksum,
            accepted_count=page.entry_count,
            changed_paths=changed_paths,
            duplicate=duplicate,
            checkpoint=ScanCheckpoint(cursor=page.cursor, scanned_count=page.scanned_count),
        )

    def _indexed_by_path(self, source_id: str, paths: list[str]) -> dict[str, IndexedFile]:
        indexed = {}
        for start in range(0, len(paths), 400):
            chunk = paths[start : start + 400]
            for item in self.db.scalars(
                select(IndexedFile).where(
                    IndexedFile.source_id == source_id, IndexedFile.path.in_(chunk)
                )
            ):
                indexed.setdefault(item.path, item)
        return indexed

    def _first_staged_path(self, job_id: str, paths: list[str]) -> str | None:
        for start in range(0, len(paths), 400):
            repeated = self.db.scalar(
                select(AgentScanEntry.path)
                .where(
                    AgentScanEntry.job_id == job_id,
                    AgentScanEntry.path.in_(paths[start : start + 400]),
                )
                .limit(1)
            )
            if repeated is not None:
                return repeated
        return None

    @staticmethod
    def _modified_at_ns(item: IndexedFile) -> int | None:
        if item.modified_at_ns is not None:
            return item.modified_at_ns
        if item.modified_at is None:
            return None
        value = (
            item.modified_at.replace(tzinfo=timezone.utc)
            if item.modified_at.tzinfo is None
            else item.modified_at
        )
        return int(value.timestamp() * 1_000_000_000)

    def accept_manifest_page(
        self,
        agent_id: str,
        job_id: str,
        lease_token: str,
        submission: ScanManifestPage,
    ) -> ScanManifestPageAck:
        if len(canonical_wire_bytes(submission)) > REMOTE_MAX_MANIFEST_PAGE_BYTES:
            raise JobConflict("manifest page exceeds wire size limit")
        job = self._paged_scan_job(agent_id, job_id, lease_token)
        request = submission.page
        if request.job_id != job_id or request.source_id != job.source_id:
            raise JobConflict("invalid manifest page")

        existing = self.db.scalar(
            select(AgentScanPage).where(
                AgentScanPage.job_id == job_id, AgentScanPage.sequence == request.sequence
            )
        )
        if existing is not None:
            if existing.checksum != submission.checksum:
                raise JobConflict("manifest page checksum conflict")
            return self._page_ack(existing, duplicate=True)

        previous = self.db.scalar(
            select(AgentScanPage)
            .where(AgentScanPage.job_id == job_id)
            .order_by(AgentScanPage.sequence.desc())
            .limit(1)
        )
        if previous is None:
            if request.sequence != 0 or request.checkpoint.scanned_count < len(request.files):
                raise JobConflict("manifest page sequence conflict")
        else:
            minimum_count = previous.scanned_count + len(request.files)
            if (
                previous.is_final
                or request.sequence != previous.sequence + 1
                or request.checkpoint.scanned_count < minimum_count
                or request.checkpoint.cursor == previous.cursor
            ):
                raise JobConflict("manifest page sequence conflict")

        canonical_files = []
        paths = []
        for item in request.files:
            path = canonical_remote_path(item.path)
            if item.path_hash != remote_path_hash(path):
                raise JobConflict("manifest path hash mismatch")
            canonical_files.append((path, item))
            paths.append(path)
        if paths:
            repeated = self._first_staged_path(job_id, paths)
            if repeated is not None:
                raise JobConflict("manifest path already staged")

        indexed = self._indexed_by_path(job.source_id, paths)
        full = bool(json.loads(job.payload).get("full"))
        page = AgentScanPage(
            job_id=job_id,
            sequence=request.sequence,
            checksum=submission.checksum,
            cursor=request.checkpoint.cursor,
            scanned_count=request.checkpoint.scanned_count,
            is_final=request.final,
            entry_count=len(canonical_files),
        )
        entries = []
        for path, item in canonical_files:
            known = indexed.get(path)
            needs_processing = full or (
                known is None
                or known.status != "success"
                or known.size_bytes != item.size_bytes
                or self._modified_at_ns(known) != item.modified_at
                or (
                    bool(known.hash) and bool(item.content_hash) and known.hash != item.content_hash
                )
            )
            entries.append(
                AgentScanEntry(
                    job_id=job_id,
                    page_sequence=request.sequence,
                    path=path,
                    path_hash=item.path_hash,
                    size_bytes=item.size_bytes,
                    modified_at_ns=item.modified_at,
                    content_hash=item.content_hash,
                    needs_processing=needs_processing,
                )
            )
        try:
            with self.db.begin_nested():
                self.db.add(page)
                self.db.add_all(entries)
                self.db.flush()
        except IntegrityError as error:
            winner = self.db.scalar(
                select(AgentScanPage).where(
                    AgentScanPage.job_id == job_id,
                    AgentScanPage.sequence == request.sequence,
                )
            )
            if winner is None or winner.checksum != submission.checksum:
                raise JobConflict("manifest page conflict") from error
            return self._page_ack(winner, duplicate=True)
        return self._page_ack(page, duplicate=False)

    def accept_page_outcome(
        self,
        agent_id: str,
        job_id: str,
        lease_token: str,
        submission: ScanPageOutcome,
    ) -> ScanPageOutcomeAck:
        if len(canonical_wire_bytes(submission)) > REMOTE_MAX_MANIFEST_PAGE_BYTES:
            raise JobConflict("scan page outcome exceeds wire size limit")
        job = self._paged_scan_job(agent_id, job_id, lease_token)
        request = submission.outcome
        if (
            job.processing_mode != "on_agent"
            or request.job_id != job_id
            or request.source_id != job.source_id
        ):
            raise JobConflict("invalid scan page outcome")
        page = self.db.scalar(
            select(AgentScanPage).where(
                AgentScanPage.job_id == job_id, AgentScanPage.sequence == request.sequence
            )
        )
        if page is None or request.page_checksum != page.checksum:
            raise JobConflict("invalid scan page outcome")
        if page.outcome_checksum is not None:
            if page.outcome_checksum != submission.checksum:
                raise JobConflict("scan page outcome checksum conflict")
            return self._outcome_ack(page, duplicate=True)
        unsettled_previous = self.db.scalar(
            select(AgentScanPage.id)
            .where(
                AgentScanPage.job_id == job_id,
                AgentScanPage.sequence < request.sequence,
                AgentScanPage.settled_at.is_(None),
            )
            .limit(1)
        )
        if unsettled_previous is not None:
            raise JobConflict("scan page outcome is out of order")

        entries = list(
            self.db.scalars(
                select(AgentScanEntry).where(
                    AgentScanEntry.job_id == job_id,
                    AgentScanEntry.page_sequence == request.sequence,
                )
            )
        )
        changed = {item.path: item for item in entries if item.needs_processing}
        results = {item.path: item for item in request.results}
        if set(results) != set(changed):
            raise JobConflict("scan page outcome paths do not match changed paths")

        indexed = self._indexed_by_path(
            job.source_id,
            [
                path
                for path, result in results.items()
                if result.status is ScanPathOutcomeStatus.INDEXED
            ],
        )
        for path, result in results.items():
            if result.status is ScanPathOutcomeStatus.INDEXED:
                entry = changed[path]
                current = indexed.get(path)
                if (
                    current is None
                    or current.status != "success"
                    or current.size_bytes != entry.size_bytes
                    or self._modified_at_ns(current) != entry.modified_at_ns
                ):
                    raise JobConflict("indexed scan page outcome is not durable")
        for path, result in results.items():
            entry = changed[path]
            entry.outcome_status = result.status.value
            entry.failure_error = result.error
        page.outcome_checksum = submission.checksum
        page.settled_at = datetime.now(timezone.utc).replace(tzinfo=None)
        job.checkpoint = json.dumps(
            {
                "version": 2,
                "scan_page": {
                    "sequence": page.sequence,
                    "cursor": page.cursor,
                    "scanned_count": page.scanned_count,
                    "final": page.is_final,
                },
            },
            sort_keys=True,
            separators=(",", ":"),
        )
        self.db.flush()
        return self._outcome_ack(page, duplicate=False)

    def _outcome_ack(self, page: AgentScanPage, *, duplicate: bool) -> ScanPageOutcomeAck:
        settled_count = self.db.scalar(
            select(func.count(AgentScanEntry.id)).where(
                AgentScanEntry.job_id == page.job_id,
                AgentScanEntry.page_sequence == page.sequence,
                AgentScanEntry.outcome_status.is_not(None),
            )
        )
        return ScanPageOutcomeAck(
            job_id=page.job_id,
            sequence=page.sequence,
            checksum=page.outcome_checksum,
            settled_count=settled_count or 0,
            duplicate=duplicate,
            checkpoint=ScanCheckpoint(cursor=page.cursor, scanned_count=page.scanned_count),
        )

    async def accept_batch(
        self, agent_id: str, job_id: str, lease_token: str, batch: DocumentBatch
    ):
        if len(canonical_wire_bytes(batch)) > REMOTE_MAX_BATCH_BYTES:
            raise JobConflict("batch exceeds wire size limit")
        jobs = AgentJobService(self.db)
        if batch.job_id != job_id:
            raise JobConflict("batch job mismatch")
        jobs.lock_active_lease(agent_id, job_id, lease_token)
        canonical = json.dumps(
            batch.model_dump(mode="json"), sort_keys=True, separators=(",", ":"), ensure_ascii=False
        )
        checksum = hashlib.sha256(canonical.encode()).hexdigest()
        existing = self.db.scalar(
            select(AgentBatch).where(
                AgentBatch.job_id == job_id, AgentBatch.idempotency_key == batch.batch_id
            )
        )
        if existing is not None:
            if existing.checksum != checksum:
                raise JobConflict("batch checksum conflict")
            return BatchAck(
                batch_id=batch.batch_id, accepted_count=len(batch.documents), duplicate=True
            )
        try:
            with self.db.begin_nested():
                self.db.add(
                    AgentBatch(job_id=job_id, idempotency_key=batch.batch_id, checksum=checksum)
                )
                self.db.flush()
        except IntegrityError as error:
            winner = self.db.scalar(
                select(AgentBatch).where(
                    AgentBatch.job_id == job_id, AgentBatch.idempotency_key == batch.batch_id
                )
            )
            if winner is None or winner.checksum != checksum:
                raise JobConflict("batch checksum conflict") from error
            return BatchAck(
                batch_id=batch.batch_id, accepted_count=len(batch.documents), duplicate=True
            )
        await self.ingest(agent_id, job_id, batch)
        return BatchAck(
            batch_id=batch.batch_id, accepted_count=len(batch.documents), duplicate=False
        )

    async def ingest(self, agent_id: str, job_id: str, batch: DocumentBatch):
        job = self.db.get(AgentJob, job_id)
        if (
            job is None
            or job.agent_id != agent_id
            or job.source_id is None
            or not (
                job.processing_mode == "on_agent"
                or (job.processing_mode == "on_server" and job.kind == "extract_file")
            )
        ):
            raise JobConflict("invalid remote job")
        source = self.db.get(Source, job.source_id)
        if source is None:
            raise JobConflict("source missing")
        documents, wire_modified_at_ns = [], {}
        for item in batch.documents:
            path = canonical_remote_path(item.path)
            if item.source_id != source.id:
                raise JobConflict("document source mismatch")
            wire_modified_at_ns[path] = item.modified_at
            documents.append(
                Document(
                    id=remote_document_id(source.id, path),
                    source_id=source.id,
                    source_name=source.name,
                    path=path,
                    basename=path.rsplit("/", 1)[-1],
                    extension=path.rsplit(".", 1)[-1].lower() if "." in path else "",
                    type=item.metadata.get("type", "remote"),
                    size_bytes=item.size_bytes or 0,
                    modified_at=item.modified_at // 1_000_000_000,
                    indexed_at=int(datetime.now(timezone.utc).timestamp()),
                    content=item.content,
                    title=item.title,
                    metadata=dict(item.metadata),
                )
            )
        # Search is intentionally first: a failed external write never creates a receipt.
        confirmed = getattr(self.search_service, "index_documents_confirmed", None)
        await (
            confirmed(documents) if confirmed else self.search_service.index_documents(documents)
        )
        for doc in documents:
            record = self.db.scalar(
                select(IndexedFile).where(
                    IndexedFile.source_id == source.id, IndexedFile.path == doc.path
                )
            )
            if record is None:
                record = IndexedFile(source_id=source.id, path=doc.path)
                self.db.add(record)
            seconds = doc.modified_at
            record.size_bytes, record.modified_at = (
                doc.size_bytes,
                datetime.fromtimestamp(seconds, timezone.utc).replace(tzinfo=None),
            )
            record.modified_at_ns = wire_modified_at_ns[doc.path]
            record.hash, record.status, record.error_message = (
                remote_document_id(source.id, doc.path),
                "success",
                None,
            )
        return documents

    async def accept_server_document(self, agent_id: str, job_id: str, lease_token: str, document):
        """Idempotently ingest the normalized result of one temporary remote original."""
        jobs = AgentJobService(self.db)
        job = jobs.lock_active_lease(agent_id, job_id, lease_token)
        if job.kind != "extract_file" or job.processing_mode != "on_server":
            raise JobConflict("invalid remote extraction")
        payload = json.loads(job.payload)
        parent = self.db.get(AgentJob, payload.get("parent_job_id"))
        if (
            parent is None
            or parent.kind != "scan"
            or parent.processing_mode != "on_server"
            or parent.agent_id != agent_id
            or parent.source_id != job.source_id
            or document.source_id != job.source_id
            or document.path != payload.get("path")
        ):
            raise JobConflict("invalid remote extraction parent")
        receipt = hashlib.sha256(
            canonical_wire_bytes(
                DocumentBatch(job_id=job_id, batch_id="pending", documents=[document])
            )
        ).hexdigest()
        existing = self.db.scalar(
            select(AgentBatch).where(
                AgentBatch.job_id == job_id, AgentBatch.idempotency_key == "remote-result"
            )
        )
        if existing is None:
            self.db.add(
                AgentBatch(job_id=job_id, idempotency_key="remote-result", checksum=receipt)
            )
            self.db.flush()
            await self.ingest(
                agent_id,
                job_id,
                DocumentBatch(job_id=job_id, batch_id="remote-result", documents=[document]),
            )
        elif existing.checksum != receipt:
            raise JobConflict("remote extraction receipt conflict")
        jobs.complete(agent_id, job_id, lease_token, "succeeded")

    async def settle_server_parent(self, parent_id: str) -> str:
        """Settle a lease-released on-server scan only after all child work is terminal."""
        parent = self.db.get(AgentJob, parent_id)
        if (
            parent is None
            or parent.kind != "scan"
            or parent.processing_mode != "on_server"
            or parent.status != "running"
            or parent.lease_token_hash is not None
        ):
            raise JobConflict("invalid server parent")
        children = [
            child
            for child in self.db.scalars(select(AgentJob).where(AgentJob.kind == "extract_file"))
            if json.loads(child.payload).get("parent_job_id") == parent_id
        ]
        if any(
            child.status in {"pending", "claimed", "running", "cancelling"} for child in children
        ):
            return "running"
        if any(child.status in {"failed", "cancelled"} for child in children):
            parent.status, parent.error, parent.active_key, parent.completed_at = (
                "failed",
                "remote child extraction failed",
                None,
                datetime.now(timezone.utc).replace(tzinfo=None),
            )
            return "failed"
        checkpoint = json.loads(parent.checkpoint)
        raw = checkpoint.get("remote_manifest") if checkpoint.get("version") == 1 else None
        if raw is None:
            raise JobConflict("complete manifest required")
        manifest = ScanManifest.model_validate(raw)
        if (
            not manifest.complete
            or manifest.job_id != parent.id
            or manifest.source_id != parent.source_id
        ):
            parent.status, parent.error, parent.active_key, parent.completed_at = (
                "failed",
                "complete manifest required",
                None,
                datetime.now(timezone.utc).replace(tzinfo=None),
            )
            return "failed"
        current = {canonical_remote_path(item.path) for item in manifest.files}
        current.update(canonical_remote_path(item.path) for item in manifest.failures)
        rows = list(
            self.db.scalars(select(IndexedFile).where(IndexedFile.source_id == parent.source_id))
        )
        missing = [row for row in rows if row.path not in current]
        ids = [remote_document_id(parent.source_id, row.path) for row in missing]
        locked = self.db.execute(
            update(AgentJob)
            .where(
                AgentJob.id == parent.id,
                AgentJob.status == "running",
                AgentJob.lease_token_hash.is_(None),
            )
            .values(
                status="completed",
                active_key=None,
                completed_at=datetime.now(timezone.utc).replace(tzinfo=None),
            )
        )
        if locked.rowcount != 1:
            return self.db.get(AgentJob, parent.id).status
        confirmed_many = getattr(self.search_service, "delete_documents_confirmed", None)
        try:
            if ids and confirmed_many:
                await confirmed_many(ids)
            elif ids:
                for document_id in ids:
                    confirmed = getattr(self.search_service, "delete_document_confirmed", None)
                    await (
                        confirmed(document_id)
                        if confirmed
                        else self.search_service.delete_document(document_id)
                    )
        except BaseException:
            self.db.rollback()
            raise
        for row in missing:
            self.db.delete(row)
        self.db.flush()
        return "completed"

    def accept_manifest(
        self, agent_id: str, job_id: str, lease_token: str, manifest: ScanManifest
    ) -> None:
        if len(canonical_wire_bytes(manifest)) > REMOTE_MAX_MANIFEST_BYTES:
            raise JobConflict("manifest exceeds wire size limit")
        AgentJobService(self.db).validate_lease(agent_id, job_id, lease_token)
        job = self.db.get(AgentJob, job_id)
        if (
            job is None
            or job.agent_id != agent_id
            or job.source_id != manifest.source_id
            or job.processing_mode != "on_agent"
            or manifest.job_id != job_id
        ):
            raise JobConflict("invalid remote manifest")
        paths = set()
        for item in manifest.files:
            path = canonical_remote_path(item.path)
            if item.path_hash != remote_path_hash(path):
                raise JobConflict("manifest path hash mismatch")
            if path in paths:
                raise JobConflict("duplicate manifest path")
            paths.add(path)
        deleted = [canonical_remote_path(path) for path in manifest.deleted_paths]
        if len(deleted) != len(set(deleted)):
            raise JobConflict("duplicate manifest deleted path")
        failures = [canonical_remote_path(failure.path) for failure in manifest.failures]
        if len(failures) != len(set(failures)):
            raise JobConflict("duplicate manifest failure path")
        for failure in manifest.failures:
            canonical_remote_path(failure.path)
        job.checkpoint = json.dumps(
            {"version": 1, "remote_manifest": manifest.model_dump(mode="json")},
            sort_keys=True,
            separators=(",", ":"),
        )

    async def reconcile_completion(self, agent_id: str, job_id: str, lease_token: str) -> None:
        jobs = AgentJobService(self.db)
        job = jobs.validate_lease(agent_id, job_id, lease_token)
        if job.kind != "scan" or job.processing_mode != "on_agent" or not job.source_id:
            raise JobConflict("invalid remote completion")
        checkpoint = json.loads(job.checkpoint)
        raw = checkpoint.get("remote_manifest") if checkpoint.get("version") == 1 else None
        if raw is None:
            raise JobConflict("complete manifest required")
        manifest = ScanManifest.model_validate(raw)
        if (
            not manifest.complete
            or manifest.job_id != job_id
            or manifest.source_id != job.source_id
        ):
            raise JobConflict("complete manifest required")
        current = {canonical_remote_path(item.path) for item in manifest.files}
        current.update(canonical_remote_path(item.path) for item in manifest.failures)
        rows = list(
            self.db.scalars(select(IndexedFile).where(IndexedFile.source_id == job.source_id))
        )
        missing = [row for row in rows if row.path not in current]
        jobs.complete_reconciled_scan(agent_id, job_id, lease_token)
        ids = [remote_document_id(job.source_id, row.path) for row in missing]
        confirmed_many = getattr(self.search_service, "delete_documents_confirmed", None)
        try:
            if ids and confirmed_many:
                await confirmed_many(ids)
            elif ids:
                for document_id in ids:
                    confirmed = getattr(self.search_service, "delete_document_confirmed", None)
                    await (
                        confirmed(document_id)
                        if confirmed
                        else self.search_service.delete_document(document_id)
                    )
        except BaseException:
            self.db.rollback()
            raise
        for row in missing:
            self.db.delete(row)
        for failure in manifest.failures:
            path = canonical_remote_path(failure.path)
            row = self.db.scalar(
                select(IndexedFile).where(
                    IndexedFile.source_id == job.source_id, IndexedFile.path == path
                )
            )
            if row is None:
                row = IndexedFile(source_id=job.source_id, path=path)
                self.db.add(row)
            row.status, row.error_message = "failed", failure.error
        self.db.flush()
