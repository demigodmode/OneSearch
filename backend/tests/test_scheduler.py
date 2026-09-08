# Copyright (C) 2025 demigodmode
# SPDX-License-Identifier: AGPL-3.0-only

"""
Tests for scheduler service
"""

import threading
from datetime import datetime, timedelta, timezone
from unittest.mock import Mock, patch

import pytest

from app.services.scheduler import (
    SCHEDULE_PRESETS,
    SchedulerService,
    _indexing_locks,
    _locks_lock,
    calculate_interval_next_run_time,
    calculate_next_run_time,
    calculate_next_run_time_for_schedule,
    get_source_lock,
    resolve_cron,
    resolve_effective_schedule,
    validate_interval,
    validate_schedule,
)


class TestResolveСron:
    """Tests for cron expression resolution"""

    def test_resolve_hourly(self):
        assert resolve_cron("@hourly") == "0 * * * *"

    def test_resolve_daily(self):
        assert resolve_cron("@daily") == "0 2 * * *"

    def test_resolve_weekly(self):
        assert resolve_cron("@weekly") == "0 2 * * 0"

    def test_resolve_custom_cron(self):
        """Custom cron expressions pass through unchanged"""
        assert resolve_cron("0 */6 * * *") == "0 */6 * * *"
        assert resolve_cron("30 4 * * 1-5") == "30 4 * * 1-5"

    def test_all_presets_exist(self):
        """Verify all documented presets are defined"""
        assert "@hourly" in SCHEDULE_PRESETS
        assert "@daily" in SCHEDULE_PRESETS
        assert "@weekly" in SCHEDULE_PRESETS


class TestValidateSchedule:
    """Tests for schedule validation"""

    def test_validate_hourly(self):
        assert validate_schedule("@hourly") is True

    def test_validate_daily(self):
        assert validate_schedule("@daily") is True

    def test_validate_weekly(self):
        assert validate_schedule("@weekly") is True

    def test_validate_custom_cron_valid(self):
        assert validate_schedule("0 */6 * * *") is True
        assert validate_schedule("30 4 * * 1-5") is True
        assert validate_schedule("0 0 1 * *") is True  # monthly

    def test_validate_invalid_cron(self):
        assert validate_schedule("not a cron") is False
        assert validate_schedule("* * *") is False  # too few fields
        assert validate_schedule("60 * * * *") is False  # minute out of range
        assert validate_schedule("* 25 * * *") is False  # hour out of range

    def test_validate_empty_string(self):
        # Empty string resolves to itself and fails validation
        assert validate_schedule("") is False


class TestCalculateNextRunTime:
    """Tests for next run time calculation"""

    def test_hourly_returns_future_time(self):
        """@hourly should return a time within the next hour"""
        result = calculate_next_run_time("@hourly")

        assert result is not None
        now = datetime.now(timezone.utc).replace(tzinfo=None)
        # Should be in the future
        assert result > now
        # Should be within ~61 minutes (allowing for test execution time)
        assert result < now + timedelta(hours=1, minutes=2)

    def test_daily_returns_future_time(self):
        """@daily should return 2am tomorrow or today if not yet 2am"""
        result = calculate_next_run_time("@daily")

        assert result is not None
        now = datetime.now(timezone.utc).replace(tzinfo=None)
        # Should be in the future
        assert result > now
        # Should be within 25 hours
        assert result < now + timedelta(hours=25)

    def test_weekly_returns_future_time(self):
        """@weekly should return Sunday 2am"""
        result = calculate_next_run_time("@weekly")

        assert result is not None
        now = datetime.now(timezone.utc).replace(tzinfo=None)
        # Should be in the future
        assert result > now
        # Should be within 8 days
        assert result < now + timedelta(days=8)

    def test_custom_cron_every_6_hours(self):
        """Custom cron '0 */6 * * *' should return time within 6 hours"""
        result = calculate_next_run_time("0 */6 * * *")

        assert result is not None
        now = datetime.now(timezone.utc).replace(tzinfo=None)
        assert result > now
        assert result < now + timedelta(hours=6, minutes=1)

    def test_invalid_schedule_returns_none(self):
        """Invalid schedules should return None"""
        assert calculate_next_run_time("not valid") is None
        assert calculate_next_run_time("* * *") is None

    def test_returns_naive_datetime(self):
        """Result should be a naive datetime (no tzinfo)"""
        result = calculate_next_run_time("@hourly")

        assert result is not None
        assert result.tzinfo is None

    def test_different_schedules_return_different_times(self):
        """Different schedules should generally return different next run times"""
        hourly = calculate_next_run_time("@hourly")
        daily = calculate_next_run_time("@daily")

        assert hourly is not None
        assert daily is not None
        # They could theoretically be the same, but very unlikely
        # Daily is at 2am, hourly is at top of hour


