"""Release-scale and contention coverage for remote agents."""

import importlib.util
import sys
from pathlib import Path

import pytest
from onesearch_shared import REMOTE_MAX_SCAN_FILES
from sqlalchemy import create_engine, select

from app.models import Base, IndexedFile


def _scale_module():
    path = Path(__file__).parents[2] / "scripts" / "agent_scale.py"
    spec = importlib.util.spec_from_file_location("agent_scale", path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


def _database_artifacts(database: Path) -> list[Path]:
    return [Path(str(database) + suffix) for suffix in ("", "-wal", "-shm", "-journal")]


def test_fleet_simulation_persists_contended_winners(tmp_path):
    result = _scale_module().simulate_agent_fleet(
        database=tmp_path / "fleet.db", agents=25, jitter_seed=7
    )

    assert result["setup_transitions"] == {"pending": 25, "approved_offline": 25}
    assert result["agent_statuses"] == {"offline": 25}
    assert result["fanout"]["polls"] == 25
    assert result["fanout"]["leased_jobs"] == 25
    assert result["fanout"]["persisted_unique_job_ids"] == 25
    assert result["fanout"]["persisted_unique_token_hashes"] == 25
    assert result["fanout"]["attempts"] == {"1": 25}
    assert result["fanout"]["measured_start_jitter_seconds"] > 0
    assert result["contested_poll"] == {
        "polls": 25,
        "winners": 1,
        "persisted_attempts": 1,
        "persisted_token_hashes": 1,
    }
    assert result["reconnect_after_expiry"] == {
        "polls": 25,
        "winners": 1,
        "same_job": True,
        "persisted_attempts": 2,
        "persisted_token_hashes": 1,
        "old_lease_rejected": True,
    }
    assert result["idempotent_batch"] == {
        "submissions": 2,
        "persisted_receipts": 1,
        "job_kind": "scan",
    }
    assert result["concurrent_catch_up"] == {
        "enqueues": 25,
        "returned_unique_job_ids": 1,
        "persisted_active_keys": 1,
    }
    assert not any(path.exists() for path in _database_artifacts(tmp_path / "fleet.db"))


def test_scale_run_uses_valid_topology_and_real_enqueue_payload(tmp_path):
    database = tmp_path / "scale.db"
    module = _scale_module()
    topology = module._topology(files=10_000_000, agents=25)
    result = module.run_scale(database=database, agents=2, files=40, batch_size=10)

    assert topology == {"source_count": 100, "max_rows_per_source": REMOTE_MAX_SCAN_FILES}
    assert result["rows_inserted"] == 40
    assert result["source_count"] == 2
    assert result["max_rows_per_source"] <= REMOTE_MAX_SCAN_FILES
    assert result["batch_size"] == 10
    assert result["capacity_estimate_bytes"] == module._estimate_bytes(40)
    assert result["observed_peak_database_bytes"] > 0
    assert result["peak_python_heap_bytes"] > 0
    assert "peak_memory_bytes" not in result
    assert result["process_peak_rss_bytes"] is None or result["process_peak_rss_bytes"] > 0
    assert result["process_current_rss_bytes"] is None or result["process_current_rss_bytes"] > 0
    if sys.platform == "win32" or Path("/proc/self/statm").exists():
        assert result["process_peak_rss_bytes"] > 0
        assert result["process_current_rss_bytes"] > 0
    enqueue = result["representative_enqueue"]
    assert enqueue["known_files_count"] <= REMOTE_MAX_SCAN_FILES
    assert enqueue["payload_max_scan_files"] == REMOTE_MAX_SCAN_FILES
    assert enqueue["payload_bytes"] > enqueue["known_files_count"]
    assert enqueue["elapsed_seconds"] >= 0
    assert enqueue["python_heap_delta_bytes"] >= 0
    assert enqueue["python_heap_peak_delta_bytes"] >= enqueue["python_heap_delta_bytes"]
    assert not any(path.exists() for path in _database_artifacts(database))


def test_scale_queries_have_distinct_honest_names_and_evidence(tmp_path):
    result = _scale_module().run_scale(
        database=tmp_path / "queries.db", agents=2, files=40, batch_size=10
    )

    expected = {
        "source_status",
        "known_files_projection",
        "point_upsert_lookup",
        "reconciliation_source_walk",
        "agent_dashboard",
    }
    assert set(result["query_plans"]) == expected
    assert set(result["queries"]) == expected
    assert all(item["elapsed_seconds"] >= 0 for item in result["queries"].values())
    assert all(item["result_count"] >= 0 for item in result["queries"].values())


def test_plan_check_rejects_an_unbounded_indexed_files_scan(tmp_path):
    module = _scale_module()
    database = tmp_path / "unbounded.db"
    engine = create_engine(f"sqlite:///{database.as_posix()}")
    Base.metadata.create_all(engine)
    try:
        with (
            engine.connect() as connection,
            pytest.raises(RuntimeError, match="full indexed_files scan"),
        ):
            module._plans(connection, 1, {"unbounded": select(IndexedFile)})
    finally:
        engine.dispose()


@pytest.mark.parametrize("suffix", ("", "-wal", "-shm", "-journal"))
def test_scale_refuses_preexisting_database_artifacts_without_changing_them(tmp_path, suffix):
    database = tmp_path / "owned.db"
    existing = Path(str(database) + suffix)
    existing.write_bytes(b"keep-this-byte-for-byte")

    with pytest.raises(FileExistsError, match="already exists"):
        _scale_module().run_scale(database=database, agents=1, files=1)

    assert existing.read_bytes() == b"keep-this-byte-for-byte"
    assert [path for path in _database_artifacts(database) if path.exists()] == [existing]


def test_fleet_simulation_refuses_preexisting_database(tmp_path):
    database = tmp_path / "existing-fleet.db"
    database.write_bytes(b"belongs-to-someone-else")

    with pytest.raises(FileExistsError, match="already exists"):
        _scale_module().simulate_agent_fleet(database=database, agents=1)

    assert database.read_bytes() == b"belongs-to-someone-else"


def test_capacity_failure_leaves_no_database_artifacts(tmp_path, monkeypatch):
    module = _scale_module()
    database = tmp_path / "capacity.db"

    def fail_capacity(*_args):
        raise RuntimeError("capacity rejected")

    monkeypatch.setattr(module, "_assert_capacity", fail_capacity)
    with pytest.raises(RuntimeError, match="capacity rejected"):
        module.run_scale(database=database, agents=1, files=1)

    assert not any(path.exists() for path in _database_artifacts(database))


@pytest.mark.parametrize("failure_point", ("_insert_rows", "_plans"))
def test_failures_after_database_creation_clean_owned_artifacts(
    tmp_path, monkeypatch, failure_point
):
    module = _scale_module()
    database = tmp_path / f"{failure_point}.db"

    def injected_failure(*_args, **_kwargs):
        raise LookupError(f"injected {failure_point} failure")

    monkeypatch.setattr(module, failure_point, injected_failure)
    with pytest.raises(LookupError, match=f"injected {failure_point} failure"):
        module.run_scale(database=database, agents=2, files=20, batch_size=10)

    assert not any(path.exists() for path in _database_artifacts(database))


def test_tracemalloc_start_failure_does_not_stop_an_inactive_tracer(tmp_path, monkeypatch):
    module = _scale_module()
    database = tmp_path / "trace.db"
    stop_calls = []

    def fail_start():
        raise RuntimeError("trace startup failed")

    monkeypatch.setattr(module.tracemalloc, "start", fail_start)
    monkeypatch.setattr(module.tracemalloc, "stop", lambda: stop_calls.append(True))
    with pytest.raises(RuntimeError, match="trace startup failed"):
        module.run_scale(database=database, agents=1, files=1)

    assert stop_calls == []
    assert not any(path.exists() for path in _database_artifacts(database))


def test_scale_success_removes_database_and_sidecars(tmp_path):
    database = tmp_path / "success.db"
    result = _scale_module().run_scale(database=database, agents=1, files=5, batch_size=2)

    assert result["rows_inserted"] == 5
    assert not any(path.exists() for path in _database_artifacts(database))
