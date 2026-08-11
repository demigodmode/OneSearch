import multiprocessing
import os
import sqlite3
import time
from pathlib import Path

import pytest
from onesearch_agent.scan_spool import ScanSpool
from onesearch_shared import (
    REMOTE_MAX_MANIFEST_PAGE_BYTES,
    REMOTE_MAX_MANIFEST_PAGE_ENTRIES,
    canonical_wire_bytes,
)


def _cleanup_in_child(state_dir: str, result) -> None:
    result.put(
        ScanSpool.cleanup(
            Path(state_dir), job_id="job", payload_identity="payload", source_id="source"
        )
    )


def test_spool_persists_inventory_and_replays_same_page_after_restart(tmp_path: Path):
    spool = ScanSpool.create(
        tmp_path,
        job_id="job-1",
        payload_identity="payload-a",
        source_id="source-1",
    )
    spool.append_file("one.txt", 1, 10)
    spool.append_file("two.txt", 2, 20)
    spool.finish()

    first = spool.page(0)
    reopened = ScanSpool.resume(
        tmp_path,
        job_id="job-1",
        payload_identity="payload-a",
        source_id="source-1",
    )

    assert reopened.page(0).model_dump(mode="json") == first.model_dump(mode="json")


def test_spool_enforces_page_entry_and_wire_bounds_without_collecting_inventory(tmp_path: Path):
    spool = ScanSpool.create(tmp_path, job_id="job", payload_identity="payload", source_id="source")
    spool.append_files((f"flat/{number:06}.txt", number, number) for number in range(100_001))
    spool.finish()

    first = spool.page(0)
    middle = spool.page(1)

    assert len(first.page.files) == REMOTE_MAX_MANIFEST_PAGE_ENTRIES
    assert len(middle.page.files) == REMOTE_MAX_MANIFEST_PAGE_ENTRIES
    assert len(canonical_wire_bytes(first)) <= REMOTE_MAX_MANIFEST_PAGE_BYTES
    assert (
        first.checksum
        == ScanSpool.resume(tmp_path, job_id="job", payload_identity="payload", source_id="source")
        .page(0)
        .checksum
    )


def test_spool_rejects_file_append_at_configured_inventory_limit(tmp_path: Path):
    spool = ScanSpool.create(tmp_path, job_id="job", payload_identity="payload", source_id="source")
    spool.append_file("one.txt", 1, 1, max_files=1)

    with pytest.raises(RuntimeError, match="scan file limit exceeded"):
        spool.append_file("two.txt", 1, 1, max_files=1)

    assert spool.file_count == 1


def test_spool_fails_closed_for_payload_mismatch_and_corruption(tmp_path: Path):
    spool = ScanSpool.create(
        tmp_path, job_id="job", payload_identity="original", source_id="source"
    )
    with pytest.raises(RuntimeError, match="payload mismatch"):
        ScanSpool.resume(tmp_path, job_id="job", payload_identity="different", source_id="source")

    database = next((tmp_path / "scan-spool").glob("*.sqlite3"))
    spool.close()
    database.write_bytes(b"not sqlite")
    with pytest.raises(RuntimeError, match="corrupt"):
        ScanSpool.resume(tmp_path, job_id="job", payload_identity="original", source_id="source")


def test_spool_uses_durable_page_cursor_when_byte_bound_precedes_entry_bound(tmp_path: Path):
    spool = ScanSpool.create(tmp_path, job_id="job", payload_identity="payload", source_id="source")
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
        ScanSpool.resume(tmp_path, job_id="job", payload_identity="payload", source_id="source")
    assert not (tmp_path / "scan-spool").exists()


def test_directory_membership_is_fenced_across_interrupted_claim(tmp_path: Path):
    spool = ScanSpool.create(tmp_path, job_id="job", payload_identity="payload", source_id="source")
    spool.enqueue_directory("")
    claim = spool.next_directory()
    spool.observe_directory_member(claim, "one.txt", False, 1, 1)
    spool.observe_directory_member(claim, "two.txt", False, 2, 2)
    spool.seal_directory_membership(claim)
    spool.close()

    resumed = ScanSpool.resume(
        tmp_path, job_id="job", payload_identity="payload", source_id="source"
    )
    claim = resumed.next_directory()
    resumed.observe_directory_member(claim, "one.txt", False, 1, 1)
    with pytest.raises(RuntimeError, match="membership"):
        resumed.complete_directory(claim)


