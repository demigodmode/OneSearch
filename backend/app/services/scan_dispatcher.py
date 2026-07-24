"""Single boundary for local indexing and durable remote scan dispatch."""

from ..models import Source
from .agent_jobs import AgentJobService, JobConflict
from .indexer import IndexingService


class SourceNotFound(Exception):
    """Raised when dispatch is requested for a deleted source."""


class ScanDispatcher:
    def __init__(self, db, search_service):
        self.db = db
        self.search_service = search_service

    async def dispatch(self, source_id: str, reason: str, full: bool = False):
        source = self.db.get(Source, source_id)
        if source is None:
            raise SourceNotFound(source_id)
        if getattr(source, "location_type", "local") != "agent":
            return await IndexingService(self.db, self.search_service).index_source(
                source_id, full=full
            )
        if not source.agent_id:
            raise JobConflict("source is not remote")
        job = AgentJobService(self.db).enqueue_scan(source, full=full, reason=reason)
        return job
