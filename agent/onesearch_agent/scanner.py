"""Safe, deterministic manifest creation for on-agent scan jobs."""

from __future__ import annotations

from collections.abc import Iterator

from app.services.scanner import get_default_exclude_patterns, path_is_included

from .paths import (
    PathOutsideAllowedRoots,
    SafeDirectoryEntry,
    confined_relative,
    iter_confined_entries,
    list_confined_entries_page,
)
from .scan_spool import ScanSpool


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
        source_prefix="",
        max_entries_per_directory=100000,
    ):
        self.root_id, self.roots = root_id, roots
        self.include_patterns = ["**/*"] if include_patterns is None else include_patterns
        self.exclude_patterns = (
            get_default_exclude_patterns() if exclude_patterns is None else exclude_patterns
        )
        self.source_prefix = confined_relative("", source_prefix)
        self.max_entries_per_directory = max_entries_per_directory

    def _included(self, path: str) -> bool:
        return path_is_included(path, self.include_patterns, [])

    def _excluded(self, path: str) -> bool:
        return not path_is_included(path, ["**/*"], self.exclude_patterns)

    def _walk(self) -> Iterator[SafeDirectoryEntry]:
        def entries_for(directory: str) -> Iterator[SafeDirectoryEntry]:
            allowed_directory = confined_relative(self.source_prefix, directory)
            page = list_confined_entries_page(
                self.root_id,
                allowed_directory,
                self.roots,
                max_entries=self.max_entries_per_directory,
            )
            if page.truncated:
                raise PathOutsideAllowedRoots(
                    f"directory entry limit exceeded: {directory or 'root'}"
                )
            if page.failures:
                failure = page.failures[0]
                raise PathOutsideAllowedRoots(f"{failure.relative_path}: {failure.error}"[:500])
            prefix = f"{self.source_prefix}/" if self.source_prefix else ""
            entries = []
            for entry in page.entries:
                if prefix and not entry.relative_path.startswith(prefix):
                    raise PathOutsideAllowedRoots("listed path escaped selected source")
                source_path = entry.relative_path[len(prefix) :]
                entries.append(
                    SafeDirectoryEntry(
                        source_path,
                        entry.name,
                        entry.is_dir,
                        entry.size_bytes,
                        entry.modified_at_ns,
                    )
                )
            return iter(sorted(entries, key=lambda entry: entry.relative_path))

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

    def scan_v3(
        self, *, state_dir, job_id: str, source_id: str, payload_identity: str, resume: bool = False
    ) -> ScanSpool:
        """Durably traverse the selected source and return its resumable v3 inventory."""
        if resume or ScanSpool.lifecycle_exists(state_dir, job_id):
            spool = ScanSpool.resume(
                state_dir, job_id=job_id, payload_identity=payload_identity, source_id=source_id
            )
        else:
            spool = ScanSpool.create(
                state_dir, job_id=job_id, payload_identity=payload_identity, source_id=source_id
            )
        if spool.finished:
            return spool
        spool.clear_incomplete()
        try:
            spool.enqueue_directory("")
            while (directory := spool.next_directory()) is not None:
                root_directory = confined_relative(self.source_prefix, directory)
                for entry in iter_confined_entries(self.root_id, root_directory, self.roots):
                    prefix = f"{self.source_prefix}/" if self.source_prefix else ""
                    if prefix and not entry.relative_path.startswith(prefix):
                        raise PathOutsideAllowedRoots("listed path escaped selected source")
                    path = entry.relative_path[len(prefix) :]
                    spool.observe_directory_member(
                        directory, path, entry.is_dir, entry.size_bytes, entry.modified_at_ns
                    )
                spool.seal_directory_membership(directory)
                for path, is_dir, size_bytes, modified_at_ns in spool.directory_members(directory):
                    if is_dir:
                        if not self._excluded(path):
                            spool.enqueue_directory(path)
                    elif self._included(path) and not self._excluded(path):
                        spool.append_file(path, size_bytes, modified_at_ns)
                spool.complete_directory(directory)
            spool.finish()
            return spool
        except Exception:
            spool.close()
            raise
