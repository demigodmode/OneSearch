# Copyright (C) 2025 demigodmode
# SPDX-License-Identifier: AGPL-3.0-only

"""
Scheduled indexing service using APScheduler.
Runs indexing jobs in a background thread on cron schedules.
"""
import asyncio
import logging
import threading
from datetime import datetime, timezone
from typing import Optional

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.jobstores.sqlalchemy import SQLAlchemyJobStore
from sqlalchemy.orm import sessionmaker, Session

from ..config import settings
from ..models import Source
from ..services.indexer import IndexingService
from ..services.search import meili_service

logger = logging.getLogger(__name__)

# Preset aliases → cron expressions
SCHEDULE_PRESETS = {
    "@hourly": "0 * * * *",
    "@daily": "0 2 * * *",       # 2 AM
    "@weekly": "0 2 * * 0",      # Sunday 2 AM
}

# Per-source locks to prevent concurrent indexing
_indexing_locks: dict[str, threading.Lock] = {}
_locks_lock = threading.Lock()


def get_source_lock(source_id: str) -> threading.Lock:
    with _locks_lock:
        if source_id not in _indexing_locks:
            _indexing_locks[source_id] = threading.Lock()
        return _indexing_locks[source_id]


def resolve_cron(schedule: str) -> str:
    """Resolve a schedule string to a cron expression."""
    return SCHEDULE_PRESETS.get(schedule, schedule)


def validate_schedule(schedule: str) -> bool:
    """Check if a schedule string is valid."""
    cron_expr = resolve_cron(schedule)
    try:
        CronTrigger.from_crontab(cron_expr, timezone=settings.schedule_timezone)
        return True
    except (ValueError, KeyError):
        return False


class SchedulerService:
    """
    Manages APScheduler for background source indexing.
    Uses BackgroundScheduler (daemon thread) with SQLAlchemy job store.
    """

    def __init__(self, engine):
        self.engine = engine
        self.scheduler: Optional[BackgroundScheduler] = None
        self._session_factory = sessionmaker(bind=engine)

    def start(self):
        if not settings.scheduler_enabled:
            logger.info("Scheduler disabled via SCHEDULER_ENABLED=false")
            return

        try:
            jobstores = {
                "default": SQLAlchemyJobStore(engine=self.engine)
            }

            self.scheduler = BackgroundScheduler(
                jobstores=jobstores,
                timezone=settings.schedule_timezone,
            )
            self.scheduler.start()
            logger.info(f"Scheduler started (timezone={settings.schedule_timezone})")

            self._sync_all_jobs()
        except Exception as e:
            logger.warning(f"Failed to start scheduler: {e}")
            self.scheduler = None

    def shutdown(self):
        if self.scheduler and self.scheduler.running:
            self.scheduler.shutdown(wait=False)
            logger.info("Scheduler shut down")

    def _sync_all_jobs(self):
        """Load schedules from DB and sync with APScheduler state."""
        db = self._session_factory()
        try:
            sources = db.query(Source).filter(
                Source.scan_schedule.isnot(None),
                Source.scan_schedule != "",
            ).all()

            expected_ids = set()
            for source in sources:
                job_id = f"index-{source.id}"
                expected_ids.add(job_id)
                self._add_or_update_job(source.id, source.scan_schedule, db)

            # Clean up jobs for sources that no longer have schedules
            for job in self.scheduler.get_jobs():
                if job.id.startswith("index-") and job.id not in expected_ids:
                    self.scheduler.remove_job(job.id)
                    logger.info(f"Removed stale job: {job.id}")
        finally:
            db.close()

    def update_source_schedule(self, source_id: str, schedule: Optional[str]):
        """Called when a source's schedule is created/updated/cleared."""
        if not self.scheduler or not self.scheduler.running:
            return

        job_id = f"index-{source_id}"

        if not schedule:
            try:
                self.scheduler.remove_job(job_id)
                logger.info(f"Removed scheduled job for source '{source_id}'")
            except Exception:
                pass
            # Clear next_scan_at
            db = self._session_factory()
            try:
                source = db.get(Source, source_id)
                if source:
                    source.next_scan_at = None
                    db.commit()
            finally:
                db.close()
            return

        db = self._session_factory()
        try:
            self._add_or_update_job(source_id, schedule, db)
        finally:
            db.close()

    def _add_or_update_job(self, source_id: str, schedule: str, db: Session):
        job_id = f"index-{source_id}"
        cron_expr = resolve_cron(schedule)

        try:
            trigger = CronTrigger.from_crontab(cron_expr, timezone=settings.schedule_timezone)
        except (ValueError, KeyError) as e:
            logger.error(f"Invalid cron '{cron_expr}' for source '{source_id}': {e}")
            return

        self.scheduler.add_job(
            func=self._run_indexing_job,
            trigger=trigger,
            args=[source_id],
            id=job_id,
            name=f"Index source: {source_id}",
            replace_existing=True,
            misfire_grace_time=3600,
        )

        # Update next_scan_at on the source record
        job = self.scheduler.get_job(job_id)
        if job and job.next_run_time:
            source = db.get(Source, source_id)
            if source:
                source.next_scan_at = job.next_run_time.replace(tzinfo=None)
                db.commit()
            logger.info(f"Scheduled indexing for '{source_id}': {cron_expr} (next: {job.next_run_time})")
        else:
            logger.warning(f"Scheduled indexing for '{source_id}': {cron_expr} (next run time unknown)")

    def _run_indexing_job(self, source_id: str):
        """Job function called by APScheduler in a background thread."""
        lock = get_source_lock(source_id)
        if not lock.acquire(blocking=False):
            logger.warning(f"Skipping scheduled index for '{source_id}' - already running")
            return

        try:
            db = self._session_factory()
            try:
                source = db.get(Source, source_id)
                if not source:
                    logger.warning(f"Scheduled job: source '{source_id}' not found, skipping")
                    return

                logger.info(f"Scheduled indexing starting for '{source.name}'")

                loop = asyncio.new_event_loop()
                try:
                    indexing_service = IndexingService(db, meili_service)
                    stats = loop.run_until_complete(indexing_service.index_source(source_id))
                finally:
                    loop.close()

                source.last_scan_at = datetime.now(timezone.utc).replace(tzinfo=None)
                job = self.scheduler.get_job(f"index-{source_id}")
                if job and job.next_run_time:
                    source.next_scan_at = job.next_run_time.replace(tzinfo=None)
                db.commit()

                logger.info(
                    f"Scheduled indexing complete for '{source.name}': "
                    f"{stats.successful} indexed, {stats.failed} failed"
                )
            finally:
                db.close()
        finally:
            lock.release()

    def remove_source(self, source_id: str):
        """Clean up job when a source is deleted."""
        if not self.scheduler or not self.scheduler.running:
            return
        try:
            self.scheduler.remove_job(f"index-{source_id}")
        except Exception:
            pass
        with _locks_lock:
            _indexing_locks.pop(source_id, None)
