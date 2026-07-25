from pathlib import Path

import pytest
from onesearch_agent.paths import (
    PathOutsideAllowedRoots,
    browse,
    resolve_allowed_path,
    resolve_relative_path,
)
from onesearch_shared import AllowedRoot


def test_paths_reject_traversal_prefix_sibling_and_relative_absolute(tmp_path: Path):
    root = tmp_path / "docs"
    root.mkdir()
    (root / "a.txt").write_text("x")
    roots = [AllowedRoot(root_id="docs", path=str(root))]
    with pytest.raises(PathOutsideAllowedRoots):
        resolve_allowed_path(str(root / ".." / "secret"), roots)
    with pytest.raises(PathOutsideAllowedRoots):
        resolve_allowed_path(str(tmp_path / "docs2"), roots)
    with pytest.raises(PathOutsideAllowedRoots):
        resolve_relative_path("docs", "/absolute", roots)


def test_browse_is_confined_deterministic_and_bounded(tmp_path: Path):
    root = tmp_path / "docs"
    root.mkdir()
    for name in ["z", "a", "b"]:
        (root / name).write_text(name)
    entries = browse("docs", "", [AllowedRoot(root_id="docs", path=str(root))], max_entries=2)
    assert [entry.name for entry in entries] == ["a", "b"]


def test_symlink_escape_is_rejected_when_supported(tmp_path: Path):
    root = tmp_path / "docs"
    root.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    link = root / "escape"
    try:
        link.symlink_to(outside, target_is_directory=True)
    except OSError:
        pytest.skip("symlink creation unavailable")
    with pytest.raises(PathOutsideAllowedRoots):
        resolve_allowed_path(str(link), [AllowedRoot(root_id="docs", path=str(root))])


def test_browse_suppresses_symlink_escape(tmp_path: Path):
    root = tmp_path / "docs"
    root.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    (root / "safe").write_text("x")
    try:
        (root / "escape").symlink_to(outside, target_is_directory=True)
    except OSError:
        pytest.skip("symlink creation unavailable")
    entries = browse("docs", "", [AllowedRoot(root_id="docs", path=str(root))])
    assert [entry.name for entry in entries] == ["safe"]
