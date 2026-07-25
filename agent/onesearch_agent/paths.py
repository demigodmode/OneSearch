"""Filesystem confinement helpers for future agent jobs."""

from __future__ import annotations

import ntpath
import os
import stat
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO

from onesearch_shared import AllowedRoot


class PathOutsideAllowedRoots(ValueError):  # noqa: N818
    pass


@dataclass(frozen=True)
class SafeDirectoryEntry:
    relative_path: str
    name: str
    is_dir: bool
    size_bytes: int
    modified_at_ns: int


def list_confined_entries(
    root_id: str, relative: str, roots: list[AllowedRoot], max_entries: int = 200
) -> list[SafeDirectoryEntry]:
    """Return metadata derived solely from no-follow handles, never host Paths."""
    if os.name == "nt":
        # `browse` obtains each name from rooted native handles; reopen that name
        # through the same confined boundary solely to derive metadata from its fd.
        result = []
        for display in browse(root_id, relative, roots, max_entries=max_entries):
            path = f"{relative}/{display.name}".strip("/")
            try:
                with open_confined_file(root_id, path, roots) as handle:
                    info = os.fstat(handle.fileno())
                result.append(
                    SafeDirectoryEntry(
                        path,
                        display.name,
                        stat.S_ISDIR(info.st_mode),
                        info.st_size,
                        info.st_mtime_ns,
                    )
                )
            except (OSError, PathOutsideAllowedRoots):
                continue
        return result
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
    directory_fd = -1
    entries: list[SafeDirectoryEntry] = []
    try:
        directory_fd = os.open(_root(root_id, roots), flags)
        for part in _relative_parts(relative):
            child = os.open(part, flags, dir_fd=directory_fd)
            os.close(directory_fd)
            directory_fd = child
        for name in sorted(os.listdir(directory_fd), key=str.casefold)[:max_entries]:
            fd = -1
            try:
                fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC, dir_fd=directory_fd)
                info = os.fstat(fd)
                mode = info.st_mode
                if stat.S_ISLNK(mode) or not (stat.S_ISREG(mode) or stat.S_ISDIR(mode)):
                    continue
                path = f"{relative}/{name}".strip("/")
                entries.append(
                    SafeDirectoryEntry(
                        path, name, stat.S_ISDIR(mode), info.st_size, info.st_mtime_ns
                    )
                )
            except OSError:
                continue
            finally:
                if fd != -1:
                    os.close(fd)
        return entries
    except OSError as error:
        raise PathOutsideAllowedRoots("path cannot be listed safely") from error
    finally:
        if directory_fd != -1:
            os.close(directory_fd)


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
        file_fd = os.open(parts[-1], os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC, dir_fd=fd)
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
    kernel32.GetFileInformationByHandle.argtypes = [wintypes.HANDLE, wintypes.LPVOID]
    kernel32.GetFileInformationByHandle.restype = wintypes.BOOL
    kernel32.GetFileInformationByHandleEx.restype = wintypes.BOOL
    return ctypes, kernel32


def _windows_handle_metadata(handle) -> tuple[bool, int, int]:
    """Read directory, size and UTC nanoseconds from this exact native handle."""
    ctypes, kernel32 = _windows_kernel32()
    from ctypes import wintypes

    class BY_HANDLE_FILE_INFORMATION(ctypes.Structure):  # noqa: N801
        _fields_ = [
            ("dwFileAttributes", wintypes.DWORD),
            ("ftCreationTimeLowDateTime", wintypes.DWORD),
            ("ftCreationTimeHighDateTime", wintypes.DWORD),
            ("ftLastAccessTimeLowDateTime", wintypes.DWORD),
            ("ftLastAccessTimeHighDateTime", wintypes.DWORD),
            ("ftLastWriteTimeLowDateTime", wintypes.DWORD),
            ("ftLastWriteTimeHighDateTime", wintypes.DWORD),
            ("dwVolumeSerialNumber", wintypes.DWORD),
            ("nFileSizeHigh", wintypes.DWORD),
            ("nFileSizeLow", wintypes.DWORD),
            ("nNumberOfLinks", wintypes.DWORD),
            ("nFileIndexHigh", wintypes.DWORD),
            ("nFileIndexLow", wintypes.DWORD),
        ]

    info = BY_HANDLE_FILE_INFORMATION()
    if not kernel32.GetFileInformationByHandle(handle, ctypes.byref(info)):
        raise OSError(ctypes.get_last_error(), "cannot inspect file handle")
    ticks = int(info.ftLastWriteTimeLowDateTime) | (int(info.ftLastWriteTimeHighDateTime) << 32)
    if ticks < 116444736000000000:
        raise OSError("file timestamp predates Unix epoch")
    return (
        bool(info.dwFileAttributes & 0x10),
        (int(info.nFileSizeHigh) << 32) | int(info.nFileSizeLow),
        (ticks - 116444736000000000) * 100,
    )


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


