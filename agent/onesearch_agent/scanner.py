"""Safe, deterministic manifest creation for on-agent scan jobs."""

from __future__ import annotations

import fnmatch
import hashlib
import os
from collections.abc import Iterator

from onesearch_shared import ScanFile, ScanManifest

from app.services.scanner import _match_exclude_pattern, get_default_exclude_patterns

from .paths import PathOutsideAllowedRoots, browse, open_confined_file


def canonical_path(path: str) -> str:
    """Return a protocol path, rejecting paths which could escape a root."""
    value = path.replace("\\", "/")
    if (
        not value
        or value.startswith("/")
        or any(part in {"", ".", ".."} for part in value.split("/"))
    ):
        raise PathOutsideAllowedRoots("invalid remote relative path")
    return value


class RemoteScanner:
    def __init__(self, root_id, roots, *, include_patterns=None, exclude_patterns=None, known=None):
        self.root_id, self.roots = root_id, roots
        self.include_patterns = include_patterns or ["**/*"]
        self.exclude_patterns = (
            get_default_exclude_patterns() if exclude_patterns is None else exclude_patterns
        )
        self.known = known or {}
        self.changed_paths: list[str] = []

    def _included(self, path: str) -> bool:
        return any(
            fnmatch.fnmatchcase(path, p)
            or (p.startswith("**/") and fnmatch.fnmatchcase(path, p[3:]))
            for p in self.include_patterns
        )

    def _excluded(self, path: str) -> bool:
        parts = path.split("/")
        candidates = ["/".join(parts[:index]) for index in range(len(parts), 0, -1)]
        return any(
            _match_exclude_pattern(candidate, pattern)
            for candidate in candidates
            for pattern in self.exclude_patterns
        )

    def _walk(self) -> Iterator[str]:
        stack = [""]
        while stack:
            directory = stack.pop()
            try:
                entries = browse(self.root_id, directory, self.roots, max_entries=100000)
            except PathOutsideAllowedRoots:
                continue
            for entry in reversed(entries):
                relative = canonical_path(
                    str(
                        entry.relative_to(
                            next(r for r in self.roots if r.root_id == self.root_id).path
                        )
                    )
                )
                try:
                    browse(self.root_id, relative, self.roots, max_entries=1)
                except PathOutsideAllowedRoots:
                    yield relative
                else:
                    stack.append(relative)

    def scan(self, *, job_id: str, source_id: str) -> ScanManifest:
        files = []
        self.changed_paths = []
        for path in sorted(self._walk()):
            if not self._included(path) or self._excluded(path):
                continue
            with open_confined_file(self.root_id, path, self.roots) as handle:
                stat = os.fstat(handle.fileno())
                digest = hashlib.sha256()
                for block in iter(lambda: handle.read(65536), b""):
                    digest.update(block)
            item = ScanFile(
                path=path,
                size_bytes=stat.st_size,
                modified_at=stat.st_mtime_ns,
                content_hash=digest.hexdigest(),
            )
            files.append(item)
            old = self.known.get(path)
            if (
                old is None
                or old.get("size_bytes") != item.size_bytes
                or old.get("modified_at") != item.modified_at
            ):
                self.changed_paths.append(path)
        return ScanManifest(job_id=job_id, source_id=source_id, files=files, complete=True)
