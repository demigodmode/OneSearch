"""Validation and durable ingestion boundary for on-agent document batches."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone

from onesearch_shared import DocumentBatch, ScanManifest
from sqlalchemy import select

from ..models import AgentJob, IndexedFile, Source
from ..schemas import Document
from .agent_jobs import JobConflict


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
    return f"{source_id}--{hashlib.sha256(path.encode()).hexdigest()[:12]}"


class RemoteIngestService:
    def __init__(self, db, search_service):
        self.db, self.search_service = db, search_service

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
        documents = []
        for item in batch.documents:
            path = canonical_remote_path(item.path)
            if item.source_id != source.id:
                raise JobConflict("document source mismatch")
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
                    modified_at=item.modified_at,
                    indexed_at=int(datetime.now(timezone.utc).timestamp()),
                    content=item.content,
                    title=item.title,
                    metadata=dict(item.metadata),
                )
            )
        # Search is intentionally first: a failed external write never creates a receipt.
        await self.search_service.index_documents(documents)
        for doc in documents:
            record = self.db.scalar(
                select(IndexedFile).where(
                    IndexedFile.source_id == source.id, IndexedFile.path == doc.path
                )
            )
            if record is None:
                record = IndexedFile(source_id=source.id, path=doc.path)
                self.db.add(record)
            record.size_bytes, record.modified_at = (
                doc.size_bytes,
                datetime.fromtimestamp(doc.modified_at, timezone.utc).replace(tzinfo=None),
            )
            record.hash, record.status, record.error_message = (
                remote_document_id(source.id, doc.path),
                "success",
                None,
            )
        return documents

    def store_manifest(self, agent_id: str, job_id: str, manifest: ScanManifest) -> None:
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
            if path in paths:
                raise JobConflict("duplicate manifest path")
            paths.add(path)
        for failure in manifest.failures:
            canonical_remote_path(failure.path)
        job.checkpoint = json.dumps(
            {"remote_manifest": manifest.model_dump(mode="json")},
            sort_keys=True,
            separators=(",", ":"),
        )
