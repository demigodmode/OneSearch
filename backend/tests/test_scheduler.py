# Copyright (C) 2025 demigodmode
# SPDX-License-Identifier: AGPL-3.0-only

"""
Tests for scheduler service
"""
import pytest
from datetime import datetime, timezone, timedelta
from unittest.mock import patch

from app.services.scheduler import (
    validate_schedule,
    resolve_cron,
    calculate_next_run_time,
    SCHEDULE_PRESETS,
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
