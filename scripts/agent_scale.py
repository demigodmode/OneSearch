#!/usr/bin/env python
"""Exercise shipped remote-agent database paths at release scale."""

from __future__ import annotations

import argparse
import concurrent.futures
import ctypes
import json
import math
import os
import random
import shutil
import sqlite3
import sys
import threading
import time
import tracemalloc
from collections import Counter
from collections.abc import Callable
from ctypes import wintypes
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from onesearch_shared import REMOTE_MAX_SCAN_FILES  # noqa: E402
from sqlalchemy import case, create_engine, func, select  # noqa: E402
from sqlalchemy.exc import OperationalError  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402

from app.models import Agent, AgentBatch, AgentJob, Base, IndexedFile, Source  # noqa: E402
from app.services.agent_jobs import AgentJobService, JobLeaseError  # noqa: E402

_DATABASE_SUFFIXES = ("", "-wal", "-shm", "-journal")


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _database_artifacts(database: Path) -> list[Path]:
    return [Path(str(database) + suffix) for suffix in _DATABASE_SUFFIXES]


def _assert_fresh_database(database: Path) -> None:
    existing = [path for path in _database_artifacts(database) if path.exists()]
    if existing:
        raise FileExistsError("database artifact already exists: " + ", ".join(map(str, existing)))


def _cleanup_database(database: Path) -> None:
    for path in _database_artifacts(database):
        path.unlink(missing_ok=True)


def _engine(database: Path, *, concurrent: bool = False):
    engine = create_engine(
        f"sqlite:///{database.as_posix()}",
        connect_args={"timeout": 1, "check_same_thread": not concurrent},
    )
    Base.metadata.create_all(engine)
    if concurrent:
        with engine.begin() as connection:
            connection.exec_driver_sql("PRAGMA journal_mode=WAL")
            connection.exec_driver_sql("PRAGMA busy_timeout=1000")
    return engine


def _estimate_bytes(files: int) -> int:
    # Includes rows, indexes, WAL headroom, and SQLite page overhead. A 100k
    # audit used about 137 bytes per row, so 220 preserves useful margin.
    return files * 220


def _assert_capacity(database: Path, files: int) -> None:
    free = shutil.disk_usage(database.parent).free
    needed = _estimate_bytes(files)
    if free < needed:
        raise RuntimeError(
            f"not enough free disk for {files:,} rows: need about {needed / 2**30:.2f} GiB, "
            f"have {free / 2**30:.2f} GiB"
        )


def _topology(*, files: int, agents: int) -> dict[str, int]:
    source_count = max(agents, math.ceil(files / REMOTE_MAX_SCAN_FILES))
    return {
        "source_count": source_count,
        "max_rows_per_source": math.ceil(files / source_count),
    }


def _query_shapes(agents: int):
    agent_ids = [f"agent-{number}" for number in range(agents)]
    return {
        "source_status": select(
            func.count(), func.sum(case((IndexedFile.status == "success", 1), else_=0))
        ).where(IndexedFile.source_id == "source-0"),
        "known_files_projection": select(
            IndexedFile.path,
            IndexedFile.size_bytes,
            IndexedFile.modified_at_ns,
            IndexedFile.hash,
            IndexedFile.status,
        ).where(IndexedFile.source_id == "source-0"),
        "point_upsert_lookup": select(IndexedFile.id).where(
            IndexedFile.source_id == "source-0", IndexedFile.path == "remote/00000000.txt"
        ),
        "reconciliation_source_walk": select(IndexedFile).where(
            IndexedFile.source_id == "source-0"
        ),
        "agent_dashboard": (
            select(Source.agent_id, func.count(IndexedFile.id))
            .join(IndexedFile, IndexedFile.source_id == Source.id)
            .where(Source.agent_id.in_(agent_ids), IndexedFile.status == "success")
            .group_by(Source.agent_id)
        ),
    }


