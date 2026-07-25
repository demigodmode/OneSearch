from pathlib import Path

from onesearch_agent.scanner import RemoteScanner
from onesearch_shared import AllowedRoot


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
    assert manifest.complete is True


def test_scanner_marks_file_bound_incomplete(tmp_path: Path):
    (tmp_path / "a.txt").write_text("a")
    (tmp_path / "b.txt").write_text("b")
    manifest = RemoteScanner(
        "root", [AllowedRoot(root_id="root", path=str(tmp_path))], max_files=1
    ).scan(job_id="job", source_id="source")
    assert manifest.complete is False
    assert manifest.failures[0].error == "scan file limit exceeded"


def test_scanner_marks_unknown_root_incomplete(tmp_path: Path):
    manifest = RemoteScanner("missing", [AllowedRoot(root_id="root", path=str(tmp_path))]).scan(
        job_id="job", source_id="source"
    )
    assert manifest.complete is False
