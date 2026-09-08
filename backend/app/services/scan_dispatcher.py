"""Single boundary for local indexing and durable remote scan dispatch."""

from ..models import Agent, Source
from .agent_auth import agent_is_fresh, mark_stale_agent_offline
from .agent_jobs import AgentJobService, JobConflict
from .app_settings import AppSettingsService
from .indexer import IndexingService


class SourceNotFoundError(Exception):
    """Raised when dispatch is requested for a deleted source."""


class RemoteAgentsDisabledError(Exception):
    """Remote job dispatch is globally disabled."""


class AgentUnavailableError(Exception):
    """The source agent cannot safely receive durable work."""


class ScanDispatcher:
    def __init__(self, db, search_service):
        self.db = db
        self.search_service = search_service

    async def dispatch(self, source_id: str, reason: str, full: bool = False):
        source = self.db.get(Source, source_id)
        if source is None:
            raise SourceNotFoundError(source_id)
        if getattr(source, "location_type", "local") != "agent":
            return await IndexingService(self.db, self.search_service).index_source(
                source_id, full=full
            )
        if not source.agent_id:
            raise JobConflict("source is not remote")
        if not AppSettingsService(self.db).get_settings().remote_agents_enabled:
            raise RemoteAgentsDisabledError()
        agent = self.db.get(Agent, source.agent_id)
        if (
            agent is None
            or agent.approved_at is None
            or agent.token_hash is None
            or agent.status not in {"offline", "online"}
        ):
            raise AgentUnavailableError()
        job_reason = reason
        if reason == "schedule" and (agent.status == "offline" or not agent_is_fresh(agent)):
            if agent.status == "online":
                mark_stale_agent_offline(self.db, agent)
            job_reason = "catch_up"
        job = AgentJobService(self.db).enqueue_scan(source, full=full, reason=job_reason)
        return job