def _plans(connection, agents: int, shapes=None) -> dict[str, list[str]]:
    probes = shapes if shapes is not None else _query_shapes(agents)
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
        if "SCAN INDEXED_FILES" in detail.upper()
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
        del rows
    return results


def _database_size(database: Path) -> int:
    return sum(path.stat().st_size for path in _database_artifacts(database) if path.exists())


def _insert_rows(
    connection,
    *,
    database: Path,
    files: int,
    source_count: int,
    batch_size: int,
) -> int:
    peak = _database_size(database)
    for start in range(0, files, batch_size):
        stop = min(start + batch_size, files)
        rows = [
            {
                "source_id": f"source-{number % source_count}",
                "path": f"remote/{number:08d}.txt",
                "size_bytes": number,
                "modified_at_ns": number,
                "status": "success",
            }
            for number in range(start, stop)
        ]
        connection.execute(IndexedFile.__table__.insert(), rows)
        connection.commit()
        peak = max(peak, _database_size(database))
    return peak


def _process_memory() -> tuple[int | None, int | None]:
    """Return best-effort (peak RSS, current RSS) without optional packages."""
    if os.name == "nt":

        class ProcessMemoryCounters(ctypes.Structure):
            _fields_ = [
                ("cb", ctypes.c_ulong),
                ("PageFaultCount", ctypes.c_ulong),
                ("PeakWorkingSetSize", ctypes.c_size_t),
                ("WorkingSetSize", ctypes.c_size_t),
                ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
                ("QuotaPagedPoolUsage", ctypes.c_size_t),
                ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
                ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                ("PagefileUsage", ctypes.c_size_t),
                ("PeakPagefileUsage", ctypes.c_size_t),
            ]

        counters = ProcessMemoryCounters()
        counters.cb = ctypes.sizeof(counters)
        process = ctypes.windll.kernel32.GetCurrentProcess()
        get_memory = ctypes.windll.psapi.GetProcessMemoryInfo
        get_memory.argtypes = [
            wintypes.HANDLE,
            ctypes.POINTER(ProcessMemoryCounters),
            wintypes.DWORD,
        ]
        get_memory.restype = wintypes.BOOL
        if get_memory(process, ctypes.byref(counters), counters.cb):
            return int(counters.PeakWorkingSetSize), int(counters.WorkingSetSize)
        return None, None
    try:
        import resource

        peak = int(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)
        if sys.platform != "darwin":
            peak *= 1024
    except (ImportError, OSError, ValueError):
        peak = None
    try:
        pages = int(Path("/proc/self/statm").read_text(encoding="ascii").split()[1])
        current = pages * os.sysconf("SC_PAGE_SIZE")
    except (FileNotFoundError, IndexError, OSError, ValueError):
        current = None
    return peak, current


def _is_sqlite_busy(error: OperationalError) -> bool:
    original = error.orig
    if not isinstance(original, sqlite3.OperationalError):
        return False
    code = getattr(original, "sqlite_errorcode", None)
    base_code = code & 0xFF if code is not None else None
    return (
        base_code in {sqlite3.SQLITE_BUSY, sqlite3.SQLITE_LOCKED}
        or "locked" in str(original).lower()
    )


def _session_retry(sessions, operation: Callable, *, attempts: int = 30):
    for attempt in range(attempts):
        session = sessions()
        try:
            value = operation(session)
            session.commit()
            return value
        except OperationalError as error:
            session.rollback()
            if not _is_sqlite_busy(error) or attempt + 1 == attempts:
                raise
            time.sleep(min(0.005 * (attempt + 1), 0.1))
        finally:
            session.close()
    raise AssertionError("unreachable")


def _race(sessions, count: int, operation: Callable, delays=None):
    barrier = threading.Barrier(count)

    def run(number: int):
        barrier.wait()
        if delays is not None:
            time.sleep(delays[number])
        started = time.perf_counter()
        value = _session_retry(sessions, lambda session: operation(session, number))
        return started, value

    with concurrent.futures.ThreadPoolExecutor(max_workers=count) as pool:
        return list(pool.map(run, range(count)))


