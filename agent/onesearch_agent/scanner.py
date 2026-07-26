"""Safe, deterministic manifest creation for on-agent scan jobs."""

from __future__ import annotations

from collections.abc import Iterator

from onesearch_shared import ScanFailure, ScanFile, ScanManifest, remote_path_hash

from app.services.scanner import get_default_exclude_patterns, path_is_included

from .paths import PathOutsideAllowedRoots, SafeDirectoryEntry, list_confined_entries_page


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
    def __init__(
        self,
        root_id,
        roots,
        *,
        include_patterns=None,
        exclude_patterns=None,
        known=None,
        max_files=100000,
        max_entries_per_directory=100000,
    ):
        self.root_id, self.roots = root_id, roots
        self.include_patterns = ["**/*"] if include_patterns is None else include_patterns
        self.exclude_patterns = (
            get_default_exclude_patterns() if exclude_patterns is None else exclude_patterns
        )
        self.known = known or {}
        self.changed_paths: list[str] = []
        self.max_files, self.max_entries_per_directory = max_files, max_entries_per_directory

    def _included(self, path: str) -> bool:
        return path_is_included(path, self.include_patterns, [])

    def _excluded(self, path: str) -> bool:
        return not path_is_included(path, ["**/*"], self.exclude_patterns)

    def _walk(self) -> Iterator[SafeDirectoryEntry]:
        def entries_for(directory: str) -> Iterator[SafeDirectoryEntry]:
            page = list_confined_entries_page(
                self.root_id, directory, self.roots, max_entries=self.max_entries_per_directory
            )
            if page.truncated:
                raise PathOutsideAllowedRoots(
                    f"directory entry limit exceeded: {directory or 'root'}"
                )
            if page.failures:
                failure = page.failures[0]
                raise PathOutsideAllowedRoots(f"{failure.relative_path}: {failure.error}"[:500])
            return iter(sorted(page.entries, key=lambda entry: entry.relative_path))

        stack = [entries_for("")]
        while stack:
            try:
                entry = next(stack[-1])
            except StopIteration:
                stack.pop()
                continue
            if entry.is_dir:
                if not self._excluded(entry.relative_path):
                    stack.append(entries_for(entry.relative_path))
                continue
            yield entry

    def scan(self, *, job_id: str, source_id: str) -> ScanManifest:
        files, failures = [], []
        self.changed_paths = []
        try:
            for entry in self._walk():
                path = entry.relative_path
                if not self._included(path) or self._excluded(path):
                    continue
                item = ScanFile(
                    path=path,
                    path_hash=remote_path_hash(path),
                    size_bytes=entry.size_bytes,
                    modified_at=entry.modified_at_ns,
                    content_hash=None,
                )
                files.append(item)
                if len(files) > self.max_files:
                    failures.append(ScanFailure(path=path, error="scan file limit exceeded"))
                    return ScanManifest(
                        job_id=job_id,
                        source_id=source_id,
                        files=files[:-1],
                        changed_paths=list(self.changed_paths),
                        failures=failures,
                        complete=False,
                    )
                old = self.known.get(path)
                if (
                    old is None
                    or old.get("status", "success") != "success"
                    or old.get("size_bytes") != item.size_bytes
                    or old.get("modified_at") != item.modified_at
                ):
                    self.changed_paths.append(path)
        except PathOutsideAllowedRoots as error:
            return ScanManifest(
                job_id=job_id,
                source_id=source_id,
                files=[],
                changed_paths=list(self.changed_paths),
                failures=[ScanFailure(path="scan", error=str(error)[:500])],
                complete=False,
            )
        return ScanManifest(
            job_id=job_id,
            source_id=source_id,
            files=files,
            changed_paths=list(self.changed_paths),
            failures=failures,
            complete=True,
        )
