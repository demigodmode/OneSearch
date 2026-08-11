from pathlib import Path

import onesearch_agent.scanner as scanner_module
import pytest
from onesearch_agent.scanner import RemoteScanner
from onesearch_shared import AllowedRoot

from app.services.scanner import FileScanner


def test_scanner_emits_canonical_paths_and_skips_unchanged(tmp_path: Path):
    (tmp_path / "keep.txt").write_text("one")
    (tmp_path / "nested").mkdir()
    (tmp_path / "nested" / "skip.tmp").write_text("two")
    scanner = RemoteScanner(
        "root",
        [AllowedRoot(root_id="root", path=str(tmp_path))],
        include_patterns=["**/*"],
        exclude_patterns=["**/*.tmp"],
        known={
            "keep.txt": {"size_bytes": 3, "modified_at": (tmp_path / "keep.txt").stat().st_mtime_ns}
        },
    )

    manifest = scanner.scan(job_id="job", source_id="source")

    assert [item.path for item in manifest.files] == ["keep.txt"]
    assert manifest.files[0].content_hash is None
    assert scanner.changed_paths == []
    assert manifest.changed_paths == []
    assert manifest.complete is True


def test_scanner_limits_nested_source_and_emits_source_relative_paths(tmp_path: Path):
    (tmp_path / "sibling.txt").write_text("outside")
    source = tmp_path / "team"
    source.mkdir()
    (source / "report.txt").write_text("inside")
    (source / "nested").mkdir()
    (source / "nested" / "notes.txt").write_text("inside")
    report = (source / "report.txt").stat()

    manifest = RemoteScanner(
        "root",
        [AllowedRoot(root_id="root", path=str(tmp_path))],
        source_prefix="team",
        known={
            "report.txt": {
                "size_bytes": report.st_size,
                "modified_at": report.st_mtime_ns,
            }
        },
    ).scan(job_id="job", source_id="source")

    assert [item.path for item in manifest.files] == ["nested/notes.txt", "report.txt"]
    assert manifest.changed_paths == ["nested/notes.txt"]
    assert all(not item.path.startswith("team/") for item in manifest.files)


def test_scanner_marks_file_bound_incomplete(tmp_path: Path):
    (tmp_path / "a.txt").write_text("a")
    (tmp_path / "b.txt").write_text("b")
    manifest = RemoteScanner(
        "root", [AllowedRoot(root_id="root", path=str(tmp_path))], max_files=1
    ).scan(job_id="job", source_id="source")
    assert manifest.complete is False
    assert manifest.changed_paths == ["a.txt"]
    assert manifest.failures[0].error == "scan file limit exceeded"


def test_scanner_stops_listing_after_small_file_cap(monkeypatch, tmp_path):
    from onesearch_agent.paths import SafeDirectoryEntry, SafeDirectoryPage

    listed = []

    def listing(_root_id, relative, _roots, max_entries):
        listed.append(relative)
        if relative == "":
            return SafeDirectoryPage(
                (
                    SafeDirectoryEntry("a", "a", True, 0, 0),
                    SafeDirectoryEntry("later", "later", True, 0, 0),
                ),
                False,
            )
        if relative == "a":
            return SafeDirectoryPage(
                (
                    SafeDirectoryEntry("a/one.txt", "one.txt", False, 1, 1),
                    SafeDirectoryEntry("a/two.txt", "two.txt", False, 1, 1),
                ),
                False,
            )
        raise AssertionError(f"scanner listed after cap: {relative}")

    monkeypatch.setattr(scanner_module, "list_confined_entries_page", listing)
    manifest = RemoteScanner(
        "root", [AllowedRoot(root_id="root", path=str(tmp_path))], max_files=1
    ).scan(job_id="j", source_id="s")

    assert [item.path for item in manifest.files] == ["a/one.txt"]
    assert manifest.complete is False
    assert listed == ["", "a"]


def test_scanner_prunes_excluded_unreadable_subtree_before_listing(monkeypatch, tmp_path):
    from onesearch_agent.paths import SafeDirectoryEntry, SafeDirectoryPage

    listed = []

    def listing(_root_id, relative, _roots, max_entries):
        listed.append(relative)
        if relative == "":
            return SafeDirectoryPage(
                (
                    SafeDirectoryEntry("excluded", "excluded", True, 0, 0),
                    SafeDirectoryEntry("keep.txt", "keep.txt", False, 1, 1),
                ),
                False,
            )
        if relative == "excluded":
            raise AssertionError("excluded subtree must never be listed")
        raise AssertionError(f"unexpected directory: {relative}")

    monkeypatch.setattr(scanner_module, "list_confined_entries_page", listing)
    manifest = RemoteScanner(
        "root",
        [AllowedRoot(root_id="root", path=str(tmp_path))],
        exclude_patterns=["excluded/**"],
    ).scan(job_id="j", source_id="s")

    assert manifest.complete is True
    assert [item.path for item in manifest.files] == ["keep.txt"]
    assert listed == [""]