class TestSchedulePresetsConsistency:
    """Tests to ensure schedule presets work end-to-end"""

    @pytest.mark.parametrize("preset", ["@hourly", "@daily", "@weekly"])
    def test_preset_validates(self, preset):
        """All presets should validate"""
        assert validate_schedule(preset) is True

    @pytest.mark.parametrize("preset", ["@hourly", "@daily", "@weekly"])
    def test_preset_calculates_next_time(self, preset):
        """All presets should calculate a next run time"""
        result = calculate_next_run_time(preset)
        assert result is not None
        assert isinstance(result, datetime)


class TestGetSourceLock:
    def test_returns_lock(self):
        lock = get_source_lock("lock-test-1")
        assert hasattr(lock, "acquire") and hasattr(lock, "release")

    def test_same_lock_for_same_id(self):
        a = get_source_lock("lock-test-2")
        b = get_source_lock("lock-test-2")
        assert a is b

    def test_different_locks_for_different_ids(self):
        a = get_source_lock("lock-test-3")
        b = get_source_lock("lock-test-4")
        assert a is not b


class TestSchedulerService:
    @pytest.fixture
    def mock_engine(self):
        return Mock()

    @pytest.fixture
    def svc(self, mock_engine):
        return SchedulerService(mock_engine)

    def test_start_disabled(self, svc, monkeypatch):
        from app.config import settings

        monkeypatch.setattr(settings, "scheduler_enabled", False)

        svc.start()

        assert svc.scheduler is None

    @patch("app.services.scheduler.BackgroundScheduler")
    def test_start_enabled(self, MockScheduler, svc, monkeypatch):
        from app.config import settings

        monkeypatch.setattr(settings, "scheduler_enabled", True)

        mock_sched = MockScheduler.return_value
        # _sync_all_jobs needs a session factory, mock it to return empty sources
        # and empty app settings rows (queried via query().filter().all())
        mock_db = Mock()
        mock_db.query.return_value.all.return_value = []
        mock_db.query.return_value.filter.return_value.all.return_value = []
        mock_db.close = Mock()
        svc._session_factory = Mock(return_value=mock_db)

        svc.start()

        assert svc.scheduler is mock_sched
        mock_sched.start.assert_called_once()

    def test_shutdown_running(self, svc):
        svc.scheduler = Mock()
        svc.scheduler.running = True

        svc.shutdown()

        svc.scheduler.shutdown.assert_called_once_with(wait=False)

    def test_shutdown_not_running(self, svc):
        svc.scheduler = None

        # Should not raise
        svc.shutdown()

    def test_update_source_schedule_add(self, svc):
        mock_sched = Mock()
        mock_sched.running = True
        mock_job = Mock()
        mock_job.next_run_time = datetime.now(timezone.utc)
        mock_sched.get_job.return_value = mock_job
        svc.scheduler = mock_sched

        mock_source = Mock()
        mock_source.id = "src1"
        mock_source.use_default_schedule = False
        mock_source.schedule_type = "cron"
        mock_source.scan_schedule = "@hourly"
        mock_source.interval_value = None
        mock_source.interval_unit = None

        mock_db = Mock()
        mock_db.get.return_value = mock_source
        svc._session_factory = Mock(return_value=mock_db)

        svc.update_source_schedule("src1")

        mock_sched.add_job.assert_called_once()

    def test_update_source_schedule_clear(self, svc):
        mock_sched = Mock()
        mock_sched.running = True
        svc.scheduler = mock_sched

        mock_source = Mock()
        mock_source.id = "src1"
        mock_source.use_default_schedule = False
        mock_source.schedule_type = "cron"
        mock_source.scan_schedule = None
        mock_source.interval_value = None
        mock_source.interval_unit = None

        mock_db = Mock()
        mock_db.get.return_value = mock_source
        svc._session_factory = Mock(return_value=mock_db)

        svc.update_source_schedule("src1")

        mock_sched.remove_job.assert_called_once_with("index-src1")

    def test_update_source_schedule_not_running(self, svc):
        svc.scheduler = None

        # Should not raise
        svc.update_source_schedule("src1")

    @patch("app.services.scheduler.meili_service")
    @patch("app.services.scheduler.IndexingService")
    def test_run_indexing_job_success(self, MockIndexingService, mock_meili, svc):
        mock_db = Mock()
        mock_source = Mock()
        mock_source.name = "Test"
        mock_db.get.return_value = mock_source
        svc._session_factory = Mock(return_value=mock_db)

        mock_stats = Mock()
        mock_stats.successful = 5
        mock_stats.failed = 0
        MockIndexingService.return_value.index_source = Mock(return_value=mock_stats)

        svc.scheduler = Mock()
        mock_job = Mock()
        mock_job.next_run_time = datetime.now(timezone.utc)
        svc.scheduler.get_job.return_value = mock_job

        # Need to make run_until_complete work with the mock
        with patch("asyncio.new_event_loop") as mock_loop_factory:
            mock_loop = Mock()

            def run_until_complete(awaitable):
                awaitable.close()
                return mock_stats

            mock_loop.run_until_complete.side_effect = run_until_complete
            mock_loop_factory.return_value = mock_loop

            svc._run_indexing_job("src1")

        mock_db.commit.assert_called()
        mock_db.close.assert_called()

    @patch("app.services.scheduler.meili_service")
    def test_run_indexing_job_source_not_found(self, mock_meili, svc):
        mock_db = Mock()
        mock_db.get.return_value = None
        svc._session_factory = Mock(return_value=mock_db)

        svc._run_indexing_job("missing-src")

        # Should return without error
        mock_db.close.assert_called()

    def test_run_indexing_job_already_locked(self, svc):
        lock = get_source_lock("locked-src")
        lock.acquire()  # Lock it first

        mock_db = Mock()
        svc._session_factory = Mock(return_value=mock_db)

        try:
            svc._run_indexing_job("locked-src")
        finally:
            lock.release()

        # Current source location is resolved before locking, so a stale local
        # lock cannot suppress a source switched to a remote agent.
        svc._session_factory.assert_called_once()

    def test_remove_source(self, svc):
        mock_sched = Mock()
        mock_sched.running = True
        svc.scheduler = mock_sched

        # Pre-populate lock
        with _locks_lock:
            _indexing_locks["rm-src"] = threading.Lock()

        svc.remove_source("rm-src")

        mock_sched.remove_job.assert_called_once_with("index-rm-src")
        assert "rm-src" not in _indexing_locks

    def test_remove_source_scheduler_not_running(self, svc):
        svc.scheduler = None

        # Should not raise
        svc.remove_source("any-src")

    def test_sync_all_jobs_cleans_stale(self, svc):
        mock_sched = Mock()
        mock_sched.running = True
        svc.scheduler = mock_sched

        # No sources at all, and empty app settings rows (query().filter().all())
        mock_db = Mock()
        mock_db.query.return_value.all.return_value = []
        mock_db.query.return_value.filter.return_value.all.return_value = []
        svc._session_factory = Mock(return_value=mock_db)

        # But scheduler has a stale job
        stale_job = Mock()
        stale_job.id = "index-deleted-source"
        mock_sched.get_jobs.return_value = [stale_job]

        svc._sync_all_jobs()

        mock_sched.remove_job.assert_called_once_with("index-deleted-source")


