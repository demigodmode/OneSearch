# Copyright (C) 2026 demigodmode
# SPDX-License-Identifier: AGPL-3.0-only

"""Tests for the local source folder picker's directory lister."""
import os

import pytest

from app.services import local_browse
from app.services.local_browse import LocalBrowseError, list_local_directories


def _names(page):
    return [entry.name for entry in page.entries]


def test_lists_only_directories_sorted_case_insensitively(tmp_path):
    for name in ["beta", "Alpha", "gamma"]:
        (tmp_path / name).mkdir()
    (tmp_path / "file.txt").write_text("x")

    page = list_local_directories(tmp_path, "")

    assert _names(page) == ["Alpha", "beta", "gamma"]
    assert [entry.path for entry in page.entries] == ["Alpha", "beta", "gamma"]
    assert page.truncated is False


def test_child_paths_are_relative_to_the_root(tmp_path):
    (tmp_path / "photos" / "2024" / "jan").mkdir(parents=True)

    page = list_local_directories(tmp_path, "photos/2024")

    assert [entry.path for entry in page.entries] == ["photos/2024/jan"]


def test_truncates_at_max_entries(tmp_path):
    for index in range(5):
        (tmp_path / f"d{index}").mkdir()

    page = list_local_directories(tmp_path, "", max_entries=3)

    assert _names(page) == ["d0", "d1", "d2"]
    assert page.truncated is True


def test_truncates_at_scan_budget(tmp_path):
    for index in range(5):
        (tmp_path / f"d{index}").mkdir()

    page = list_local_directories(tmp_path, "", scan_budget=2)

    assert len(page.entries) <= 2
    assert page.truncated is True


def test_symlinked_child_directory_is_hidden(tmp_path):
    root = tmp_path / "root"
    outside = tmp_path / "outside"
    (root / "real").mkdir(parents=True)
    outside.mkdir()
    (root / "escape").symlink_to(outside, target_is_directory=True)

    assert _names(list_local_directories(root, "")) == ["real"]


@pytest.mark.parametrize("relative", ["escape", "escape/secret", "real/escape/secret"])
def test_symlink_as_intermediate_relative_part_is_refused(tmp_path, relative):
    # symlink in the middle of the path, not just at the end
    root = tmp_path / "root"
    outside = tmp_path / "outside"
    (root / "real").mkdir(parents=True)
    (outside / "secret").mkdir(parents=True)
    (root / "escape").symlink_to(outside, target_is_directory=True)
    (root / "real" / "escape").symlink_to(outside, target_is_directory=True)

    with pytest.raises(LocalBrowseError):
        list_local_directories(root, relative)


def test_root_configured_as_symlink_still_browses(tmp_path):
    real = tmp_path / "real"
    (real / "docs").mkdir(parents=True)
    link = tmp_path / "data"
    link.symlink_to(real, target_is_directory=True)

    assert _names(list_local_directories(link, "")) == ["docs"]


def test_intermediate_root_component_swapped_for_symlink_is_refused(tmp_path, monkeypatch):
    # Simulate the race: at resolve time "mnt" was a real dir, by open time it's a symlink.
    outside = tmp_path / "outside"
    (outside / "data" / "secret").mkdir(parents=True)
    (tmp_path / "mnt").symlink_to(outside, target_is_directory=True)
    root = tmp_path / "mnt" / "data"
    monkeypatch.setattr(local_browse, "_resolve_root", lambda path: path)

    with pytest.raises(LocalBrowseError):
        list_local_directories(root, "")


def test_missing_folder_raises(tmp_path):
    with pytest.raises(LocalBrowseError):
        list_local_directories(tmp_path, "nope")


def test_missing_root_raises(tmp_path):
    with pytest.raises(LocalBrowseError):
        list_local_directories(tmp_path / "gone", "")


@pytest.mark.skipif(os.name != "posix" or os.geteuid() == 0, reason="permission bits don't apply to root")
def test_unreadable_folder_raises(tmp_path):
    locked = tmp_path / "locked"
    locked.mkdir()
    locked.chmod(0)
    try:
        with pytest.raises(LocalBrowseError):
            list_local_directories(tmp_path, "locked")
    finally:
        locked.chmod(0o755)


@pytest.mark.parametrize("relative", ["..", "a/../b", "/etc", "./a", "a\x00b", "a\x01b"])
def test_rejects_unsafe_relative_paths(tmp_path, relative):
    (tmp_path / "a").mkdir()
    with pytest.raises(LocalBrowseError):
        list_local_directories(tmp_path, relative)


def test_names_the_api_cannot_return_do_not_crowd_out_valid_ones(tmp_path):
    # Linux allows these; the browse wire contract (BrowseDirectoryEntry) doesn't.
    for name in [" leading-space", "back\\slash", "trailing-space "]:
        (tmp_path / name).mkdir()
    (tmp_path / "zz-valid").mkdir()

    page = list_local_directories(tmp_path, "", max_entries=1)

    assert _names(page) == ["zz-valid"]
    assert page.truncated is False


def test_error_carries_no_os_detail(tmp_path):
    with pytest.raises(LocalBrowseError) as caught:
        list_local_directories(tmp_path, "nope")
    assert str(tmp_path) not in str(caught.value)


def test_scan_budget_exact_boundary_not_truncated(tmp_path):
    for index in range(5):
        (tmp_path / f"d{index}").mkdir()

    page = list_local_directories(tmp_path, "", scan_budget=5)

    assert len(page.entries) == 5
    assert page.truncated is False


def test_scan_budget_one_under_is_truncated(tmp_path):
    for index in range(5):
        (tmp_path / f"d{index}").mkdir()

    page = list_local_directories(tmp_path, "", scan_budget=4)

    assert len(page.entries) <= 4
    assert page.truncated is True


def test_max_entries_exact_boundary_not_truncated(tmp_path):
    for index in range(3):
        (tmp_path / f"d{index}").mkdir()

    page = list_local_directories(tmp_path, "", max_entries=3)

    assert len(page.entries) == 3
    assert page.truncated is False


@pytest.mark.skipif(os.name != "posix" or os.geteuid() == 0, reason="permission bits don't apply to root")
def test_root_under_execute_only_parent_still_browses(tmp_path):
    parent = tmp_path / "parent"
    root = parent / "root"
    (root / "child").mkdir(parents=True)
    parent.chmod(0o311)
    try:
        assert _names(list_local_directories(root, "")) == ["child"]
    finally:
        parent.chmod(0o755)


@pytest.mark.skipif(not os.path.isdir("/proc/self/fd"), reason="requires /proc/self/fd (Linux)")
def test_does_not_leak_file_descriptors(tmp_path):
    root = tmp_path / "root"
    outside = tmp_path / "outside"
    (root / "real").mkdir(parents=True)
    (outside / "secret").mkdir(parents=True)
    (root / "escape").symlink_to(outside, target_is_directory=True)
    (root / "a-file").write_text("x")

    def open_fd_count() -> int:
        return len(os.listdir("/proc/self/fd"))

    baseline = open_fd_count()

    with pytest.raises(LocalBrowseError):
        list_local_directories(tmp_path, "nope")
    with pytest.raises(LocalBrowseError):
        list_local_directories(root, "escape")
    with pytest.raises(LocalBrowseError):
        list_local_directories(root, "a-file")
    with pytest.raises(LocalBrowseError):
        list_local_directories(root, "escape/secret")
    list_local_directories(root, "")

    assert open_fd_count() == baseline