def test_scanner_keeps_deterministic_order_while_streaming(monkeypatch, tmp_path):
    from onesearch_agent.paths import SafeDirectoryEntry, SafeDirectoryPage

    pages = {
        "": (
            SafeDirectoryEntry("z.txt", "z.txt", False, 1, 1),
            SafeDirectoryEntry("a", "a", True, 0, 0),
        ),
        "a": (
            SafeDirectoryEntry("a/b.txt", "b.txt", False, 1, 1),
            SafeDirectoryEntry("a/a.txt", "a.txt", False, 1, 1),
        ),
    }
    monkeypatch.setattr(
        scanner_module,
        "list_confined_entries_page",
        lambda _root_id, relative, _roots, max_entries: SafeDirectoryPage(pages[relative], False),
    )

    manifest = RemoteScanner("root", [AllowedRoot(root_id="root", path=str(tmp_path))]).scan(
        job_id="j", source_id="s"
    )

    assert [item.path for item in manifest.files] == ["a/a.txt", "a/b.txt", "z.txt"]


def test_scanner_retries_prior_failed_file_with_matching_metadata(tmp_path: Path):
    file = tmp_path / "retry.txt"
    file.write_text("x")
    info = file.stat()
    scanner = RemoteScanner(
        "root",
        [AllowedRoot(root_id="root", path=str(tmp_path))],
        known={
            "retry.txt": {
                "size_bytes": info.st_size,
                "modified_at": info.st_mtime_ns,
                "status": "failed",
            }
        },
    )
    manifest = scanner.scan(job_id="j", source_id="s")
    assert scanner.changed_paths == ["retry.txt"]
    assert manifest.changed_paths == ["retry.txt"]


def test_scanner_marks_unknown_root_incomplete(tmp_path: Path):
    manifest = RemoteScanner("missing", [AllowedRoot(root_id="root", path=str(tmp_path))]).scan(
        job_id="job", source_id="source"
    )
    assert manifest.complete is False


def test_scanner_per_directory_truncation_is_incomplete(tmp_path: Path):
    (tmp_path / "a").write_text("a")
    (tmp_path / "b").write_text("b")
    manifest = RemoteScanner(
        "root", [AllowedRoot(root_id="root", path=str(tmp_path))], max_entries_per_directory=1
    ).scan(job_id="job", source_id="source")
    assert manifest.complete is False and manifest.failures


def test_remote_scanner_matches_backend_patterns_without_opening_files(tmp_path: Path, monkeypatch):
    (tmp_path / "root.txt").write_text("x")
    (tmp_path / "nested").mkdir()
    (tmp_path / "nested" / "keep.txt").write_text("x")
    (tmp_path / "node_modules").mkdir()
    (tmp_path / "node_modules" / "skip.txt").write_text("x")
    expected = [
        Path(item).relative_to(tmp_path).as_posix()
        for item in FileScanner(
            str(tmp_path), include_patterns=["**/*.txt"], exclude_patterns=["**/node_modules/**"]
        ).scan()
    ]
    monkeypatch.setattr(
        scanner_module,
        "open_confined_file",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("opened file")),
        raising=False,
    )
    manifest = RemoteScanner(
        "root",
        [AllowedRoot(root_id="root", path=str(tmp_path))],
        include_patterns=["**/*.txt"],
        exclude_patterns=["**/node_modules/**"],
    ).scan(job_id="job", source_id="source")
    assert [item.path for item in manifest.files] == expected == ["nested/keep.txt", "root.txt"]


def test_explicit_empty_excludes_includes_default_excluded_dirs_but_defaults_do_not(tmp_path: Path):
    (tmp_path / "node_modules").mkdir()
    (tmp_path / "node_modules" / "a.txt").write_text("x")
    roots = [AllowedRoot(root_id="root", path=str(tmp_path))]
    explicit = RemoteScanner("root", roots, exclude_patterns=[]).scan(job_id="j", source_id="s")
    default = RemoteScanner("root", roots, exclude_patterns=None).scan(job_id="j", source_id="s")
    assert [item.path for item in explicit.files] == ["node_modules/a.txt"]
    assert default.files == []


def test_listing_failure_marks_scan_incomplete_with_directory_failure(tmp_path: Path, monkeypatch):
    (tmp_path / "a.txt").write_text("x")
    (tmp_path / "nested").mkdir()
    original = scanner_module.list_confined_entries_page

    def fail_nested(root_id, relative, roots, max_entries):
        if relative == "nested":
            raise scanner_module.PathOutsideAllowedRoots("permission denied")
        return original(root_id, relative, roots, max_entries)

    monkeypatch.setattr(scanner_module, "list_confined_entries_page", fail_nested)
    manifest = RemoteScanner("root", [AllowedRoot(root_id="root", path=str(tmp_path))]).scan(
        job_id="j", source_id="s"
    )
    assert manifest.complete is False and manifest.failures[0].path == "scan"
    assert [item.path for item in manifest.files] == ["a.txt"]
    assert manifest.changed_paths == ["a.txt"]