def simulate_agent_fleet(database: Path, agents: int = 25, jitter_seed: int = 1) -> dict[str, Any]:
    """Exercise actual lease and idempotency paths with 25-way SQLite races."""
    database = Path(database)
    _assert_fresh_database(database)
    owned = False
    engine = None
    try:
        owned = True
        engine = _engine(database, concurrent=True)
        sessions = sessionmaker(bind=engine, expire_on_commit=False)
        seed = sessions()
        try:
            records = [
                Agent(
                    id=f"agent-{number}",
                    name=f"Agent {number}",
                    platform="test",
                    version="test",
                    protocol_version=1,
                    status="pending",
                    allowed_roots=json.dumps(
                        [{"root_id": f"root-{number}", "path": f"/fixture/{number}"}]
                    ),
                )
                for number in range(agents)
            ]
            seed.add_all(records)
            seed.commit()
            pending_count = seed.query(Agent).filter_by(status="pending").count()
            approved_at = _now()
            for record in records:
                record.status = "offline"
                record.approved_at = approved_at
            sources = [
                Source(
                    id=f"source-{number}",
                    name=f"Source {number}",
                    root_path=f"/fixture/{number}",
                    location_type="agent",
                    agent_id=f"agent-{number}",
                    processing_mode="on_agent",
                )
                for number in range(agents)
            ]
            seed.add_all(sources)
            seed.commit()
            for source in sources:
                AgentJobService(seed).enqueue_scan(source, full=True, reason="scheduled")
            seed.commit()
        finally:
            seed.close()

        randomizer = random.Random(jitter_seed)
        delays = [randomizer.random() / 100 for _ in range(agents)]

        def poll_own_job(session, number):
            lease = AgentJobService(session).claim_next(f"agent-{number}")
            return (lease.id, lease.lease_token) if lease else None

        fanout_results = _race(sessions, agents, poll_own_job, delays)
        fanout_leases = [value for _, value in fanout_results if value is not None]
        fanout_starts = [started for started, _ in fanout_results]
        batch_job_id, batch_token = fanout_results[0][1]

        setup = sessions()
        try:
            browse = AgentJobService(setup).enqueue_browse("agent-0", "/fixture/0")
            browse_id = browse.id
            setup.commit()
        finally:
            setup.close()

        def poll_agent_zero(session, _number):
            lease = AgentJobService(session).claim_next("agent-0")
            return (lease.id, lease.lease_token) if lease else None

        contested_results = _race(sessions, agents, poll_agent_zero)
        contested_winners = [value for _, value in contested_results if value is not None]
        old_job_id, old_token = contested_winners[0]

        contested_check = sessions()
        try:
            first_claim = contested_check.get(AgentJob, browse_id)
            first_claim_attempts = first_claim.attempts
            first_claim_token_hashes = 1 if first_claim.lease_token_hash else 0
        finally:
            contested_check.close()

        expire = sessions()
        try:
            expired = expire.get(AgentJob, old_job_id)
            expired.lease_expires_at = _now() - timedelta(seconds=1)
            expire.commit()
            AgentJobService(expire).fail_expired_leases()
            expire.commit()
        finally:
            expire.close()

        reconnect_results = _race(sessions, agents, poll_agent_zero)
        reconnect_winners = [value for _, value in reconnect_results if value is not None]
        new_job_id, new_token = reconnect_winners[0]

        receipt = sessions()
        try:
            service = AgentJobService(receipt)
            try:
                service.extend_lease("agent-0", old_job_id, old_token)
            except JobLeaseError:
                old_lease_rejected = True
            else:
                old_lease_rejected = False
            service.accept_batch(
                "agent-0", batch_job_id, batch_token, "tiny-manifest-0", {"documents": []}
            )
            service.accept_batch(
                "agent-0", batch_job_id, batch_token, "tiny-manifest-0", {"documents": []}
            )
            receipt.commit()
        finally:
            receipt.close()

        def enqueue_catch_up(session, _number):
            source = session.get(Source, "source-0")
            return AgentJobService(session).enqueue_scan(source, full=True, reason="catch_up").id

        catch_up_results = _race(sessions, agents, enqueue_catch_up)
        catch_up_ids = [value for _, value in catch_up_results]

        check = sessions()
        try:
            agents_by_status = Counter(row.status for row in check.scalars(select(Agent)))
            fanout_ids = [job_id for job_id, _token in fanout_leases]
            fanout_jobs = list(check.scalars(select(AgentJob).where(AgentJob.id.in_(fanout_ids))))
            contested = check.get(AgentJob, browse_id)
            batch_job = check.get(AgentJob, batch_job_id)
            receipt_count = check.query(AgentBatch).filter_by(job_id=batch_job_id).count()
            active_source_zero = check.query(AgentJob).filter_by(active_key="source-0").count()
            return {
                "setup_transitions": {
                    "pending": pending_count,
                    "approved_offline": sum(
                        1
                        for row in check.scalars(select(Agent))
                        if row.status == "offline" and row.approved_at is not None
                    ),
                },
                "agent_statuses": dict(agents_by_status),
                "fanout": {
                    "polls": agents,
                    "leased_jobs": len(fanout_leases),
                    "persisted_unique_job_ids": len({job.id for job in fanout_jobs}),
                    "persisted_unique_token_hashes": len(
                        {job.lease_token_hash for job in fanout_jobs}
                    ),
                    "attempts": dict(Counter(str(job.attempts) for job in fanout_jobs)),
                    "measured_start_jitter_seconds": max(fanout_starts) - min(fanout_starts),
                },
                "contested_poll": {
                    "polls": agents,
                    "winners": len(contested_winners),
                    "persisted_attempts": first_claim_attempts,
                    "persisted_token_hashes": first_claim_token_hashes,
                },
                "reconnect_after_expiry": {
                    "polls": agents,
                    "winners": len(reconnect_winners),
                    "same_job": new_job_id == old_job_id == browse_id,
                    "persisted_attempts": contested.attempts,
                    "persisted_token_hashes": 1 if contested.lease_token_hash else 0,
                    "old_lease_rejected": old_lease_rejected,
                },
                "idempotent_batch": {
                    "submissions": 2,
                    "persisted_receipts": receipt_count,
                    "job_kind": batch_job.kind,
                },
                "concurrent_catch_up": {
                    "enqueues": agents,
                    "returned_unique_job_ids": len(set(catch_up_ids)),
                    "persisted_active_keys": active_source_zero,
                },
            }
        finally:
            check.close()
    finally:
        if engine is not None:
            engine.dispose()
        if owned:
            _cleanup_database(database)


