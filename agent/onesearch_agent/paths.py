"""Filesystem confinement helpers for future agent jobs."""

from __future__ import annotations

import ntpath
import os
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import BinaryIO

from onesearch_shared import AllowedRoot


class PathOutsideAllowedRoots(ValueError):  # noqa: N818
    pass


@contextmanager
def open_confined_file(
    root_id: str,
    relative: str,
    roots: list[AllowedRoot],
    mode: str = "rb",
) -> Iterator[BinaryIO]:
    """Open an already-confined file; returned paths must not be reopened by callers."""
    if os.name == "nt":
        with _open_confined_file_windows(root_id, relative, roots, mode) as handle:
            yield handle
        return
    if mode != "rb":
        raise ValueError("only binary read mode is supported")
    parts = Path(relative).parts
    if (
        not relative
        or "\\" in relative
        or Path(relative).is_absolute()
        or any(part in {".", ".."} for part in parts)
    ):
        raise PathOutsideAllowedRoots("invalid relative path")
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
    fd = -1
    file_fd = -1
    try:
        fd = os.open(_root(root_id, roots), flags)
        for part in parts[:-1]:
            child = os.open(part, flags, dir_fd=fd)
            os.close(fd)
            fd = child
        file_fd = os.open(
            parts[-1], os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC, dir_fd=fd
        )
        with os.fdopen(file_fd, "rb") as handle:
            file_fd = -1
            yield handle
    except OSError as error:
        raise PathOutsideAllowedRoots("path cannot be opened safely") from error
    finally:
        if file_fd != -1:
            os.close(file_fd)
        if fd != -1:
            os.close(fd)


def _relative_parts(relative: str) -> tuple[str, ...]:
    if relative == "":
        return ()
    parts = Path(relative).parts
    if (
        not relative
        or "\\" in relative
        or Path(relative).is_absolute()
        or any(part in {".", ".."} for part in parts)
    ):
        raise PathOutsideAllowedRoots("invalid relative path")
    return parts


def _windows_kernel32():
    """Load Win32 APIs lazily so non-Windows imports stay portable."""
    import ctypes
    from ctypes import wintypes

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.CreateFileW.argtypes = [
        wintypes.LPCWSTR,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.LPVOID,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.HANDLE,
    ]
    kernel32.CreateFileW.restype = wintypes.HANDLE
    kernel32.GetFinalPathNameByHandleW.argtypes = [
        wintypes.HANDLE,
        wintypes.LPWSTR,
        wintypes.DWORD,
        wintypes.DWORD,
    ]
    kernel32.GetFinalPathNameByHandleW.restype = wintypes.DWORD
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel32.CloseHandle.restype = wintypes.BOOL
    return ctypes, kernel32


def _windows_open(path: str):
    ctypes, kernel32 = _windows_kernel32()
    handle = kernel32.CreateFileW(
        path,
        0x80000000,  # GENERIC_READ
        0x00000001 | 0x00000002 | 0x00000004,  # share read/write/delete
        None,
        3,  # OPEN_EXISTING
        0x02000000,  # FILE_FLAG_BACKUP_SEMANTICS (also permits directories)
        None,
    )
    if handle == ctypes.c_void_p(-1).value:
        raise OSError(ctypes.get_last_error(), f"cannot open {path!r}")
    return handle


def _windows_close(handle) -> None:
    if handle is not None:
        _ctypes, kernel32 = _windows_kernel32()
        kernel32.CloseHandle(handle)


def _windows_final_path(handle) -> str:
    ctypes, kernel32 = _windows_kernel32()
    size = 260
    while True:
        buffer = ctypes.create_unicode_buffer(size)
        written = kernel32.GetFinalPathNameByHandleW(handle, buffer, size, 0)
        if not written:
            raise OSError(ctypes.get_last_error(), "cannot get final handle path")
        if written < size:
            return buffer.value
        size = written + 1


def _windows_normal_path(path: str) -> str:
    if path.startswith("\\\\?\\"):
        path = path[4:]
    return ntpath.normcase(ntpath.normpath(path))


def _windows_is_within(candidate: str, directory: str) -> bool:
    candidate = _windows_normal_path(candidate)
    directory = _windows_normal_path(directory)
    try:
        return ntpath.commonpath([candidate, directory]) == directory
    except ValueError:
        return False


def _windows_verified_directory(root_id: str, relative: str, roots: list[AllowedRoot]):
    root_handle = directory_handle = None
    try:
        root_handle = _windows_open(str(_root(root_id, roots)))
        root_path = _windows_final_path(root_handle)
        directory_handle = _windows_open(ntpath.join(root_path, *_relative_parts(relative)))
        directory_path = _windows_final_path(directory_handle)
        if not _windows_is_within(directory_path, root_path):
            raise PathOutsideAllowedRoots("path is outside selected root")
        return root_handle, root_path, directory_handle, directory_path
    except Exception:
        _windows_close(directory_handle)
        _windows_close(root_handle)
        raise


