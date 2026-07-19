# Copyright (C) 2025 demigodmode
# SPDX-License-Identifier: AGPL-3.0-only

"""Persistence contracts for remote indexing agents and their durable jobs."""

import json
import os
import sqlite3
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from sqlalchemy import create_engine, event, inspect
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker

from app.models import Agent, AgentBatch, AgentEnrollment, AgentJob, Base, IndexedFile, Source, User
from app.schemas import SourceCreate, SourceResponse, SourceUpdate


@pytest.fixture
def agent_db(tmp_path):
    database_path = tmp_path / "agents.db"
    engine = create_engine(f"sqlite:///{database_path.as_posix()}")

    @event.listens_for(engine, "connect")
    def _enable_foreign_keys(dbapi_connection, _connection_record):
        dbapi_connection.execute("PRAGMA foreign_keys=ON")

    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


def _agent(agent_id="agent-1"):
    return Agent(
        id=agent_id,
        name="NAS agent",
        platform="linux-amd64",
        version="1.0.0",
        protocol_version=1,
        allowed_roots=json.dumps([{"root_id": "media", "path": "/mnt/media"}]),
    )


def _remote_source(source_id="remote-1", agent_id="agent-1"):
    return Source(
        id=source_id,
        name="Remote files",
        root_path="/mnt/media",
        location_type="agent",
        agent_id=agent_id,
        processing_mode="on_agent",
    )


def test_agent_and_enrollment_persist_with_defaults(agent_db):
    user = User(username="admin", password_hash="hash")
    agent_db.add(user)
    agent_db.flush()
    enrollment = AgentEnrollment(
        id="enrollment-1",
        code_hash="a" * 64,
        expires_at=datetime.now(timezone.utc).replace(tzinfo=None) + timedelta(minutes=10),
        created_by_user_id=user.id,
    )
    agent = _agent()
    agent_db.add_all([agent, enrollment])
    agent_db.commit()

    agent_db.refresh(agent)
    assert json.loads(agent.allowed_roots) == [{"root_id": "media", "path": "/mnt/media"}]
    assert agent.default_processing_mode == "on_agent"
    assert agent.auto_update is False
    assert agent.status == "pending"
    assert agent.token_hash is None
    assert agent.approved_at is None
    assert agent.last_seen_at is None
    assert agent.disabled_at is None
    assert agent.created_at is not None
    assert agent.updated_at is not None
    assert enrollment.used_at is None


@pytest.mark.parametrize(
    ("source", "is_valid"),
    [
        (Source(id="local", name="Local", root_path="/data"), True),
        (Source(id="bad-local", name="Bad", root_path="/data", agent_id="agent-1"), False),
        (
            Source(
                id="bad-local-processing",
                name="Bad local processing",
                root_path="/data",
                processing_mode="on_server",
            ),
            False,
        ),
        (_remote_source(), True),
        (
            Source(
                id="remote-server",
                name="Remote server processing",
                root_path="/mnt/media",
                location_type="agent",
                agent_id="agent-1",
                processing_mode="on_server",
            ),
            True,
        ),
        (Source(id="bad-agent", name="Bad", root_path="/data", location_type="agent"), False),
    ],
)
def test_source_location_requires_matching_agent_reference(agent_db, source, is_valid):
    agent_db.add(_agent())
    agent_db.commit()
    agent_db.add(source)

    if is_valid:
        agent_db.commit()
        assert agent_db.get(Source, source.id) is not None
    else:
        with pytest.raises(IntegrityError):
            agent_db.commit()


@pytest.mark.parametrize(
    ("field", "value"),
    [("location_type", "cloud"), ("processing_mode", "elsewhere")],
)
def test_source_rejects_unknown_location_and_processing_modes(agent_db, field, value):
    source = Source(id="invalid", name="Invalid", root_path="/data")
    setattr(source, field, value)
    agent_db.add(source)

    with pytest.raises(IntegrityError):
        agent_db.commit()


def test_agent_rejects_unknown_default_processing_mode(agent_db):
    agent = _agent()
    agent.default_processing_mode = "elsewhere"
    agent_db.add(agent)

    with pytest.raises(IntegrityError):
        agent_db.commit()


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("kind", "unknown"),
        ("status", "unknown"),
        ("status", "leased"),
        ("processing_mode", "elsewhere"),
    ],
)
def test_agent_job_rejects_unknown_contract_values(agent_db, field, value):
    agent_db.add(_agent())
    agent_db.commit()
    job = AgentJob(id="invalid", agent_id="agent-1", kind="browse")
    setattr(job, field, value)
    agent_db.add(job)

    with pytest.raises(IntegrityError):
        agent_db.commit()


@pytest.mark.parametrize("status", ["claimed", "cancelling", "completed"])
def test_agent_job_accepts_planned_lifecycle_statuses(agent_db, status):
    agent_db.add(_agent())
    agent_db.commit()
    agent_db.add(AgentJob(id=f"job-{status}", agent_id="agent-1", kind="browse", status=status))

    agent_db.commit()