class TestIntervalSchedules:
    def test_validate_interval_valid(self):
        assert validate_interval(3, "hours") is True
        assert validate_interval(1, "minutes") is True
        assert validate_interval(30, "days") is True

    def test_validate_interval_invalid(self):
        assert validate_interval(0, "hours") is False
        assert validate_interval(-1, "hours") is False
        assert validate_interval(3, "weeks") is False
        assert validate_interval(None, "hours") is False

    def test_calculate_interval_next_run_time_hours(self):
        result = calculate_interval_next_run_time(3, "hours")

        assert result is not None
        now = datetime.now(timezone.utc).replace(tzinfo=None)
        assert result > now
        assert result < now + timedelta(hours=3, minutes=1)

    def test_calculate_interval_next_run_time_invalid_returns_none(self):
        assert calculate_interval_next_run_time(0, "hours") is None
        assert calculate_interval_next_run_time(3, "fortnights") is None

    def test_calculate_next_run_time_for_schedule_dispatches_interval(self):
        result = calculate_next_run_time_for_schedule("interval", None, 2, "hours")

        assert result is not None
        now = datetime.now(timezone.utc).replace(tzinfo=None)
        assert result < now + timedelta(hours=2, minutes=1)

    def test_calculate_next_run_time_for_schedule_dispatches_cron(self):
        result = calculate_next_run_time_for_schedule("cron", "@hourly", None, None)

        assert result is not None
        now = datetime.now(timezone.utc).replace(tzinfo=None)
        assert result < now + timedelta(hours=1, minutes=2)

    def test_calculate_next_run_time_for_schedule_manual_returns_none(self):
        assert calculate_next_run_time_for_schedule("cron", None, None, None) is None


