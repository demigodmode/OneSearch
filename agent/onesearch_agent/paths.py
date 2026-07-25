"""Filesystem confinement helpers for future agent jobs."""

from __future__ import annotations

from pathlib import Path

from onesearch_shared import AllowedRoot


class PathOutsideAllowedRoots(ValueError):  # noqa: N818
    pass


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
    return resolve_allowed_path(_root(root_id, roots) / path, roots)


def browse(root_id: str, relative: str, roots: list[AllowedRoot], max_entries: int = 200):
    directory = resolve_relative_path(root_id, relative, roots)
    if not directory.is_dir():
        raise PathOutsideAllowedRoots("path is not a directory")
    safe = []
    for entry in sorted(directory.iterdir(), key=lambda item: item.name.casefold()):
        try:
            resolve_allowed_path(entry, roots)
        except PathOutsideAllowedRoots:
            continue
        safe.append(entry)
        if len(safe) >= max_entries:
            break
    return safe
