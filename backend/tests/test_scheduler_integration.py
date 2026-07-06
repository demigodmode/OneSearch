# Copyright (C) 2025 demigodmode
# SPDX-License-Identifier: AGPL-3.0-only

"""
Integration test for SchedulerService against a real APScheduler instance
and a real (temporary) database — no mocks. Closes out #99.
"""
from app.models import Source
from app.services.scheduler import SchedulerService


def test_scheduler_runs_interval_job_end_to_end(db_session, tmp_path):
    engine = db_session.get_bind()

    source = Source(
        id="integration-src",
        name="Integration Source",
        root_path=str(tmp_path),
        schedule_type="interval",
        interval_value=1,
        interval_unit="minutes",
        use_default_schedule=False,
    )
    db_session.add(source)
    db_session.commit()

    svc = SchedulerService(engine)
    svc.start()
    try:
        job = svc.scheduler.get_job("index-integration-src")
        assert job is not None
        assert job.next_run_time is not None

        db_session.refresh(source)
        assert source.next_scan_at is not None
    finally:
        svc.shutdown()


def test_scheduler_resync_on_default_schedule_change(db_session, tmp_path):
    from app.services.app_settings import AppSettingsService
    from app.schemas import AppSettingsUpdate, ScheduleConfig

    engine = db_session.get_bind()

    source = Source(
        id="integration-default-src",
        name="Follows Default",
        root_path=str(tmp_path),
        use_default_schedule=True,
    )
    db_session.add(source)
    db_session.commit()

    svc = SchedulerService(engine)
    svc.start()
    try:
        assert svc.scheduler.get_job("index-integration-default-src") is None  # no default set yet

        AppSettingsService(db_session).update_settings(AppSettingsUpdate(
            default_scan_schedule=ScheduleConfig(schedule_type="interval", interval_value=1, interval_unit="minutes"),
        ))
        svc.sync_default_schedule_sources()

        job = svc.scheduler.get_job("index-integration-default-src")
        assert job is not None
        assert job.next_run_time is not None
    finally:
        svc.shutdown()
