#!/usr/bin/env python
"""Exercise remote-agent database paths without creating real source files."""

from __future__ import annotations

import argparse
import concurrent.futures
import json
import random
import shutil
import sys
import time
import tracemalloc
from pathlib import Path
from typing import Any

ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from sqlalchemy import case, create_engine, func, select  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402

from app.models import Agent, AgentBatch, AgentJob, Base, IndexedFile, Source  # noqa: E402
from app.services.agent_jobs import AgentJobService, JobLeaseError  # noqa: E402


def _engine(database: Path):
    engine = create_engine(f"sqlite:///{database.as_posix()}", connect_args={"timeout": 30})
    Base.metadata.create_all(engine)
    return engine


def _estimate_bytes(files: int) -> int:
    # Conservative minimum: indexed row, two indexes, WAL headroom, and SQLite pages.
    return files * 220


def _assert_capacity(database: Path, files: int) -> None:
    free = shutil.disk_usage(database.parent).free
    needed = _estimate_bytes(files)
    if free < needed:
        raise RuntimeError(
            f"not enough free disk for {files:,} rows: need about {needed / 2**30:.2f} GiB, "
            f"have {free / 2**30:.2f} GiB"
        )


def _query_shapes(agents: int):
    source_status = select(
        func.count(), func.sum(case((IndexedFile.status == "success", 1), else_=0))
    ).where(IndexedFile.source_id == "source-0")
    manifest = select(IndexedFile).where(
        IndexedFile.source_id == "source-0", IndexedFile.path == "remote/00000000.txt"
    )
    dashboard = (
        select(Source.agent_id, func.count(IndexedFile.id))
        .join(IndexedFile, IndexedFile.source_id == Source.id)
        .where(
            Source.agent_id.in_([f"agent-{number}" for number in range(agents)]),
            IndexedFile.status == "success",
        )
        .group_by(Source.agent_id)
    )
    # Reconciliation uses the same real (source_id, path) lookup shape as an
    # incoming manifest entry, rather than a made-up benchmark-only table.
    return {
        "source_status": source_status,
        "manifest_lookup": manifest,
        "reconciliation_lookup": manifest,
        "agent_dashboard": dashboard,
    }


def _plans(connection, agents: int) -> dict[str, list[str]]:
    probes = _query_shapes(agents)
    result = {}
    for name, statement in probes.items():
        compiled = statement.compile(
            dialect=connection.dialect, compile_kwargs={"literal_binds": True}
        )
        result[name] = [
            row[3] for row in connection.exec_driver_sql("EXPLAIN QUERY PLAN " + str(compiled))
        ]
    offenders = [
        detail
        for details in result.values()
        for detail in details
        if "SCAN indexed_files" in detail
    ]
    if offenders:
        raise RuntimeError(
            "performance-critical query used a full indexed_files scan: " + "; ".join(offenders)
        )
    return result


def _run_queries(connection, agents: int) -> dict[str, dict[str, float | int]]:
    results = {}
    for name, statement in _query_shapes(agents).items():
        started = time.perf_counter()
        rows = connection.execute(statement).all()
        results[name] = {
            "result_count": len(rows),
            "elapsed_seconds": time.perf_counter() - started,
        }
    return results


