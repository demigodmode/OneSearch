import json
import os
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest
from sqlalchemy import create_engine, event, inspect
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker

from app import models


@pytest.fixture
def staging_db(tmp_path):
    database = tmp_path / "scan-staging.db"
    engine = create_engine(f"sqlite:///{database.as_posix()}")

    @event.listens_for(engine, "connect")
    def _enable_foreign_keys(connection, _record):
        connection.execute("PRAGMA foreign_keys=ON")

    models.Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


def _add_scan_job(session, job_id="job-1"):
    agent = session.get(models.Agent, "agent-1")
    if agent is None:
        agent = models.Agent(
            id="agent-1",
            name="Agent",
            platform="linux",
            version="1.4.0",
            protocol_version=3,
            allowed_roots=json.dumps([{"root_id": "docs", "path": "/data"}]),
        )
        session.add(agent)
        session.flush()
    source = session.get(models.Source, "source-1")
    if source is None:
        source = models.Source(
            id="source-1",
            name="Docs",
            root_path="/data",
            location_type="agent",
            agent_id=agent.id,
            processing_mode="on_agent",
        )
        session.add(source)
        session.flush()
    job = models.AgentJob(
        id=job_id,
        agent_id=agent.id,
        source_id=source.id,
        kind="scan",
        processing_mode="on_agent",
    )
    session.add(job)
    session.flush()
    return job


def _page(job_id="job-1", sequence=0, **overrides):
    values = {
        "job_id": job_id,
        "sequence": sequence,
        "checksum": "a" * 64,
        "cursor": f"page:{sequence + 1}",
        "scanned_count": sequence + 1,
        "is_final": False,
        "entry_count": 1,
    }
    values.update(overrides)
    return models.AgentScanPage(**values)


def _entry(job_id="job-1", page_sequence=0, path="a.txt", **overrides):
    values = {
        "job_id": job_id,
        "page_sequence": page_sequence,
        "path": path,
        "path_hash": "b" * 64,
        "size_bytes": 1,
        "modified_at_ns": 2,
        "needs_processing": True,
    }
    values.update(overrides)
    return models.AgentScanEntry(**values)


def test_scan_staging_persists_pages_entries_and_settlement_state(staging_db):
    job = _add_scan_job(staging_db)
    page = _page(is_final=True, outcome_checksum="c" * 64)
    entry = _entry(outcome_status="failed", failure_error="extract failed")
    staging_db.add_all([page, entry])
    staging_db.commit()

    staging_db.refresh(page)
    staging_db.refresh(entry)
    assert page.job is job
    assert page.entries == [entry]
    assert entry.page is page
    assert page.accepted_at is not None
    assert page.settled_at is None


def test_scan_staging_rejects_duplicate_page_sequences_and_paths(staging_db):
    _add_scan_job(staging_db)
    staging_db.add(_page())
    staging_db.commit()

    staging_db.add(_page(checksum="c" * 64))
    with pytest.raises(IntegrityError):
        staging_db.commit()
    staging_db.rollback()

    staging_db.add_all([_page(sequence=1), _entry(), _entry(page_sequence=1)])
    with pytest.raises(IntegrityError):
        staging_db.commit()


@pytest.mark.parametrize(
    ("page_overrides", "entry_overrides"),
    [
        ({"sequence": -1}, {}),
        ({"scanned_count": -1}, {}),
        ({"entry_count": -1}, {}),
        ({"checksum": "A" * 64}, {}),
        ({"outcome_checksum": "A" * 64}, {}),
        ({}, {"path_hash": "B" * 64}),
        ({}, {"size_bytes": -1}),
        ({}, {"modified_at_ns": -1}),
        ({}, {"outcome_status": "failed", "failure_error": None}),
        ({}, {"outcome_status": "indexed", "failure_error": "unexpected"}),
        ({}, {"outcome_status": None, "failure_error": "unexpected"}),
    ],
)
def test_scan_staging_rejects_invalid_checksums_counts_and_outcomes(
    staging_db, page_overrides, entry_overrides
):
    _add_scan_job(staging_db)
    staging_db.add(_page(**page_overrides))
    if not page_overrides:
        staging_db.add(_entry(**entry_overrides))

    with pytest.raises(IntegrityError):
        staging_db.commit()


def test_scan_staging_declares_bounded_lookup_indexes(staging_db):
    page_indexes = {
        item["name"]: item["column_names"]
        for item in inspect(staging_db.bind).get_indexes("agent_scan_pages")
    }
    entry_indexes = {
        item["name"]: item["column_names"]
        for item in inspect(staging_db.bind).get_indexes("agent_scan_entries")
    }

    assert page_indexes["ix_agent_scan_pages_job_final"] == ["job_id", "is_final"]
    assert entry_indexes["ix_agent_scan_entries_job_page"] == ["job_id", "page_sequence"]
    assert entry_indexes["ix_agent_scan_entries_job_processing"] == [
        "job_id",
        "needs_processing",
        "outcome_status",
    ]


def test_scan_staging_rows_cascade_with_the_parent_job(staging_db):
    job = _add_scan_job(staging_db)
    staging_db.add_all([_page(), _entry()])
    staging_db.commit()

    staging_db.delete(job)
    staging_db.commit()

    assert staging_db.query(models.AgentScanPage).count() == 0
    assert staging_db.query(models.AgentScanEntry).count() == 0


def test_scan_staging_migration_upgrades_and_downgrades_a_temporary_database(tmp_path):
    backend = Path(__file__).resolve().parents[1]
    database = tmp_path / "scan-staging-migration.db"
    environment = os.environ.copy()
    environment["DATABASE_URL"] = f"sqlite:///{database.as_posix()}"

    def alembic(*arguments):
        subprocess.run(
            [sys.executable, "-m", "alembic", "-c", "alembic.ini", *arguments],
            cwd=backend,
            env=environment,
            check=True,
            capture_output=True,
            text=True,
        )

    alembic("upgrade", "head")
    with sqlite3.connect(database) as connection:
        tables = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
        revision = connection.execute("SELECT version_num FROM alembic_version").fetchone()[0]
    assert revision != "c25f7a9b1d02"
    assert {"agent_scan_pages", "agent_scan_entries"} <= tables

    alembic("downgrade", "c25f7a9b1d02")
    with sqlite3.connect(database) as connection:
        tables = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
    assert "agent_scan_pages" not in tables
    assert "agent_scan_entries" not in tables