def _windows_ntdll():
    """Return the small lazy ntdll surface needed for rooted directory access."""
    import ctypes
    from ctypes import wintypes

    class IO_STATUS_BLOCK(ctypes.Structure):  # noqa: N801
        _fields_ = [("Status", wintypes.LONG), ("Information", ctypes.c_size_t)]

    class UNICODE_STRING(ctypes.Structure):  # noqa: N801
        _fields_ = [
            ("Length", wintypes.USHORT),
            ("MaximumLength", wintypes.USHORT),
            ("Buffer", wintypes.LPWSTR),
        ]

    class OBJECT_ATTRIBUTES(ctypes.Structure):  # noqa: N801
        _fields_ = [
            ("Length", wintypes.ULONG),
            ("RootDirectory", wintypes.HANDLE),
            ("ObjectName", ctypes.POINTER(UNICODE_STRING)),
            ("Attributes", wintypes.ULONG),
            ("SecurityDescriptor", wintypes.LPVOID),
            ("SecurityQualityOfService", wintypes.LPVOID),
        ]

    ntdll = ctypes.WinDLL("ntdll")
    ntdll.NtQueryDirectoryFile.restype = wintypes.LONG
    ntdll.NtCreateFile.restype = wintypes.LONG
    ntdll.RtlNtStatusToDosError.restype = wintypes.ULONG
    return ctypes, ntdll, IO_STATUS_BLOCK, UNICODE_STRING, OBJECT_ATTRIBUTES


def _windows_nt_error(ntdll, status: int) -> OSError:
    return OSError(ntdll.RtlNtStatusToDosError(status), "native directory operation failed")


def _windows_directory_names(handle) -> list[str]:
    ctypes, ntdll, io_status_block, _unicode, _attributes = _windows_ntdll()
    buffer = ctypes.create_string_buffer(65536)
    iosb = io_status_block()
    names: list[str] = []
    restart = 1
    while True:
        status = ntdll.NtQueryDirectoryFile(
            handle,
            None,
            None,
            None,
            ctypes.byref(iosb),
            buffer,
            len(buffer),
            12,
            False,
            None,
            restart,
        )
        restart = 0
        if (status & 0xFFFFFFFF) == 0x80000006:  # STATUS_NO_MORE_FILES
            return names
        if status < 0:
            raise _windows_nt_error(ntdll, status)
        offset = 0
        while offset < iosb.Information:
            next_offset = int.from_bytes(buffer[offset : offset + 4], "little")
            name_length = int.from_bytes(buffer[offset + 8 : offset + 12], "little")
            name = bytes(buffer[offset + 12 : offset + 12 + name_length]).decode("utf-16-le")
            if name not in {".", ".."}:
                names.append(name)
            if not next_offset:
                break
            offset += next_offset


def _windows_open_relative(directory_handle, name: str):
    ctypes, ntdll, io_status_block, unicode_string, object_attributes = _windows_ntdll()
    text = ctypes.create_unicode_buffer(name)
    unicode = unicode_string(
        len(name.encode("utf-16-le")), (len(name) + 1) * 2, ctypes.cast(text, ctypes.c_wchar_p)
    )
    attributes = object_attributes(
        ctypes.sizeof(object_attributes),
        directory_handle,
        ctypes.pointer(unicode),
        0x40,
        None,
        None,
    )
    handle = ctypes.c_void_p()
    iosb = io_status_block()
    status = ntdll.NtCreateFile(
        ctypes.byref(handle),
        0x80 | 0x100000,
        ctypes.byref(attributes),
        ctypes.byref(iosb),
        None,
        0,
        1 | 2 | 4,
        1,
        0x20 | 0x200000,
        None,
        0,
    )
    if status < 0:
        raise _windows_nt_error(ntdll, status)
    return handle.value


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


def _windows_is_reparse_point(handle) -> bool:
    ctypes, kernel32 = _windows_kernel32()

    class AttributeTagInfo(ctypes.Structure):
        _fields_ = [("FileAttributes", ctypes.c_ulong), ("ReparseTag", ctypes.c_ulong)]

    info = AttributeTagInfo()
    if not kernel32.GetFileInformationByHandleEx(
        handle, 9, ctypes.byref(info), ctypes.sizeof(info)
    ):
        raise OSError(ctypes.get_last_error(), "cannot inspect file attributes")
    return bool(info.FileAttributes & 0x400)


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
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
    directory_fd = -1
    try:
        directory_fd = os.open(_root(root_id, roots), flags)
        for part in _relative_parts(relative):
            child_fd = os.open(part, flags, dir_fd=directory_fd)
            os.close(directory_fd)
            directory_fd = child_fd
        names = sorted(os.listdir(directory_fd), key=str.casefold)
        display_directory = _root(root_id, roots) / Path(relative)
        safe: list[Path] = []
        for name in names:
            child_fd = -1
            try:
                child_fd = os.open(
                    name, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC, dir_fd=directory_fd
                )
                safe.append(display_directory / name)
                if len(safe) >= max_entries:
                    break
            except OSError:
                continue
            finally:
                if child_fd != -1:
                    os.close(child_fd)
        return safe
    except OSError as error:
        raise PathOutsideAllowedRoots("path cannot be browsed safely") from error
    finally:
        if directory_fd != -1:
            os.close(directory_fd)


def _browse_windows(
    root_id: str, relative: str, roots: list[AllowedRoot], max_entries: int
) -> list[Path]:
    """Return display paths only after each entry has been verified by handle."""
    root_handle = directory_handle = None
    try:
        root_handle, root_path, directory_handle, directory_path = _windows_verified_directory(
            root_id, relative, roots
        )
        names = sorted(_windows_directory_names(directory_handle), key=str.casefold)
        display_directory = _root(root_id, roots) / Path(relative)
        safe: list[Path] = []
        for name in names:
            child_handle = None
            try:
                child_handle = _windows_open_relative(directory_handle, name)
                if _windows_is_reparse_point(child_handle):
                    continue
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