def _measure_representative_enqueue(engine, source_id: str) -> dict[str, int | float | str]:
    sessions = sessionmaker(bind=engine, expire_on_commit=False)
    session = sessions()
    try:
        source = session.get(Source, source_id)
        before_current, _ = tracemalloc.get_traced_memory()
        tracemalloc.reset_peak()
        started = time.perf_counter()
        job = AgentJobService(session).enqueue_scan(source, full=True, reason="scale_audit")
        session.flush()
        elapsed = time.perf_counter() - started
        after_current, after_peak = tracemalloc.get_traced_memory()
        payload_text = job.payload
        payload = json.loads(payload_text)
        evidence = {
            "source_id": source_id,
            "known_files_count": len(payload["known_files"]),
            "payload_max_scan_files": payload["limits"]["max_scan_files"],
            "payload_bytes": len(payload_text.encode("utf-8")),
            "elapsed_seconds": elapsed,
            "python_heap_delta_bytes": max(0, after_current - before_current),
            "python_heap_peak_delta_bytes": max(0, after_peak - before_current),
        }
        session.commit()
        return evidence
    finally:
        session.expunge_all()
        session.close()


def run_scale(
    *, database: Path, agents: int, files: int, batch_size: int = 10_000
) -> dict[str, Any]:
    """Load bounded metadata batches, measure shipped queries, and remove owned SQLite files."""
    if agents < 1 or files < 1 or batch_size < 1:
        raise ValueError("agents, files, and batch_size must be positive")
    database = Path(database)
    _assert_fresh_database(database)
    _assert_capacity(database, files)
    topology = _topology(files=files, agents=agents)
    capacity_estimate = _estimate_bytes(files)
    started = time.perf_counter()
    tracing_started = False
    owned = False
    engine = None
    connection = None
    try:
        tracemalloc.start()
        tracing_started = True
        owned = True
        engine = _engine(database)
        connection = engine.connect()
        approved_at = _now()
        connection.execute(
            Agent.__table__.insert(),
            [
                {
                    "id": f"agent-{number}",
                    "name": f"Agent {number}",
                    "platform": "scale",
                    "version": "scale",
                    "protocol_version": 1,
                    "allowed_roots": json.dumps(
                        [{"root_id": f"root-{number}", "path": f"/fixture/{number}"}]
                    ),
                    "status": "offline",
                    "approved_at": approved_at,
                }
                for number in range(agents)
            ],
        )
        source_count = topology["source_count"]
        connection.execute(
            Source.__table__.insert(),
            [
                {
                    "id": f"source-{number}",
                    "name": f"Source {number}",
                    "root_path": f"/fixture/{number % agents}",
                    "location_type": "agent",
                    "agent_id": f"agent-{number % agents}",
                    "processing_mode": "on_agent",
                }
                for number in range(source_count)
            ],
        )
        connection.commit()
        observed_peak_database = _insert_rows(
            connection,
            database=database,
            files=files,
            source_count=source_count,
            batch_size=batch_size,
        )
        plans = _plans(connection, agents)
        queries = _run_queries(connection, agents)
        _insertion_heap_current, insertion_heap_peak = tracemalloc.get_traced_memory()
        connection.close()
        connection = None
        enqueue = _measure_representative_enqueue(engine, "source-0")
        observed_peak_database = max(observed_peak_database, _database_size(database))
        _current_heap, peak_heap = tracemalloc.get_traced_memory()
        peak_rss, current_rss = _process_memory()
        return {
            "rows_inserted": files,
            "source_count": source_count,
            "max_rows_per_source": topology["max_rows_per_source"],
            "batch_size": batch_size,
            "capacity_estimate_bytes": capacity_estimate,
            "observed_peak_database_bytes": observed_peak_database,
            "representative_enqueue": enqueue,
            "query_plans": plans,
            "queries": queries,
            "elapsed_seconds": time.perf_counter() - started,
            "peak_python_heap_bytes": max(insertion_heap_peak, peak_heap),
            "process_peak_rss_bytes": peak_rss,
            "process_current_rss_bytes": current_rss,
        }
    finally:
        if connection is not None:
            connection.close()
        if engine is not None:
            engine.dispose()
        if tracing_started and tracemalloc.is_tracing():
            tracemalloc.stop()
        if owned:
            _cleanup_database(database)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--agents", type=int, default=25)
    parser.add_argument("--files", type=int, default=10_000_000)
    parser.add_argument("--batch-size", type=int, default=10_000)
    parser.add_argument("--database", type=Path, default=Path(".agent-scale.db"))
    args = parser.parse_args()
    if args.agents < 1 or args.files < 1 or args.batch_size < 1:
        parser.error("--agents, --files, and --batch-size must be positive")
    print(
        json.dumps(
            run_scale(
                database=args.database,
                agents=args.agents,
                files=args.files,
                batch_size=args.batch_size,
            ),
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
