"""Validation and durable ingestion boundary for on-agent document batches."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone

from onesearch_shared import BatchAck, DocumentBatch, ScanManifest, remote_path_hash
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from ..models import AgentBatch, AgentJob, IndexedFile, Source
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

    async def accept_batch(
        self, agent_id: str, job_id: str, lease_token: str, batch: DocumentBatch
    ):
        jobs = AgentJobService(self.db)
        jobs.validate_lease(agent_id, job_id, lease_token)
        if batch.job_id != job_id:
            raise JobConflict("batch job mismatch")
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
            or job.processing_mode != "on_agent"
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

    def accept_manifest(
        self, agent_id: str, job_id: str, lease_token: str, manifest: ScanManifest
    ) -> None:
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
        for row in missing:
            confirmed = getattr(self.search_service, "delete_document_confirmed", None)
            await (
                confirmed(remote_document_id(job.source_id, row.path))
                if confirmed
                else self.search_service.delete_document(
                    remote_document_id(job.source_id, row.path)
                )
            )
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
        jobs.complete_reconciled_scan(agent_id, job_id, lease_token)
