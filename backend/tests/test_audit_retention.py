# Copyright (C) 2026 demigodmode
# SPDX-License-Identifier: AGPL-3.0-only

from datetime import datetime, timedelta
from unittest.mock import Mock, patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.config import settings
from app.models import AuditEvent, _utcnow
from app.services.audit_retention import purge_old_audit_events
from app.services.scheduler import SchedulerService, build_cron_trigger

NOW = datetime(2026, 11, 2, 12, 0, 0)


def _add_event(
    db_session: Session,
    age_days: int,
    now: datetime = NOW,
    action: str = "auth.login",
    label: str = "alice",
) -> None:
    db_session.add(
        AuditEvent(
            created_at=now - timedelta(days=age_days),
            action=action,
            actor_username=label,
        )
    )
    db_session.commit()


def _set_retention(client: TestClient, db_session: Session, days: int) -> None:
    assert client.put("/api/settings", json={"audit_retention_days": days}).status_code == 200
    db_session.query(AuditEvent).delete()
    db_session.commit()


def _remaining_ages(db_session: Session) -> list[int]:
    return sorted((NOW - row.created_at).days for row in db_session.query(AuditEvent).all())


def test_default_retention_is_90_days(client):
    response = client.get("/api/settings")

    assert response.json()["audit_retention_days"] == 90


def test_purge_removes_only_entries_older_than_the_default(client, db_session):
    _add_event(db_session, 89)
    _add_event(db_session, 91)
    _add_event(db_session, 400)

    removed = purge_old_audit_events(db_session, NOW)

    assert removed == 2
    assert _remaining_ages(db_session) == [89]


def test_purge_keeps_recent_entries_when_nothing_is_old(client, db_session):
    _add_event(db_session, 1)
    _add_event(db_session, 30)

    assert purge_old_audit_events(db_session, NOW) == 0
    assert _remaining_ages(db_session) == [1, 30]


def test_purge_keeps_an_entry_exactly_at_the_cutoff(client, db_session):
    _add_event(db_session, 90)
    _add_event(db_session, 91)

    assert purge_old_audit_events(db_session, NOW) == 1
    assert _remaining_ages(db_session) == [90]


def test_purge_deletes_in_batches(client, db_session):
    db_session.add_all(
        AuditEvent(
            created_at=NOW - timedelta(days=200), action="auth.login", actor_username="alice"
        )
        for _ in range(2500)
    )
    db_session.commit()
    _add_event(db_session, 1)

    assert purge_old_audit_events(db_session, NOW) == 2500
    assert _remaining_ages(db_session) == [1]


def test_purge_batch_size_does_not_change_which_entries_go(client, db_session):
    _add_event(db_session, 200)
    _add_event(db_session, 100)
    _add_event(db_session, 5)

    assert purge_old_audit_events(db_session, NOW, batch_size=1) == 2
    assert _remaining_ages(db_session) == [5]


def test_purge_uses_the_retention_setting(client, db_session):
    _set_retention(client, db_session, 30)
    _add_event(db_session, 20)
    _add_event(db_session, 40)

    removed = purge_old_audit_events(db_session, NOW)

    assert removed == 1
    assert _remaining_ages(db_session) == [20]


def test_a_longer_retention_keeps_more_entries(client, db_session):
    _set_retention(client, db_session, 365)
    _add_event(db_session, 200)

    assert purge_old_audit_events(db_session, NOW) == 0
    assert _remaining_ages(db_session) == [200]


def test_purge_does_not_audit_itself(client, db_session):
    _add_event(db_session, 500, action="auth.login_failed")

    purge_old_audit_events(db_session, NOW)

    assert db_session.query(AuditEvent).count() == 0


def test_retention_setting_accepts_the_bounds(client):
    assert client.put("/api/settings", json={"audit_retention_days": 1}).status_code == 200
    assert client.put("/api/settings", json={"audit_retention_days": 3650}).status_code == 200
    assert client.get("/api/settings").json()["audit_retention_days"] == 3650


@pytest.mark.parametrize("days", [0, -1, 3651])
def test_retention_setting_rejects_values_outside_the_bounds(client, days):
    assert client.put("/api/settings", json={"audit_retention_days": days}).status_code == 422
    assert client.get("/api/settings").json()["audit_retention_days"] == 90


def test_retention_setting_must_be_a_whole_number(client):
    assert client.put("/api/settings", json={"audit_retention_days": 30.5}).status_code == 422


def test_scheduler_job_runs_the_purge_as_of_now(db_session):
    _add_event(db_session, 120)
    _add_event(db_session, 2)
    service = SchedulerService(db_session.get_bind())

    service._purge_audit_log(NOW)

    assert _remaining_ages(db_session) == [2]


def test_startup_purges_even_when_the_scheduler_is_disabled(db_session, monkeypatch):
    monkeypatch.setattr(settings, "scheduler_enabled", False)
    _add_event(db_session, 120, now=_utcnow())
    _add_event(db_session, 2, now=_utcnow())

    SchedulerService(db_session.get_bind()).start()

    assert db_session.query(AuditEvent).count() == 1


def test_startup_purge_failure_is_logged_and_does_not_stop_startup(db_session, monkeypatch):
    monkeypatch.setattr(settings, "scheduler_enabled", False)

    def fail(*_args, **_kwargs):
        raise RuntimeError("database is locked")

    monkeypatch.setattr("app.services.scheduler.purge_old_audit_events", fail)

    SchedulerService(db_session.get_bind()).start()


@patch("app.services.scheduler.BackgroundScheduler")
def test_scheduler_registers_a_daily_audit_retention_job(mock_scheduler_class, monkeypatch):
    monkeypatch.setattr(settings, "scheduler_enabled", True)
    mock_db = Mock()
    mock_db.query.return_value.all.return_value = []
    mock_db.query.return_value.filter.return_value.all.return_value = []
    service = SchedulerService(Mock())
    service._session_factory = Mock(return_value=mock_db)

    service.start()

    calls = mock_scheduler_class.return_value.add_job.call_args_list
    jobs = [call.kwargs for call in calls if call.kwargs.get("id") == "audit-retention"]
    assert len(jobs) == 1
    assert jobs[0]["func"] == service._purge_audit_log
    assert jobs[0]["replace_existing"] is True
    assert str(jobs[0]["trigger"]) == str(build_cron_trigger("17 3 * * *"))


def test_app_startup_in_tests_never_purges_the_configured_database(monkeypatch):
    from fastapi.testclient import TestClient

    from app.main import app

    calls = []
    monkeypatch.setattr(
        "app.services.scheduler.purge_old_audit_events",
        lambda *args, **kwargs: calls.append(args) or 0,
    )

    with TestClient(app):
        pass

    assert calls == []
