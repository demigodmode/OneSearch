"""File-backed SQLite race regressions for durable remote jobs."""

import threading
from datetime import datetime, timezone

from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker

from app.models import Agent, AgentJob, Base, Source
from app.services.agent_jobs import AgentJobService


def _now():
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _database(tmp_path):
    engine = create_engine(
        f"sqlite:///{(tmp_path / 'race.db').as_posix()}", connect_args={"timeout": 5}
    )
    event.listen(engine, "connect", lambda conn, _: conn.execute("PRAGMA foreign_keys=ON"))
    Base.metadata.create_all(engine)
    sessions = sessionmaker(bind=engine)
    db = sessions()
    agent = Agent(
        id="agent",
        name="Agent",
        platform="linux",
        version="1",
        protocol_version=1,
        allowed_roots="[]",
    )
    source = Source(
        id="source",
        name="Source",
        root_path="/data",
        location_type="agent",
        agent_id="agent",
        processing_mode="on_agent",
    )
    db.add_all([agent, source])
    db.commit()
    db.close()
    return engine, sessions


def test_two_sqlite_sessions_coalesce_concurrent_enqueue(tmp_path):
    engine, sessions = _database(tmp_path)
    barrier, jobs = threading.Barrier(2), []

    def worker():
        db = sessions()
        source = db.get(Source, "source")
        barrier.wait()
        jobs.append(AgentJobService(db).enqueue_scan(source, full=True).id)
        db.commit()
        db.close()

    threads = [threading.Thread(target=worker) for _ in range(2)]
    [thread.start() for thread in threads]
    [thread.join() for thread in threads]
    db = sessions()
    assert len(set(jobs)) == 1 and db.query(AgentJob).count() == 1
    db.close()
    engine.dispose()


def test_two_sqlite_sessions_issue_only_one_claim_lease(tmp_path):
    engine, sessions = _database(tmp_path)
    db = sessions()
    source = db.get(Source, "source")
    AgentJobService(db).enqueue_scan(source, full=True)
    db.commit()
    db.close()
    barrier, leases = threading.Barrier(2), []

    def worker():
        db = sessions()
        barrier.wait()
        lease = AgentJobService(db).claim_next("agent")
        db.commit()
        leases.append(lease)
        db.close()

    threads = [threading.Thread(target=worker) for _ in range(2)]
    [thread.start() for thread in threads]
    [thread.join() for thread in threads]
    assert sum(lease is not None for lease in leases) == 1
    engine.dispose()