def test_directory_claim_is_atomic_across_two_open_connections(tmp_path: Path):
    first = ScanSpool.create(tmp_path, job_id="job", payload_identity="payload", source_id="source")
    first.enqueue_directory("")
    second = ScanSpool.resume(
        tmp_path, job_id="job", payload_identity="payload", source_id="source"
    )

    assert first.next_directory() == ""
    assert second.next_directory() is None


def test_page_rejects_gaps_and_semantic_tampering(tmp_path: Path):
    spool = ScanSpool.create(tmp_path, job_id="job", payload_identity="payload", source_id="source")
    spool.finish()
    assert spool.page(0).page.final is True
    with pytest.raises(RuntimeError, match="sequence"):
        spool.page(1)
    spool.close()

    reopened = ScanSpool.resume(
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
        ScanSpool.resume(tmp_path, job_id="job", payload_identity="payload", source_id="source")


def test_open_rejects_persisted_page_checksum_rewrite(tmp_path: Path):
    spool = ScanSpool.create(tmp_path, job_id="job", payload_identity="payload", source_id="source")
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
        ScanSpool.resume(tmp_path, job_id="job", payload_identity="payload", source_id="source")


def test_open_rejects_missing_or_truncated_finished_page_chain(tmp_path: Path):
    spool = ScanSpool.create(tmp_path, job_id="job", payload_identity="payload", source_id="source")
    spool.append_files((f"{number}.txt", number, number) for number in range(1_001))
    spool.finish()
    spool.close()
    database = next((tmp_path / "scan-spool").glob("*.sqlite3"))
    connection = sqlite3.connect(database)
    connection.execute("DELETE FROM pages WHERE sequence = 1")
    connection.commit()
    connection.close()

    with pytest.raises(RuntimeError, match="semantic"):
        ScanSpool.resume(tmp_path, job_id="job", payload_identity="payload", source_id="source")


def test_finish_rejects_claimed_or_pending_directory(tmp_path: Path):
    spool = ScanSpool.create(tmp_path, job_id="job", payload_identity="payload", source_id="source")
    spool.enqueue_directory("")
    with pytest.raises(RuntimeError, match="claimed|pending"):
        spool.finish()


def test_lifecycle_marker_fences_deleted_spool_and_payload_mismatch(tmp_path: Path):
    spool = ScanSpool.create(tmp_path, job_id="job", payload_identity="payload", source_id="source")
    spool.close()
    database = next((tmp_path / "scan-spool").glob("*.sqlite3"))
    database.unlink()

    with pytest.raises(RuntimeError, match="missing"):
        ScanSpool.resume(tmp_path, job_id="job", payload_identity="payload", source_id="source")
    with pytest.raises(RuntimeError, match="lifecycle"):
        ScanSpool.create(tmp_path, job_id="job", payload_identity="payload", source_id="source")


def test_lifecycle_marker_requires_matching_payload_and_explicit_resume(tmp_path: Path):
    spool = ScanSpool.create(tmp_path, job_id="job", payload_identity="payload", source_id="source")
    with pytest.raises(RuntimeError, match="resume"):
        ScanSpool.open(tmp_path, job_id="job", payload_identity="payload", source_id="source")
    spool.close()

    with pytest.raises(RuntimeError, match="payload"):
        ScanSpool.resume(tmp_path, job_id="job", payload_identity="different", source_id="source")
    assert ScanSpool.resume(tmp_path, job_id="job", payload_identity="payload", source_id="source")


def test_public_open_cannot_create_untracked_spool(tmp_path: Path):
    with pytest.raises(RuntimeError, match="create|resume"):
        ScanSpool.open(tmp_path, job_id="job", payload_identity="payload", source_id="source")
    assert not (tmp_path / "scan-spool").exists()


def test_terminal_cleanup_removes_exact_lifecycle_pair_idempotently(tmp_path: Path):
    spool = ScanSpool.create(tmp_path, job_id="job", payload_identity="payload", source_id="source")
    spool.finish()
    spool.close()

    assert (
        ScanSpool.cleanup(tmp_path, job_id="job", payload_identity="payload", source_id="source")
        is True
    )
    assert (
        ScanSpool.cleanup(tmp_path, job_id="job", payload_identity="payload", source_id="source")
        is False
    )
    with pytest.raises(RuntimeError, match="missing"):
        ScanSpool.resume(tmp_path, job_id="job", payload_identity="payload", source_id="source")


def test_terminal_cleanup_fails_closed_for_partial_lifecycle(tmp_path: Path):
    spool = ScanSpool.create(tmp_path, job_id="job", payload_identity="payload", source_id="source")
    spool.close()
    next((tmp_path / "scan-spool").glob("*.sqlite3")).unlink()

    with pytest.raises(RuntimeError, match="missing"):
        ScanSpool.cleanup(tmp_path, job_id="job", payload_identity="payload", source_id="source")


def test_lifecycle_mutations_request_parent_directory_fsync(tmp_path: Path, monkeypatch):
    synced = []
    monkeypatch.setattr(
        ScanSpool, "_fsync_directory", staticmethod(lambda path: synced.append(path))
    )
    spool = ScanSpool.create(tmp_path, job_id="job", payload_identity="payload", source_id="source")
    spool.finish()
    spool.close()
    ScanSpool.cleanup(tmp_path, job_id="job", payload_identity="payload", source_id="source")

    assert len(synced) >= 4


def test_lifecycle_marker_create_and_mutation_replace_same_directory_tempfiles(
    tmp_path: Path, monkeypatch
):
    replacements = []
    original_replace = os.replace

    def replace(source, destination):
        replacements.append((Path(source), Path(destination)))
        original_replace(source, destination)

    monkeypatch.setattr("onesearch_agent.scan_spool.os.replace", replace)
    spool = ScanSpool.create(tmp_path, job_id="job", payload_identity="payload", source_id="source")
    spool.finish()
    spool.close()
    ScanSpool.cleanup(tmp_path, job_id="job", payload_identity="payload", source_id="source")

    assert len(replacements) >= 2
    assert all(source.parent == destination.parent for source, destination in replacements)
    assert all(source != destination for source, destination in replacements)


def test_cleanup_waits_for_another_process_to_finish_resuming(tmp_path: Path):
    spool = ScanSpool.create(tmp_path, job_id="job", payload_identity="payload", source_id="source")
    spool.finish()
    spool.close()
    resumed = ScanSpool.resume(tmp_path, job_id="job", payload_identity="payload", source_id="source")
    context = multiprocessing.get_context("spawn")
    result = context.Queue()
    child = context.Process(target=_cleanup_in_child, args=(str(tmp_path), result))
    child.start()
    time.sleep(0.2)
    assert child.is_alive()

    resumed.close()
    child.join(timeout=10)
    assert child.exitcode == 0
    assert result.get(timeout=1) is True


def test_cleanup_rejects_unfinished_or_unclaimed_terminal_state(tmp_path: Path):
    spool = ScanSpool.create(tmp_path, job_id="job", payload_identity="payload", source_id="source")
    spool.enqueue_directory("")
    spool.close()

    with pytest.raises(RuntimeError, match="terminal"):
        ScanSpool.cleanup(tmp_path, job_id="job", payload_identity="payload", source_id="source")


def test_cleanup_keeps_recoverable_intent_if_spool_delete_fails(tmp_path: Path, monkeypatch):
    spool = ScanSpool.create(tmp_path, job_id="job", payload_identity="payload", source_id="source")
    spool.finish()
    spool.close()
    original = ScanSpool._remove_file

    def fail_spool(path):
        if path.suffix == ".sqlite3":
            raise OSError("locked")
        original(path)

    monkeypatch.setattr(ScanSpool, "_remove_file", staticmethod(fail_spool))
    with pytest.raises(RuntimeError, match="cleanup failed"):
        ScanSpool.cleanup(tmp_path, job_id="job", payload_identity="payload", source_id="source")

    assert ScanSpool.lifecycle_exists(tmp_path, "job")
    assert ScanSpool.exists(tmp_path, "job")
