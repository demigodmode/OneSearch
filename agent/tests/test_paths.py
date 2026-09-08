import os
from pathlib import Path

import onesearch_agent.paths as paths
import pytest
from onesearch_agent.paths import (
    PathOutsideAllowedRoots,
    browse,
    list_confined_entries,
    open_confined_file,
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


def test_list_confined_entries_returns_handle_metadata_without_host_paths(tmp_path: Path):
    root = tmp_path / "docs"
    root.mkdir()
    (root / "z.txt").write_text("z")
    (root / "a").mkdir()
    entries = list_confined_entries("docs", "", [AllowedRoot(root_id="docs", path=str(root))])
    assert [(item.relative_path, item.is_dir) for item in entries] == [
        ("a", True),
        ("z.txt", False),
    ]


def test_windows_handle_metadata_converts_filetime_and_large_size(monkeypatch):
    class Kernel:
        def GetFileInformationByHandle(self, handle, pointer):  # noqa: N802
            info = pointer._obj
            info.dwFileAttributes = 0x10
            info.nFileSizeHigh, info.nFileSizeLow = 2, 3
            ticks = 116444736000000000 + 123
            info.ftLastWriteTimeLowDateTime = ticks & 0xFFFFFFFF
            info.ftLastWriteTimeHighDateTime = ticks >> 32
            return True

    import ctypes

    monkeypatch.setattr(paths, "_windows_kernel32", lambda: (ctypes, Kernel()))
    assert paths._windows_handle_metadata(1) == (True, (2 << 32) | 3, 12300)


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


def test_relative_path_cannot_cross_into_another_root(tmp_path: Path):
    first = tmp_path / "first"
    second = tmp_path / "second"
    first.mkdir()
    second.mkdir()
    link = first / "to-second"
    try:
        link.symlink_to(second, target_is_directory=True)
    except OSError:
        pytest.skip("symlink creation unavailable")
    roots = [AllowedRoot(root_id="a", path=str(first)), AllowedRoot(root_id="b", path=str(second))]
    with pytest.raises(PathOutsideAllowedRoots):
        resolve_relative_path("a", "to-second", roots)


@pytest.mark.skipif(os.name != "nt", reason="Windows handle confinement")
def test_windows_open_confined_file_reads_and_closes(tmp_path: Path):
    root = tmp_path / "docs"
    root.mkdir()
    (root / "safe.txt").write_text("safe")
    roots = [AllowedRoot(root_id="docs", path=str(root))]
    with open_confined_file("docs", "safe.txt", roots) as handle:
        assert handle.read() == b"safe"
    assert handle.closed


@pytest.mark.skipif(os.name != "nt", reason="Windows handle confinement")
def test_windows_open_confined_file_rejects_symlink_outside(tmp_path: Path):
    root = tmp_path / "docs"
    root.mkdir()
    outside = tmp_path / "outside.txt"
    outside.write_text("outside")
    try:
        (root / "escape.txt").symlink_to(outside)
    except OSError:
        pytest.skip("symlink creation unavailable")
    with (
        pytest.raises(PathOutsideAllowedRoots),
        open_confined_file("docs", "escape.txt", [AllowedRoot(root_id="docs", path=str(root))]),
    ):
        pass


@pytest.mark.skipif(os.name != "nt", reason="Windows handle confinement")
def test_windows_open_confined_file_rejects_other_allowed_root(tmp_path: Path):
    first = tmp_path / "first"
    second = tmp_path / "second"
    first.mkdir()
    second.mkdir()
    (second / "secret.txt").write_text("secret")
    try:
        (first / "to-second").symlink_to(second, target_is_directory=True)
    except OSError:
        pytest.skip("symlink creation unavailable")
    roots = [
        AllowedRoot(root_id="first", path=str(first)),
        AllowedRoot(root_id="second", path=str(second)),
    ]
    with (
        pytest.raises(PathOutsideAllowedRoots),
        open_confined_file("first", "to-second/secret.txt", roots),
    ):
        pass


@pytest.mark.skipif(os.name != "nt", reason="Windows handle confinement")
def test_windows_browse_uses_native_handle_enumerator(tmp_path: Path, monkeypatch):
    root = tmp_path / "docs"
    child = root / "child"
    child.mkdir(parents=True)
    (child / "safe.txt").write_text("safe")
    monkeypatch.setattr(paths, "_windows_directory_names", lambda handle: ["safe.txt"])
    entries = browse("docs", "child", [AllowedRoot(root_id="docs", path=str(root))])
    assert [entry.name for entry in entries] == ["safe.txt"]


@pytest.mark.skipif(os.name == "nt", reason="requires POSIX dirfd semantics")
def test_open_confined_file_is_pinned_when_ancestor_is_replaced(tmp_path: Path, monkeypatch):
    root = tmp_path / "docs"
    child = root / "child"
    child.mkdir(parents=True)
    (child / "safe.txt").write_text("safe")
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "safe.txt").write_text("outside")
    original_open = os.open

    def open_then_swap(path, flags, *args, **kwargs):
        descriptor = original_open(path, flags, *args, **kwargs)
        if path == "child" and "dir_fd" in kwargs:
            child.rename(root / "old-child")
            (root / "child").symlink_to(outside, target_is_directory=True)
        return descriptor

    monkeypatch.setattr("onesearch_agent.paths.os.open", open_then_swap)
    roots = [AllowedRoot(root_id="docs", path=str(root))]
    with open_confined_file("docs", "child/safe.txt", roots) as handle:
        assert handle.read() == b"safe"


@pytest.mark.skipif(os.name == "nt", reason="requires POSIX dirfd semantics")
def test_open_confined_file_rejects_symlink_and_closes_file(tmp_path: Path):
    root = tmp_path / "docs"
    root.mkdir()
    outside = tmp_path / "outside.txt"
    outside.write_text("outside")
    (root / "escape.txt").symlink_to(outside)
    roots = [AllowedRoot(root_id="docs", path=str(root))]
    with pytest.raises(PathOutsideAllowedRoots), open_confined_file("docs", "escape.txt", roots):
        pass
    (root / "safe.txt").write_text("safe")
    with open_confined_file("docs", "safe.txt", roots) as handle:
        assert not handle.closed
    assert handle.closed