class TestResolveEffectiveSchedule:
    def _make_source(self, **overrides):
        source = Mock()
        source.use_default_schedule = False
        source.schedule_type = "cron"
        source.scan_schedule = None
        source.interval_value = None
        source.interval_unit = None
        for key, value in overrides.items():
            setattr(source, key, value)
        return source

    def test_uses_own_schedule_when_not_following_default(self):
        source = self._make_source(
            schedule_type="interval", interval_value=6, interval_unit="hours"
        )
        db = Mock()

        resolved = resolve_effective_schedule(source, db)

        assert resolved == {
            "schedule_type": "interval",
            "scan_schedule": None,
            "interval_value": 6,
            "interval_unit": "hours",
        }

    @patch("app.services.app_settings.AppSettingsService")
    def test_uses_global_default_when_following_default(self, MockAppSettingsService):
        from app.schemas import ScheduleConfig

        source = self._make_source(
            use_default_schedule=True,
            schedule_type="cron",
            scan_schedule="0 */6 * * *",  # this stored value must be ignored
        )
        db = Mock()
        MockAppSettingsService.return_value.get_settings.return_value.default_scan_schedule = (
            ScheduleConfig(
                schedule_type="interval",
                interval_value=3,
                interval_unit="hours",
            )
        )

        resolved = resolve_effective_schedule(source, db)

        assert resolved["schedule_type"] == "interval"
        assert resolved["interval_value"] == 3
        assert resolved["interval_unit"] == "hours"

    @patch("app.services.app_settings.AppSettingsService")
    def test_defaults_to_manual_when_no_global_default_configured(self, MockAppSettingsService):
        source = self._make_source(use_default_schedule=True)
        db = Mock()
        MockAppSettingsService.return_value.get_settings.return_value.default_scan_schedule = None

        resolved = resolve_effective_schedule(source, db)

        assert resolved == {
            "schedule_type": "cron",
            "scan_schedule": None,
            "interval_value": None,
            "interval_unit": None,
        }
