# Copyright (C) 2026 demigodmode
# SPDX-License-Identifier: AGPL-3.0-only

"""Bounded, symlink-safe directory listing for the local source folder picker.

Same approach as the agent's POSIX browse: walk with directory fds and
O_NOFOLLOW so no symlink anywhere in the chain is followed, list directories
only, and cap both how much we scan and how much we return.
"""

from __future__ import annotations

import heapq
import os
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from onesearch_shared import REMOTE_MAX_BROWSE_DIRECTORIES, BrowseDirectoryEntry

# getattr so this still imports on Windows (the agent depends on this package);
# browsing itself is refused there, see _SUPPORTED
_O_DIRECTORY = getattr(os, "O_DIRECTORY", 0)
_O_NOFOLLOW = getattr(os, "O_NOFOLLOW", 0)
_O_CLOEXEC = getattr(os, "O_CLOEXEC", 0)
_SUPPORTED = bool(_O_DIRECTORY and _O_NOFOLLOW) and os.open in os.supports_dir_fd
_DIR_FLAGS = os.O_RDONLY | _O_DIRECTORY | _O_NOFOLLOW | _O_CLOEXEC
# ancestors only need x, not r, so they aren't opened for reading (no O_PATH on macOS)
_PATH_FLAGS = getattr(os, "O_PATH", os.O_RDONLY) | _O_DIRECTORY | _O_NOFOLLOW | _O_CLOEXEC
DEFAULT_SCAN_BUDGET = 10_000


class LocalBrowseError(Exception):
    """The folder can't be listed safely. Deliberately carries no OS detail."""

    def __init__(self) -> None:
        super().__init__("folder cannot be listed")


@dataclass(frozen=True)
class LocalBrowsePage:
    entries: tuple[BrowseDirectoryEntry, ...]
    truncated: bool


def _resolve_root(root: Path) -> Path:
    # The configured root may itself be a symlink (admin config); this is the
    # only place links get followed.
    return root.resolve(strict=True)


def _relative_parts(relative: str) -> tuple[str, ...]:
    if relative == "":
        return ()
    has_control_char = any(ord(character) < 32 or ord(character) == 127 for character in relative)
    if (
        relative.startswith("/")
        or "\\" in relative
        or has_control_char
        or any(part in {"", ".", ".."} for part in relative.split("/"))
    ):
        raise LocalBrowseError()
    return PurePosixPath(relative).parts


def _open_confined(root: Path, relative: str) -> int:
    parts = _relative_parts(relative)
    resolved = _resolve_root(root)
    # Walk the resolved root from "/" one component at a time. A single
    # os.open(resolved, O_NOFOLLOW) only protects the last component; if a
    # parent got swapped for a symlink after resolve() it would be followed.
    all_parts = (*resolved.parts[1:], *parts)
    if not all_parts:
        # The resolved root is "/" itself; it's also the directory we scan.
        return os.open("/", os.O_RDONLY | _O_DIRECTORY | _O_CLOEXEC)
    fd = os.open("/", (_PATH_FLAGS & ~_O_NOFOLLOW))
    try:
        last_index = len(all_parts) - 1
        for index, part in enumerate(all_parts):
            flags = _DIR_FLAGS if index == last_index else _PATH_FLAGS
            child = os.open(part, flags, dir_fd=fd)
            os.close(fd)
            fd = child
    except BaseException:
        os.close(fd)
        raise
    return fd


def _entry(relative: str, name: str) -> BrowseDirectoryEntry | None:
    # Only names the API response can actually carry get a slot; otherwise
    # oddly named folders could fill the page and hide valid ones.
    try:
        name.encode("utf-8")
        return BrowseDirectoryEntry(name=name, path=f"{relative}/{name}".strip("/"))
    except (UnicodeEncodeError, ValueError):
        return None


def list_local_directories(
    root: Path,
    relative: str,
    *,
    max_entries: int = REMOTE_MAX_BROWSE_DIRECTORIES,
    scan_budget: int = DEFAULT_SCAN_BUDGET,
) -> LocalBrowsePage:
    if max_entries < 1 or scan_budget < 1:
        raise ValueError("browse limits must be positive")
    if not _SUPPORTED:
        raise LocalBrowseError()

    try:
        fd = _open_confined(Path(root), relative)
    except (OSError, ValueError) as error:
        raise LocalBrowseError() from error

    over_budget = False
    valid_count = 0

    def candidates(directory_fd: int):
        nonlocal over_budget, valid_count
        with os.scandir(directory_fd) as entries:
            for scanned, candidate in enumerate(entries, start=1):
                if scanned > scan_budget:
                    over_budget = True
                    return
                entry = _entry(relative, candidate.name)
                if entry is None:
                    continue
                try:
                    child = os.open(candidate.name, _DIR_FLAGS, dir_fd=directory_fd)
                except OSError:
                    # files, symlinks, vanished or unreadable entries
                    continue
                os.close(child)
                valid_count += 1
                yield entry

    try:
        selected = heapq.nsmallest(
            max_entries, candidates(fd), key=lambda entry: (entry.name.casefold(), entry.name)
        )
    except OSError as error:
        raise LocalBrowseError() from error
    finally:
        os.close(fd)

    return LocalBrowsePage(tuple(selected), over_budget or valid_count > max_entries)