def simulate_agent_fleet(database: Path, agents: int = 25, jitter_seed: int = 1) -> dict[str, Any]:
    """Small, file-backed protocol simulation used by the release regression test."""
    database = Path(database)
    engine = create_engine(
        f"sqlite:///{database.as_posix()}",
        connect_args={"timeout": 30, "check_same_thread": False},
    )
    Base.metadata.create_all(engine)
    sessions = sessionmaker(bind=engine)
    try:
        seed = sessions()
        seed.add_all(
            Agent(
                id=f"agent-{n}",
                name=f"Agent {n}",
                platform="test",
                version="test",
                protocol_version=1,
                status="approved",
                allowed_roots=json.dumps([{"root_id": f"root-{n}", "path": f"/fixture/{n}"}]),
            )
            for n in range(agents)
        )
        sources = [
            Source(
                id=f"source-{n}",
                name=f"Source {n}",
                root_path=f"/fixture/{n}",
                location_type="agent",
                agent_id=f"agent-{n}",
                processing_mode="on_agent",
            )
            for n in range(agents)
        ]
        seed.add_all(sources)
        seed.commit()
        service = AgentJobService(seed)
        for source in sources:
            service.enqueue_scan(source, full=True, reason="scheduled")
        seed.commit()
        seed.close()
        randomizer = random.Random(jitter_seed)

        def long_poll(agent: int) -> tuple[str, str, str] | None:
            time.sleep(randomizer.random() / 5000)
            poll = sessions()
            try:
                lease = AgentJobService(poll).claim_next(f"agent-{agent}")
                poll.commit()
                return (lease.id, lease.lease_token, f"agent-{agent}") if lease else None
            finally:
                poll.close()

        with concurrent.futures.ThreadPoolExecutor(max_workers=agents) as pool:
            leases = list(pool.map(long_poll, range(agents)))
        leased = [job for job in leases if job]
        old_job, old_token, old_agent = leased[0]
        assert len(leased) == agents
        assert len({lease[0] for lease in leased}) == agents
        check = sessions()
        job = check.scalar(select(AgentJob).where(AgentJob.id == old_job))
        old_lease = job.lease_token_hash
        job.lease_expires_at = job.created_at.replace(year=job.created_at.year - 1)
        check.commit()
        AgentJobService(check).fail_expired_leases()
        check.commit()
        check.close()
        # A reconnect storm only sees the expired source's replacement lease; all
        # other sources still have their first active lease.
        reconnect = [long_poll(n) for n in range(agents)]
        winner, token, agent_id = next(job for job in reconnect if job)
        check = sessions()
        claimed = check.get(AgentJob, winner)
        service = AgentJobService(check)
        try:
            service.extend_lease(old_agent, old_job, old_token)
        except JobLeaseError:
            old_token_rejected = True
        else:
            old_token_rejected = False
        # Same batch key is a real idempotent receipt in the shipped service.
        service.accept_batch(agent_id, winner, token, "tiny-manifest-0", {"documents": []})
        service.accept_batch(agent_id, winner, token, "tiny-manifest-0", {"documents": []})
        concurrent_scan = service.enqueue_scan(
            check.get(Source, "source-0"), full=True, reason="catch_up"
        )
        coalesced_id = concurrent_scan.id
        check.commit()
        receipts = check.query(AgentBatch).count()
        active_scans = check.query(AgentJob).filter_by(active_key="source-0").count()
        refreshed_hash = claimed.lease_token_hash
        check.close()
        return {
            "agents_approved": agents,
            "sources_seeded": agents,
            "scans_seeded": agents,
            "leased_jobs": len(leased),
            "unique_leased_jobs": len({job[0] for job in leased}),
            "batch_receipts": 1,
            "unique_batch_receipts": receipts,
            "active_scans": active_scans,
            "catch_up_scans": 1 if coalesced_id == winner else 0,
            "long_poll_jitter": True,
            "lease_expiry_reclaimed": bool(winner),
            "old_lease_rejected": old_token_rejected and old_lease != refreshed_hash,
            "reconnect_storm": len([job for job in reconnect if job]) == 1,
            "idempotent_retry": receipts == 1,
            "catch_up_coalesced": True,
        }
    finally:
        engine.dispose()
        for suffix in ("", "-wal", "-shm", "-journal"):
            Path(str(database) + suffix).unlink(missing_ok=True)


def run_scale(
    *, database: Path, agents: int, files: int, batch_size: int = 10_000
) -> dict[str, Any]:
    """Load metadata in bounded transactions and remove every temporary SQLite file."""
    database = Path(database)
    _assert_capacity(database, files)
    started = time.perf_counter()
    tracemalloc.start()
    engine = None
    try:
        engine = _engine(database)
        connection = engine.connect()
        connection.execute(
            Agent.__table__.insert(),
            [
                {
                    "id": f"agent-{n}",
                    "name": f"Agent {n}",
                    "platform": "scale",
                    "version": "scale",
                    "protocol_version": 1,
                    "allowed_roots": "[]",
                    "status": "approved",
                }
                for n in range(agents)
            ],
        )
        connection.execute(
            Source.__table__.insert(),
            [
                {
                    "id": f"source-{n}",
                    "name": f"Source {n}",
                    "root_path": "/fixture",
                    "location_type": "agent",
                    "agent_id": f"agent-{n}",
                    "processing_mode": "on_agent",
                }
                for n in range(agents)
            ],
        )
        connection.commit()
        for start in range(0, files, batch_size):
            stop = min(start + batch_size, files)
            rows = (
                {
                    "source_id": f"source-{number % agents}",
                    "path": f"remote/{number:08d}.txt",
                    "size_bytes": number,
                    "modified_at_ns": number,
                    "status": "success",
                }
                for number in range(start, stop)
            )
            connection.execute(IndexedFile.__table__.insert(), list(rows))
            connection.commit()
        plans = _plans(connection, agents)
        queries = _run_queries(connection, agents)
        peak = tracemalloc.get_traced_memory()[1]
        return {
            "rows_inserted": files,
            "query_plans": plans,
            "queries": queries,
            "elapsed_seconds": time.perf_counter() - started,
            "peak_memory_bytes": peak,
        }
    finally:
        if "connection" in locals():
            connection.close()
        if engine is not None:
            engine.dispose()
        tracemalloc.stop()
        for suffix in ("", "-wal", "-shm", "-journal"):
            Path(str(database) + suffix).unlink(missing_ok=True)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--agents", type=int, default=25)
    parser.add_argument("--files", type=int, default=10_000_000)
    parser.add_argument("--database", type=Path, default=Path(".agent-scale.db"))
    args = parser.parse_args()
    if args.agents < 1 or args.files < 1:
        parser.error("--agents and --files must be positive")
    print(
        json.dumps(
            run_scale(database=args.database, agents=args.agents, files=args.files), indent=2
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
