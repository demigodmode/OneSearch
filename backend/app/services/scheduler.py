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
from apscheduler.triggers.interval import IntervalTrigger
from sqlalchemy.orm import Session, sessionmaker

from ..config import settings
from ..models import Source
from ..services.indexer import IndexingService  # noqa: F401 - legacy patch target
from ..services.scan_dispatcher import (
    AgentUnavailableError,
    RemoteAgentsDisabledError,
    ScanDispatcher,
)
from ..services.search import meili_service

logger = logging.getLogger(__name__)

# Preset aliases → cron expressions
SCHEDULE_PRESETS = {
    "@hourly": "0 * * * *",
    "@daily": "0 2 * * *",  # 2 AM
    "@weekly": "0 2 * * 0",  # Sunday 2 AM
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


def calculate_next_run_time(schedule: str) -> Optional[datetime]:
    """Calculate the next run time for a schedule, returns naive UTC datetime."""
    cron_expr = resolve_cron(schedule)
    try:
        trigger = CronTrigger.from_crontab(cron_expr, timezone=settings.schedule_timezone)
        next_time = trigger.get_next_fire_time(None, datetime.now(timezone.utc))
        if next_time:
            return next_time.replace(tzinfo=None)
        return None
    except (ValueError, KeyError):
        return None


VALID_INTERVAL_UNITS = ("minutes", "hours", "days")


def validate_interval(value: Optional[int], unit: Optional[str]) -> bool:
    """Check if an interval value/unit pair is valid."""
    return isinstance(value, int) and value > 0 and unit in VALID_INTERVAL_UNITS


def build_interval_trigger(value: int, unit: str) -> IntervalTrigger:
    """Build an APScheduler IntervalTrigger from a value/unit pair."""
    return IntervalTrigger(**{unit: value}, timezone=settings.schedule_timezone)


def calculate_interval_next_run_time(value: int, unit: str) -> Optional[datetime]:
    """Calculate the next run time for a true interval schedule, naive UTC datetime."""
    if not validate_interval(value, unit):
        return None
    trigger = build_interval_trigger(value, unit)
    next_time = trigger.get_next_fire_time(None, datetime.now(timezone.utc))
    if next_time:
        return next_time.replace(tzinfo=None)
    return None


def calculate_next_run_time_for_schedule(
    schedule_type: str,
    scan_schedule: Optional[str],
    interval_value: Optional[int],
    interval_unit: Optional[str],
) -> Optional[datetime]:
    """Dispatch to the cron or interval next-run-time calculator based on schedule_type."""
    if schedule_type == "interval":
        return calculate_interval_next_run_time(interval_value, interval_unit)
    if not scan_schedule:
        return None
    return calculate_next_run_time(scan_schedule)


def resolve_effective_schedule(
    source: Source, db: Session, default_schedule: Optional[dict] = None
) -> dict:
    """
    Resolve the schedule that actually drives a source's next run: its own
    schedule, or the global default when use_default_schedule is set.
    Returns a dict shaped like ScheduleConfig (schedule_type, scan_schedule,
    interval_value, interval_unit). A "cron" type with scan_schedule=None
    means "manual only".

    Pass a pre-fetched default_schedule dict (e.g. from
    AppSettingsService(db).get_settings().default_scan_schedule.model_dump())
    when resolving many sources at once, to avoid re-querying app settings
    once per source.
    """
    if source.use_default_schedule:
        if default_schedule is None:
            from ..services.app_settings import AppSettingsService

            default = AppSettingsService(db).get_settings().default_scan_schedule
            default_schedule = default.model_dump() if default else None
        if default_schedule is None:
            return {
                "schedule_type": "cron",
                "scan_schedule": None,
                "interval_value": None,
                "interval_unit": None,
            }
        return default_schedule

    return {
        "schedule_type": source.schedule_type,
        "scan_schedule": source.scan_schedule,
        "interval_value": source.interval_value,
        "interval_unit": source.interval_unit,
    }


def _schedule_is_manual(resolved: dict) -> bool:
    if resolved["schedule_type"] == "interval":
        return not validate_interval(resolved.get("interval_value"), resolved.get("interval_unit"))
    return not resolved.get("scan_schedule")


class SchedulerService:
    """
    Manages APScheduler for background source indexing.
    Uses BackgroundScheduler (daemon thread) with in-memory job store.
    Jobs are rebuilt from the Source table on every startup via _sync_all_jobs.
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
            self.scheduler = BackgroundScheduler(
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
            from ..services.app_settings import AppSettingsService

            default = AppSettingsService(db).get_settings().default_scan_schedule
            default_schedule = default.model_dump() if default else None

            sources = db.query(Source).all()

            expected_ids = set()
            for source in sources:
                resolved = resolve_effective_schedule(source, db, default_schedule)
                if _schedule_is_manual(resolved):
                    continue
                job_id = f"index-{source.id}"
                expected_ids.add(job_id)
                self._add_or_update_job(source.id, resolved, db)

            # Clean up jobs for sources that no longer have an active schedule
            for job in self.scheduler.get_jobs():
                if job.id.startswith("index-") and job.id not in expected_ids:
                    self.scheduler.remove_job(job.id)
                    logger.info(f"Removed stale job: {job.id}")
        finally:
            db.close()

    def update_source_schedule(self, source_id: str):
        """Called when a source's own schedule fields or use_default_schedule change."""
        if not self.scheduler or not self.scheduler.running:
            return

        job_id = f"index-{source_id}"
        db = self._session_factory()
        try:
            source = db.get(Source, source_id)
            if not source:
                try:
                    self.scheduler.remove_job(job_id)
                except Exception:
                    pass
                return

            resolved = resolve_effective_schedule(source, db)
            if _schedule_is_manual(resolved):
                try:
                    self.scheduler.remove_job(job_id)
                    logger.info(f"Removed scheduled job for source '{source_id}'")
                except Exception:
                    pass
                source.next_scan_at = None
                db.commit()
                return

            self._add_or_update_job(source_id, resolved, db)
        finally:
            db.close()

    def sync_default_schedule_sources(self):
        """Called when the global default_scan_schedule setting changes. Re-syncs
        only sources with use_default_schedule=True; custom sources are untouched."""
        if not self.scheduler or not self.scheduler.running:
            return

        db = self._session_factory()
        try:
            from ..services.app_settings import AppSettingsService

            default = AppSettingsService(db).get_settings().default_scan_schedule
            default_schedule = default.model_dump() if default else None

            sources = db.query(Source).filter(Source.use_default_schedule.is_(True)).all()
            for source in sources:
                resolved = resolve_effective_schedule(source, db, default_schedule)
                job_id = f"index-{source.id}"
                if _schedule_is_manual(resolved):
                    try:
                        self.scheduler.remove_job(job_id)
                    except Exception:
                        pass
                    source.next_scan_at = None
                    db.commit()
                else:
                    self._add_or_update_job(source.id, resolved, db)
        finally:
            db.close()

    def _add_or_update_job(self, source_id: str, resolved: dict, db: Session):
        job_id = f"index-{source_id}"
        schedule_type = resolved["schedule_type"]

        if schedule_type == "interval":
            if not validate_interval(resolved.get("interval_value"), resolved.get("interval_unit")):
                logger.error(f"Invalid interval for source '{source_id}': {resolved}")
                return
            trigger = build_interval_trigger(resolved["interval_value"], resolved["interval_unit"])
            schedule_label = f"every {resolved['interval_value']} {resolved['interval_unit']}"
        else:
            cron_expr = resolve_cron(resolved.get("scan_schedule") or "")
            try:
                trigger = CronTrigger.from_crontab(cron_expr, timezone=settings.schedule_timezone)
            except (ValueError, KeyError) as e:
                logger.error(f"Invalid cron '{cron_expr}' for source '{source_id}': {e}")
                return
            schedule_label = cron_expr

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
            logger.info(
                f"Scheduled indexing for '{source_id}': {schedule_label} (next: {job.next_run_time})"
            )
        else:
            logger.warning(
                f"Scheduled indexing for '{source_id}': {schedule_label} (next run time unknown)"
            )

    def _run_indexing_job(self, source_id: str):
        """Job function called by APScheduler in a background thread."""
        # Preserve the legacy fast-path for a known local lock.  New remote
        # dispatches never touch this in-process lock; AgentJob.active_key is
        # their durable coalescing boundary.
        lock = _indexing_locks.get(source_id)
        lock_acquired = False
        if lock is not None:
            lock_acquired = lock.acquire(blocking=False)
            if not lock_acquired:
                logger.warning(f"Skipping scheduled index for '{source_id}' - already running")
                return
        db = self._session_factory()
        try:
            source = db.get(Source, source_id)
            if not source:
                logger.warning("Scheduled job source not found, skipping")
                return
            if getattr(source, "location_type", "local") != "agent" and lock is None:
                lock = get_source_lock(source_id)
                lock_acquired = lock.acquire(blocking=False)
                if not lock_acquired:
                    logger.warning(f"Skipping scheduled index for '{source_id}' - already running")
                    return
            loop = asyncio.new_event_loop()
            try:
                result = loop.run_until_complete(
                    ScanDispatcher(db, meili_service).dispatch(source_id, "schedule")
                )
            except (RemoteAgentsDisabledError, AgentUnavailableError):
                logger.info("Scheduled remote dispatch unavailable for source '%s'", source_id)
                return
            finally:
                loop.close()
            job = self.scheduler.get_job(f"index-{source_id}")
            if job and job.next_run_time:
                source.next_scan_at = job.next_run_time.replace(tzinfo=None)
            if getattr(source, "location_type", "local") != "agent":
                source.last_scan_at = datetime.now(timezone.utc).replace(tzinfo=None)
                logger.info(
                    f"Scheduled indexing complete for '{source.name}': {result.successful} indexed, {result.failed} failed"
                )
            db.commit()
        finally:
            if lock is not None and lock_acquired:
                lock.release()
            db.close()

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
