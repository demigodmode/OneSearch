import sqlite3
from pathlib import Path

import pytest
from onesearch_agent.scan_spool import ScanSpool
from onesearch_shared import (
    REMOTE_MAX_MANIFEST_PAGE_BYTES,
    REMOTE_MAX_MANIFEST_PAGE_ENTRIES,
    canonical_wire_bytes,
)


def test_spool_persists_inventory_and_replays_same_page_after_restart(tmp_path: Path):
    spool = ScanSpool.open(
        tmp_path,
        job_id="job-1",
        payload_identity="payload-a",
        source_id="source-1",
    )
    spool.append_file("one.txt", 1, 10)
    spool.append_file("two.txt", 2, 20)
    spool.finish()

    first = spool.page(0)
    reopened = ScanSpool.open(
        tmp_path,
        job_id="job-1",
        payload_identity="payload-a",
        source_id="source-1",
    )

    assert reopened.page(0).model_dump(mode="json") == first.model_dump(mode="json")


def test_spool_enforces_page_entry_and_wire_bounds_without_collecting_inventory(tmp_path: Path):
    spool = ScanSpool.open(tmp_path, job_id="job", payload_identity="payload", source_id="source")
    spool.append_files((f"flat/{number:06}.txt", number, number) for number in range(100_001))
    spool.finish()

    first = spool.page(0)
    middle = spool.page(1)

    assert len(first.page.files) == REMOTE_MAX_MANIFEST_PAGE_ENTRIES
    assert len(middle.page.files) == REMOTE_MAX_MANIFEST_PAGE_ENTRIES
    assert len(canonical_wire_bytes(first)) <= REMOTE_MAX_MANIFEST_PAGE_BYTES
    assert (
        first.checksum
        == ScanSpool.open(tmp_path, job_id="job", payload_identity="payload", source_id="source")
        .page(0)
        .checksum
    )


def test_spool_fails_closed_for_payload_mismatch_and_corruption(tmp_path: Path):
    spool = ScanSpool.open(tmp_path, job_id="job", payload_identity="original", source_id="source")
    with pytest.raises(RuntimeError, match="payload mismatch"):
        ScanSpool.open(tmp_path, job_id="job", payload_identity="different", source_id="source")

    database = next((tmp_path / "scan-spool").glob("*.sqlite3"))
    spool.close()
    database.write_bytes(b"not sqlite")
    with pytest.raises(RuntimeError, match="corrupt"):
        ScanSpool.open(tmp_path, job_id="job", payload_identity="original", source_id="source")


def test_spool_uses_durable_page_cursor_when_byte_bound_precedes_entry_bound(tmp_path: Path):
    spool = ScanSpool.open(tmp_path, job_id="job", payload_identity="payload", source_id="source")
    for number in range(10):
        spool.append_file(f"{'x' * 300_000}/{number}.txt", number, number)
    spool.finish()

    first = spool.page(0)
    second = spool.page(1)

    assert len(first.page.files) < REMOTE_MAX_MANIFEST_PAGE_ENTRIES
    assert first.page.files[-1].path != second.page.files[0].path
    assert [item.path for item in first.page.files + second.page.files] == [
        f"{'x' * 300_000}/{number}.txt" for number in range(10)
    ]
    assert second.page.checkpoint.scanned_count == len(first.page.files) + len(second.page.files)


def test_resume_requires_existing_spool_before_connecting(tmp_path: Path):
    with pytest.raises(RuntimeError, match="missing"):
        ScanSpool.open(
            tmp_path, job_id="job", payload_identity="payload", source_id="source", resume=True
        )
    assert not (tmp_path / "scan-spool").exists()


def test_directory_membership_is_fenced_across_interrupted_claim(tmp_path: Path):
    spool = ScanSpool.open(tmp_path, job_id="job", payload_identity="payload", source_id="source")
    spool.enqueue_directory("")
    claim = spool.next_directory()
    spool.observe_directory_member(claim, "one.txt", False, 1, 1)
    spool.observe_directory_member(claim, "two.txt", False, 2, 2)
    spool.seal_directory_membership(claim)
    spool.close()

    resumed = ScanSpool.open(
        tmp_path, job_id="job", payload_identity="payload", source_id="source", resume=True
    )
    claim = resumed.next_directory()
    resumed.observe_directory_member(claim, "one.txt", False, 1, 1)
    with pytest.raises(RuntimeError, match="membership"):
        resumed.complete_directory(claim)


def test_directory_claim_is_atomic_across_two_open_connections(tmp_path: Path):
    first = ScanSpool.open(tmp_path, job_id="job", payload_identity="payload", source_id="source")
    first.enqueue_directory("")
    second = ScanSpool.open(tmp_path, job_id="job", payload_identity="payload", source_id="source")

    assert first.next_directory() == ""
    assert second.next_directory() is None


def test_page_rejects_gaps_and_semantic_tampering(tmp_path: Path):
    spool = ScanSpool.open(tmp_path, job_id="job", payload_identity="payload", source_id="source")
    spool.finish()
    assert spool.page(0).page.final is True
    with pytest.raises(RuntimeError, match="sequence"):
        spool.page(1)
    spool.close()

    reopened = ScanSpool.open(
        tmp_path, job_id="job", payload_identity="payload", source_id="source"
    )
    assert reopened.page(0).page.final
    reopened.close()

    database = next((tmp_path / "scan-spool").glob("*.sqlite3"))
    connection = sqlite3.connect(database)
    connection.execute("UPDATE metadata SET value = '1' WHERE key = 'inventory_count'")
    connection.commit()
    connection.close()
    with pytest.raises(RuntimeError, match="semantic"):
        ScanSpool.open(tmp_path, job_id="job", payload_identity="payload", source_id="source")


def test_open_rejects_persisted_page_checksum_rewrite(tmp_path: Path):
    spool = ScanSpool.open(tmp_path, job_id="job", payload_identity="payload", source_id="source")
    spool.append_file("one.txt", 1, 1)
    spool.finish()
    spool.page(0)
    spool.close()
    database = next((tmp_path / "scan-spool").glob("*.sqlite3"))
    connection = sqlite3.connect(database)
    connection.execute("UPDATE pages SET checksum = ?", ("0" * 64,))
    connection.commit()
    connection.close()

    with pytest.raises(RuntimeError, match="semantic"):
        ScanSpool.open(tmp_path, job_id="job", payload_identity="payload", source_id="source")


def test_open_rejects_missing_or_truncated_finished_page_chain(tmp_path: Path):
    spool = ScanSpool.open(tmp_path, job_id="job", payload_identity="payload", source_id="source")
    spool.append_files((f"{number}.txt", number, number) for number in range(1_001))
    spool.finish()
    spool.close()
    database = next((tmp_path / "scan-spool").glob("*.sqlite3"))
    connection = sqlite3.connect(database)
    connection.execute("DELETE FROM pages WHERE sequence = 1")
    connection.commit()
    connection.close()

    with pytest.raises(RuntimeError, match="semantic"):
        ScanSpool.open(tmp_path, job_id="job", payload_identity="payload", source_id="source")


def test_finish_rejects_claimed_or_pending_directory(tmp_path: Path):
    spool = ScanSpool.open(tmp_path, job_id="job", payload_identity="payload", source_id="source")
    spool.enqueue_directory("")
    with pytest.raises(RuntimeError, match="claimed|pending"):
        spool.finish()