def test_agent_job_defaults_foreign_keys_and_active_key_uniqueness(agent_db):
    agent_db.add(_agent())
    agent_db.flush()
    source = _remote_source()
    agent_db.add(source)
    agent_db.flush()
    job = AgentJob(
        id="job-1",
        agent_id="agent-1",
        source_id=source.id,
        kind="scan",
        active_key="scan:remote-1",
    )
    agent_db.add(job)
    agent_db.commit()
    agent_db.refresh(job)

    assert job.status == "pending"
    assert json.loads(job.payload) == {}
    assert json.loads(job.checkpoint) == {}
    assert job.progress_current == 0
    assert job.progress_total is None
    assert job.attempts == 0
    assert job.processing_mode is None

    agent_db.add(
        AgentJob(
            id="job-2",
            agent_id="agent-1",
            source_id=source.id,
            kind="scan",
            active_key="scan:remote-1",
        )
    )
    with pytest.raises(IntegrityError):
        agent_db.commit()


def test_browse_job_can_exist_without_source_and_rejects_missing_agent(agent_db):
    agent_db.add(_agent())
    agent_db.commit()
    agent_db.add(AgentJob(id="browse-1", agent_id="agent-1", kind="browse"))
    agent_db.commit()

    agent_db.add(AgentJob(id="orphan", agent_id="missing", kind="browse"))
    with pytest.raises(IntegrityError):
        agent_db.commit()


def test_agent_job_source_must_belong_to_the_same_agent(agent_db):
    agent_db.add_all([_agent("agent-1"), _agent("agent-2")])
    agent_db.flush()
    agent_db.add(_remote_source(agent_id="agent-1"))
    agent_db.commit()

    agent_db.add(
        AgentJob(
            id="wrong-agent",
            agent_id="agent-2",
            source_id="remote-1",
            kind="scan",
        )
    )
    with pytest.raises(IntegrityError):
        agent_db.commit()


def test_agent_job_source_accepts_matching_agent(agent_db):
    agent_db.add(_agent())
    agent_db.flush()
    agent_db.add(_remote_source())
    agent_db.flush()
    agent_db.add(
        AgentJob(id="matching-agent", agent_id="agent-1", source_id="remote-1", kind="scan")
    )

    agent_db.commit()


def test_agent_job_query_indexes_are_declared(agent_db):
    indexes = {index["name"]: index["column_names"] for index in inspect(agent_db.bind).get_indexes("agent_jobs")}

    assert indexes["ix_agent_jobs_agent_status_created"] == ["agent_id", "status", "created_at"]
    assert indexes["ix_agent_jobs_status_lease_expires"] == ["status", "lease_expires_at"]


def test_agent_batch_is_idempotent_per_job(agent_db):
    agent_db.add(_agent())
    agent_db.flush()
    agent_db.add(AgentJob(id="job-1", agent_id="agent-1", kind="browse"))
    agent_db.flush()
    agent_db.add(AgentBatch(job_id="job-1", idempotency_key="batch-1", checksum="b" * 64))
    agent_db.commit()

    agent_db.add(AgentBatch(job_id="job-1", idempotency_key="batch-1", checksum="c" * 64))
    with pytest.raises(IntegrityError):
        agent_db.commit()


@pytest.mark.parametrize("load_relationships", [False, True])
def test_deleting_source_cascades_jobs_batches_and_indexed_rows(agent_db, load_relationships):
    agent_db.add(_agent())
    agent_db.flush()
    source = _remote_source()
    agent_db.add(source)
    agent_db.flush()
    job = AgentJob(id="job-1", agent_id="agent-1", source_id=source.id, kind="scan")
    agent_db.add_all(
        [job, IndexedFile(source_id=source.id, path="file.txt", status="success")]
    )
    agent_db.flush()
    agent_db.add(AgentBatch(job_id=job.id, idempotency_key="batch-1", checksum="a" * 64))
    agent_db.commit()

    if load_relationships:
        assert source.agent_jobs == [job]
        assert job.batches

    agent_db.delete(source)
    agent_db.commit()

    assert agent_db.query(AgentJob).count() == 0
    assert agent_db.query(AgentBatch).count() == 0
    assert agent_db.query(IndexedFile).count() == 0


@pytest.mark.parametrize("load_relationships", [False, True])
def test_deleting_agent_cascades_remote_sources_and_their_dependents(agent_db, load_relationships):
    agent = _agent()
    source = _remote_source()
    agent_db.add(agent)
    agent_db.flush()
    agent_db.add(source)
    agent_db.flush()
    job = AgentJob(id="job-1", agent_id=agent.id, source_id=source.id, kind="scan")
    agent_db.add_all([job, IndexedFile(source_id=source.id, path="file.txt")])
    agent_db.flush()
    agent_db.add(AgentBatch(job_id=job.id, idempotency_key="batch-1", checksum="a" * 64))
    agent_db.commit()

    if load_relationships:
        assert agent.sources == [source]
        assert agent.jobs == [job]
        assert source.agent_jobs == [job]
        assert job.batches

    agent_db.delete(agent)
    agent_db.commit()

    assert agent_db.query(Source).count() == 0
    assert agent_db.query(AgentJob).count() == 0
    assert agent_db.query(AgentBatch).count() == 0
    assert agent_db.query(IndexedFile).count() == 0


