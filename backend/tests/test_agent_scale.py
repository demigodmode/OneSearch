"""Protocol-level stress coverage for a small fleet of remote agents."""

import importlib.util
from pathlib import Path


def _scale_module():
    path = Path(__file__).parents[2] / "scripts" / "agent_scale.py"
    spec = importlib.util.spec_from_file_location("agent_scale", path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


def test_fleet_simulation_prevents_duplicate_leases_batches_and_scans(tmp_path):
    result = _scale_module().simulate_agent_fleet(
        database=tmp_path / "fleet.db", agents=25, jitter_seed=7
    )

    assert result["agents_approved"] == 25
    assert result["sources_seeded"] == 25
    assert result["scans_seeded"] == 25
    assert result["leased_jobs"] == result["unique_leased_jobs"]
    assert result["batch_receipts"] == result["unique_batch_receipts"]
    assert result["active_scans"] == 1
    assert result["catch_up_scans"] == 1
    assert result["long_poll_jitter"]
    assert result["lease_expiry_reclaimed"]
    assert result["old_lease_rejected"]
    assert result["reconnect_storm"]
    assert result["idempotent_retry"]
    assert result["catch_up_coalesced"]


def test_scale_run_cleans_temporary_database_and_rejects_table_scans(tmp_path):
    database = tmp_path / "scale.db"
    result = _scale_module().run_scale(database=database, agents=2, files=40, batch_size=10)

    assert result["rows_inserted"] == 40
    assert result["query_plans"]
    assert set(result["queries"]) == {
        "source_status",
        "manifest_lookup",
        "reconciliation_lookup",
        "agent_dashboard",
    }
    assert all(item["elapsed_seconds"] >= 0 for item in result["queries"].values())
    assert not database.exists()