@contextmanager
def _open_confined_file_windows(
    root_id: str, relative: str, roots: list[AllowedRoot], mode: str
) -> Iterator[BinaryIO]:
    if mode != "rb":
        raise ValueError("only binary read mode is supported")
    root_handle = file_handle = None
    fd = -1
    try:
        root_handle = _windows_open(str(_root(root_id, roots)))
        root_path = _windows_final_path(root_handle)
        file_handle = _windows_open(ntpath.join(root_path, *_relative_parts(relative)))
        file_path = _windows_final_path(file_handle)
        if not _windows_is_within(file_path, root_path):
            raise PathOutsideAllowedRoots("path is outside selected root")
        import msvcrt

        fd = msvcrt.open_osfhandle(file_handle, os.O_RDONLY | os.O_BINARY)
        file_handle = None  # fd now owns the Win32 handle
        with os.fdopen(fd, "rb") as handle:
            fd = -1
            yield handle
    except OSError as error:
        raise PathOutsideAllowedRoots("path cannot be opened safely") from error
    finally:
        if fd != -1:
            os.close(fd)
        _windows_close(file_handle)
        _windows_close(root_handle)


def _root(root_id: str, roots: list[AllowedRoot]) -> Path:
    for root in roots:
        if root.root_id == root_id:
            return Path(root.path).resolve(strict=True)
    raise PathOutsideAllowedRoots("unknown allowed root")


def resolve_allowed_path(candidate: str | Path, roots: list[AllowedRoot]) -> Path:
    raw = Path(candidate)
    if ".." in raw.parts or not raw.exists():
        raise PathOutsideAllowedRoots("path is not safe")
    resolved = raw.resolve(strict=True)
    for item in roots:
        root = Path(item.path).resolve(strict=True)
        try:
            resolved.relative_to(root)
            return resolved
        except ValueError:
            pass
    raise PathOutsideAllowedRoots("path is outside allowed roots")


def resolve_relative_path(root_id: str, relative: str, roots: list[AllowedRoot]) -> Path:
    path = Path(relative)
    if path.is_absolute() or ".." in path.parts or "\\" in relative:
        raise PathOutsideAllowedRoots("invalid relative path")
    root = _root(root_id, roots)
    candidate = root / path
    resolved = resolve_allowed_path(candidate, roots)
    try:
        resolved.relative_to(root)
    except ValueError as error:
        raise PathOutsideAllowedRoots("path is outside selected root") from error
    return resolved


def browse(root_id: str, relative: str, roots: list[AllowedRoot], max_entries: int = 200):
    if os.name == "nt":
        return _browse_windows(root_id, relative, roots, max_entries)
    directory = resolve_relative_path(root_id, relative, roots)
    if not directory.is_dir():
        raise PathOutsideAllowedRoots("path is not a directory")
    safe = []
    for entry in sorted(directory.iterdir(), key=lambda item: item.name.casefold()):
        try:
            resolve_relative_path(root_id, str(entry.relative_to(_root(root_id, roots))), roots)
        except PathOutsideAllowedRoots:
            continue
        safe.append(entry)
        if len(safe) >= max_entries:
            break
    return safe


def _browse_windows(
    root_id: str, relative: str, roots: list[AllowedRoot], max_entries: int
) -> list[Path]:
    """Return display paths only after each entry has been verified by handle."""
    root_handle = directory_handle = None
    try:
        root_handle, root_path, directory_handle, directory_path = _windows_verified_directory(
            root_id, relative, roots
        )
        enumerated_path = directory_path
        names = sorted((entry.name for entry in os.scandir(enumerated_path)), key=str.casefold)
        # The name used for enumeration can be replaced after the handle was
        # opened.  Re-resolve the held handle before validating its children.
        directory_path = _windows_final_path(directory_handle)
        if not _windows_is_within(directory_path, root_path):
            raise PathOutsideAllowedRoots("path is outside selected root")
        display_directory = _root(root_id, roots) / Path(relative)
        safe: list[Path] = []
        for name in names:
            child_handle = None
            try:
                child_handle = _windows_open(ntpath.join(enumerated_path, name))
                child_path = _windows_final_path(child_handle)
                if not (
                    _windows_is_within(child_path, root_path)
                    and _windows_is_within(child_path, directory_path)
                ):
                    continue
                safe.append(display_directory / name)
                if len(safe) >= max_entries:
                    break
            except OSError:
                continue
            finally:
                _windows_close(child_handle)
        return safe
    except OSError as error:
        raise PathOutsideAllowedRoots("path cannot be browsed safely") from error
    finally:
        _windows_close(directory_handle)
        _windows_close(root_handle)