def test_source_schemas_keep_local_defaults_and_serialize_remote_fields(agent_db):
    local = Source(id="local", name="Local", root_path="/data", scan_schedule="@daily")
    agent_db.add_all([_agent(), local])
    agent_db.flush()
    remote = _remote_source()
    agent_db.add(remote)
    agent_db.commit()

    local_response = SourceResponse.from_orm_model(local)
    remote_response = SourceResponse.from_orm_model(remote)
    assert local_response.location_type == "local"
    assert local_response.agent_id is None
    assert local_response.processing_mode is None
    assert local_response.scan_schedule == "@daily"
    assert remote_response.location_type == "agent"
    assert remote_response.agent_id == "agent-1"
    assert remote_response.processing_mode == "on_agent"
    assert SourceCreate(name="Local", root_path="/data").location_type == "local"
    assert SourceUpdate().model_dump(exclude_unset=True) == {}


def test_migration_is_head_and_round_trips_only_a_temporary_database(tmp_path):
    backend_dir = Path(__file__).resolve().parents[1]
    database_path = tmp_path / "migration-round-trip.db"
    database_url = f"sqlite:///{database_path.as_posix()}"
    env = os.environ.copy()
    env["DATABASE_URL"] = database_url

    def alembic(*args):
        subprocess.run(
            [sys.executable, "-m", "alembic", "-c", "alembic.ini", *args],
            cwd=backend_dir,
            env=env,
            check=True,
            capture_output=True,
            text=True,
        )

    alembic("upgrade", "361d2b460314")
    with sqlite3.connect(database_path) as connection:
        connection.execute(
            "INSERT INTO sources (id, name, root_path, created_at, updated_at) "
            "VALUES ('existing', 'Existing', '/data', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
        )
        connection.commit()

    alembic("upgrade", "head")
    alembic("check")
    with sqlite3.connect(database_path) as connection:
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute(
            "INSERT INTO agents "
            "(id, name, platform, version, protocol_version, created_at, updated_at) "
            "VALUES ('agent-1', 'Agent', 'linux', '1.0.0', 1, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
        )
        connection.execute(
            "INSERT INTO agents "
            "(id, name, platform, version, protocol_version, created_at, updated_at) "
            "VALUES ('agent-2', 'Agent 2', 'linux', '1.0.0', 1, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
        )
        connection.execute(
            "INSERT INTO sources "
            "(id, name, root_path, location_type, agent_id, processing_mode, created_at, updated_at) "
            "VALUES ('remote', 'Remote', '/data', 'agent', 'agent-1', 'on_agent', "
            "CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
        )
        connection.execute(
            "INSERT INTO agent_jobs (id, agent_id, source_id, kind, created_at) "
            "VALUES ('job-matching', 'agent-1', 'remote', 'scan', CURRENT_TIMESTAMP)"
        )
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(
                "INSERT INTO agent_jobs (id, agent_id, source_id, kind, created_at) "
                "VALUES ('job-mismatch', 'agent-2', 'remote', 'scan', CURRENT_TIMESTAMP)"
            )
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(
                "UPDATE sources SET processing_mode='on_server' WHERE id='existing'"
            )
        for status in ("claimed", "cancelling"):
            connection.execute(
                "INSERT INTO agent_jobs (id, agent_id, kind, status, created_at) "
                "VALUES (?, 'agent-1', 'browse', ?, CURRENT_TIMESTAMP)",
                (f"job-{status}", status),
            )
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(
                "INSERT INTO agent_jobs (id, agent_id, kind, status, created_at) "
                "VALUES ('job-leased', 'agent-1', 'browse', 'leased', CURRENT_TIMESTAMP)"
            )
        row = connection.execute(
            "SELECT location_type, agent_id, processing_mode FROM sources WHERE id='existing'"
        ).fetchone()
        revision = connection.execute("SELECT version_num FROM alembic_version").fetchone()[0]
        index_names = {
            index[1] for index in connection.execute("PRAGMA index_list('agent_jobs')").fetchall()
        }
    assert row == ("local", None, None)
    assert revision == "a91c5e7d2f40"
    assert "ix_agent_jobs_agent_status_created" in index_names
    assert "ix_agent_jobs_status_lease_expires" in index_names

    alembic("downgrade", "361d2b460314")
    alembic("upgrade", "head")
    alembic("check")
    with sqlite3.connect(database_path) as connection:
        revision = connection.execute("SELECT version_num FROM alembic_version").fetchone()[0]
    assert revision == "a91c5e7d2f40"
