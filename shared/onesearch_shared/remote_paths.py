"""Lexical mapping between a remote source and an agent's advertised roots."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from pathlib import PurePosixPath, PureWindowsPath


class RemotePathError(ValueError):
    """The remote source cannot be mapped to one unambiguous allowed root."""


def _field(root: object, name: str) -> object:
    if isinstance(root, Mapping):
        return root.get(name)
    return getattr(root, name, None)


def _parse_path(platform: str, value: object):
    if not isinstance(value, str) or not value or value != value.strip() or "\0" in value:
        raise RemotePathError("invalid remote path")
    windows = platform.lower().startswith("win")
    separator, wrong_separator = ("\\", "/") if windows else ("/", "\\")
    if wrong_separator in value:
        raise RemotePathError("remote path uses the wrong separator")
    path_class = PureWindowsPath if windows else PurePosixPath
    path = path_class(value)
    if not path.is_absolute() or any(part in {".", ".."} for part in value.split(separator)):
        raise RemotePathError("remote path is not absolute and normalized")
    return path


def resolve_remote_source_root(
    platform: str, source_path: str, roots: Sequence[object]
) -> tuple[str, str]:
    """Return the most-specific root id and its source-relative prefix."""
    source = _parse_path(platform, source_path)
    if not isinstance(roots, Sequence) or isinstance(roots, (str, bytes)) or not roots:
        raise RemotePathError("allowed roots are unavailable")

    parsed: list[tuple[str, object]] = []
    root_ids: set[str] = set()
    root_paths: set[object] = set()
    for root in roots:
        root_id = _field(root, "root_id")
        if not isinstance(root_id, str) or not root_id or root_id != root_id.strip():
            raise RemotePathError("invalid allowed root id")
        path = _parse_path(platform, _field(root, "path"))
        if root_id in root_ids or path in root_paths:
            raise RemotePathError("ambiguous allowed roots")
        root_ids.add(root_id)
        root_paths.add(path)
        parsed.append((root_id, path))

    matches = []
    for root_id, root in parsed:
        try:
            relative = source.relative_to(root)
        except ValueError:
            continue
        matches.append((len(root.parts), root_id, relative))
    if not matches:
        raise RemotePathError("remote path is outside allowed roots")
    _depth, root_id, relative = max(matches, key=lambda item: item[0])
    return root_id, relative.as_posix() if relative.parts else ""
