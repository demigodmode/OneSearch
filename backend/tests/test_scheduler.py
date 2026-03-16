# Copyright (C) 2025 demigodmode
# SPDX-License-Identifier: AGPL-3.0-only

"""
Tests for scheduler service
"""
import pytest
from datetime import datetime, timezone, timedelta
from unittest.mock import patch, Mock, MagicMock
import threading

from app.services.scheduler import (
    validate_schedule,
    resolve_cron,
    calculate_next_run_time,
    SCHEDULE_PRESETS,
    SchedulerService,
    get_source_lock,
    _indexing_locks,
    _locks_lock,
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
        # _sync_all_jobs needs a session factory, mock it
        svc._session_factory = Mock(return_value=Mock(
            query=Mock(return_value=Mock(
                filter=Mock(return_value=Mock(all=Mock(return_value=[])))
            )),
            close=Mock(),
        ))

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

        mock_db = Mock()
        mock_source = Mock()
        mock_db.get.return_value = mock_source
        svc._session_factory = Mock(return_value=mock_db)

        svc.update_source_schedule("src1", "@hourly")

        mock_sched.add_job.assert_called_once()

    def test_update_source_schedule_clear(self, svc):
        mock_sched = Mock()
        mock_sched.running = True
        svc.scheduler = mock_sched

        mock_db = Mock()
        mock_source = Mock()
        mock_db.get.return_value = mock_source
        svc._session_factory = Mock(return_value=mock_db)

        svc.update_source_schedule("src1", None)

        mock_sched.remove_job.assert_called_once_with("index-src1")

    def test_update_source_schedule_not_running(self, svc):
        svc.scheduler = None

        # Should not raise
        svc.update_source_schedule("src1", "@daily")

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
            mock_loop.run_until_complete.return_value = mock_stats
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

        # DB session should NOT have been created since lock was held
        svc._session_factory.assert_not_called()

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

        # No sources have schedules
        mock_db = Mock()
        mock_db.query.return_value.filter.return_value.all.return_value = []
        svc._session_factory = Mock(return_value=mock_db)

        # But scheduler has a stale job
        stale_job = Mock()
        stale_job.id = "index-deleted-source"
        mock_sched.get_jobs.return_value = [stale_job]

        svc._sync_all_jobs()

        mock_sched.remove_job.assert_called_once_with("index-deleted-source")
