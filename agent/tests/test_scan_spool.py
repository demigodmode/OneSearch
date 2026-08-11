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
