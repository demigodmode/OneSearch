from pathlib import Path
from uuid import uuid4

import onesearch_agent.scanner as scanner_module
import pytest
from onesearch_agent.scanner import RemoteScanner
from onesearch_shared import AllowedRoot

from app.services.scanner import FileScanner


def _v3_files(scanner: RemoteScanner, tmp_path: Path):
    spool = scanner.scan_v3(
        state_dir=tmp_path.parent / f"{tmp_path.name}-scanner-state-{uuid4().hex}",
        job_id="job",
        source_id="source",
        payload_identity="payload",
    )
    files = []
    sequence = 0
    while True:
        page = spool.page(sequence)
        files.extend(page.page.files)
        if page.page.final:
            spool.close()
            return files
        sequence += 1











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
    files = _v3_files(RemoteScanner(
        "root",
        [AllowedRoot(root_id="root", path=str(tmp_path))],
        include_patterns=["**/*.txt"],
        exclude_patterns=["**/node_modules/**"],
    ), tmp_path)
    assert sorted(item.path for item in files) == expected == ["nested/keep.txt", "root.txt"]


def test_explicit_empty_excludes_includes_default_excluded_dirs_but_defaults_do_not(tmp_path: Path):
    (tmp_path / "node_modules").mkdir()
    (tmp_path / "node_modules" / "a.txt").write_text("x")
    roots = [AllowedRoot(root_id="root", path=str(tmp_path))]
    explicit = _v3_files(RemoteScanner("root", roots, exclude_patterns=[]), tmp_path)
    default = _v3_files(RemoteScanner("root", roots, exclude_patterns=None), tmp_path)
    assert [item.path for item in explicit] == ["node_modules/a.txt"]
    assert default == []



def test_symlink_escape_is_not_manifested(tmp_path: Path):
    outside = tmp_path / "outside.txt"
    outside.write_text("x")
    link = tmp_path / "escape.txt"
    try:
        link.symlink_to(outside)
    except OSError:
        pytest.skip("symlink privilege unavailable")
    files = _v3_files(RemoteScanner("root", [AllowedRoot(root_id="root", path=str(tmp_path))]), tmp_path)
    assert "escape.txt" not in [item.path for item in files]



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
    spool.close()
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