def test_symlink_escape_is_not_manifested(tmp_path: Path):
    outside = tmp_path / "outside.txt"
    outside.write_text("x")
    link = tmp_path / "escape.txt"
    try:
        link.symlink_to(outside)
    except OSError:
        pytest.skip("symlink privilege unavailable")
    manifest = RemoteScanner("root", [AllowedRoot(root_id="root", path=str(tmp_path))]).scan(
        job_id="j", source_id="s"
    )
    assert "escape.txt" not in [item.path for item in manifest.files]


def test_page_entry_failure_makes_manifest_incomplete_without_filesystem_reconciliation(
    monkeypatch, tmp_path
):
    from onesearch_agent.paths import SafeDirectoryFailure, SafeDirectoryPage

    monkeypatch.setattr(
        scanner_module,
        "list_confined_entries_page",
        lambda *args, **kwargs: SafeDirectoryPage(
            (), False, (SafeDirectoryFailure("raced.txt", "permission denied"),)
        ),
    )
    manifest = RemoteScanner("root", [AllowedRoot(root_id="root", path=str(tmp_path))]).scan(
        job_id="j", source_id="s"
    )
    assert manifest.complete is False
    assert manifest.files == []
    assert manifest.failures[0].error.startswith("raced.txt:")


def test_v3_scan_spools_only_nested_source_inventory_and_resumes_without_rewalking(
    tmp_path, monkeypatch
):
    (tmp_path / "outside.txt").write_text("outside")
    nested = tmp_path / "team"
    nested.mkdir()
    (nested / "inside.txt").write_text("inside")
    scanner = RemoteScanner(
        "root", [AllowedRoot(root_id="root", path=str(tmp_path))], source_prefix="team"
    )

    spool = scanner.scan_v3(
        state_dir=tmp_path / "state",
        job_id="job",
        source_id="source",
        payload_identity="v3-payload",
    )
    page = spool.page(0)
    monkeypatch.setattr(
        scanner_module, "iter_confined_entries", lambda *args: pytest.fail("rewalked")
    )

    resumed = scanner.scan_v3(
        state_dir=tmp_path / "state",
        job_id="job",
        source_id="source",
        payload_identity="v3-payload",
    )

    assert [item.path for item in page.page.files] == ["inside.txt"]
    assert resumed.page(0).checksum == page.checksum


def test_v3_scan_resumes_interrupted_directory_without_mixing_metadata(tmp_path, monkeypatch):
    entries = [
        scanner_module.SafeDirectoryEntry("one.txt", "one.txt", False, 1, 1),
        scanner_module.SafeDirectoryEntry("two.txt", "two.txt", False, 2, 2),
    ]
    calls = 0

    def interrupted(*_args):
        nonlocal calls
        calls += 1
        yield entries[0]
        if calls == 1:
            raise scanner_module.PathOutsideAllowedRoots("interrupted")
        yield entries[1]

    monkeypatch.setattr(scanner_module, "iter_confined_entries", interrupted)
    scanner = RemoteScanner("root", [AllowedRoot(root_id="root", path=str(tmp_path))])
    with pytest.raises(scanner_module.PathOutsideAllowedRoots):
        scanner.scan_v3(
            state_dir=tmp_path / "state",
            job_id="job",
            source_id="source",
            payload_identity="payload",
        )

    resumed = scanner.scan_v3(
        state_dir=tmp_path / "state",
        job_id="job",
        source_id="source",
        payload_identity="payload",
        resume=True,
    )
    assert [item.path for item in resumed.page(0).page.files] == ["one.txt", "two.txt"]


def test_v3_default_retry_cannot_finalize_an_unfinished_spool(tmp_path, monkeypatch):
    entry = scanner_module.SafeDirectoryEntry("one.txt", "one.txt", False, 1, 1)

    def interrupted(*_args):
        yield entry
        raise scanner_module.PathOutsideAllowedRoots("interrupted")

    monkeypatch.setattr(scanner_module, "iter_confined_entries", interrupted)
    scanner = RemoteScanner("root", [AllowedRoot(root_id="root", path=str(tmp_path))])
    with pytest.raises(scanner_module.PathOutsideAllowedRoots):
        scanner.scan_v3(
            state_dir=tmp_path / "state",
            job_id="job",
            source_id="source",
            payload_identity="payload",
        )

    with pytest.raises(scanner_module.PathOutsideAllowedRoots):
        scanner.scan_v3(
            state_dir=tmp_path / "state",
            job_id="job",
            source_id="source",
            payload_identity="payload",
        )
    spool = scanner_module.ScanSpool.resume(
        tmp_path / "state",
        job_id="job",
        payload_identity="payload",
        source_id="source",
    )
    assert spool.finished is False


def test_v3_keeps_lifecycle_artifacts_for_terminal_owner(tmp_path):
    (tmp_path / "one.txt").write_text("one")
    scanner = RemoteScanner("root", [AllowedRoot(root_id="root", path=str(tmp_path))])
    scanner.scan_v3(
        state_dir=tmp_path / "state", job_id="job", source_id="source", payload_identity="payload"
    )

    assert scanner_module.ScanSpool.lifecycle_exists(tmp_path / "state", "job")
    assert scanner_module.ScanSpool.exists(tmp_path / "state", "job")
