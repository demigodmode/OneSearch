"""Durable, bounded protocol-v3 scan inventories."""

from __future__ import annotations

import hashlib
import sqlite3
from pathlib import Path

from onesearch_shared import (
    REMOTE_MAX_MANIFEST_PAGE_BYTES,
    REMOTE_MAX_MANIFEST_PAGE_ENTRIES,
    ScanCheckpoint,
    ScanFile,
    ScanManifestPage,
    ScanManifestPagePayload,
    canonical_wire_bytes,
    remote_path_hash,
)


class ScanSpoolError(RuntimeError):
    """A persisted scan cannot safely be resumed."""


class ScanSpool:
    """Append an inventory to SQLite and reproduce bounded, checksummed pages."""

    def __init__(self, connection: sqlite3.Connection, *, job_id: str, source_id: str):
        self._connection = connection
        self.job_id = job_id
        self.source_id = source_id

    @classmethod
    def open(
        cls, state_dir: Path, *, job_id: str, payload_identity: str, source_id: str
    ) -> ScanSpool:
        if not job_id or not payload_identity or not source_id:
            raise ScanSpoolError("scan spool identity is incomplete")
        directory = state_dir / "scan-spool"
        directory.mkdir(mode=0o700, parents=True, exist_ok=True)
        key = hashlib.sha256(job_id.encode()).hexdigest()
        path = directory / f"{key}.sqlite3"
        try:
            if path.exists():
                with path.open("rb") as handle:
                    if handle.read(16) != b"SQLite format 3\x00":
                        raise ScanSpoolError("scan spool is unavailable or corrupt")
            connection = sqlite3.connect(path)
            connection.execute("PRAGMA journal_mode=WAL")
            connection.execute("PRAGMA synchronous=FULL")
            connection.execute(
                "CREATE TABLE IF NOT EXISTS metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL)"
            )
            connection.execute(
                "CREATE TABLE IF NOT EXISTS files (position INTEGER PRIMARY KEY, path TEXT UNIQUE NOT NULL, size_bytes INTEGER NOT NULL, modified_at INTEGER NOT NULL)"
            )
            connection.execute(
                "CREATE TABLE IF NOT EXISTS directories (path TEXT PRIMARY KEY, state TEXT NOT NULL)"
            )
            connection.execute(
                "CREATE TABLE IF NOT EXISTS pages (sequence INTEGER PRIMARY KEY, start_position INTEGER NOT NULL, next_position INTEGER NOT NULL)"
            )
            existing = dict(connection.execute("SELECT key, value FROM metadata"))
            required = {
                "job_id": job_id,
                "payload_identity": payload_identity,
                "source_id": source_id,
            }
            if existing and any(existing.get(key) != value for key, value in required.items()):
                raise ScanSpoolError("scan spool payload mismatch")
            if not existing:
                connection.executemany(
                    "INSERT INTO metadata(key, value) VALUES (?, ?)", required.items()
                )
                connection.execute("INSERT INTO metadata(key, value) VALUES ('finished', '0')")
                connection.commit()
            return cls(connection, job_id=job_id, source_id=source_id)
        except (sqlite3.DatabaseError, OSError) as error:
            raise ScanSpoolError("scan spool is unavailable or corrupt") from error

    def append_file(self, path: str, size_bytes: int, modified_at: int) -> None:
        try:
            if self._value("finished") != "0":
                raise ScanSpoolError("scan spool is already finished")
            position = int(self._connection.execute("SELECT COUNT(*) FROM files").fetchone()[0])
            existing = self._connection.execute(
                "SELECT size_bytes, modified_at FROM files WHERE path = ?", (path,)
            ).fetchone()
            if existing is not None:
                if tuple(existing) != (size_bytes, modified_at):
                    raise ScanSpoolError("scan inventory changed while resuming")
                return
            self._connection.execute(
                "INSERT INTO files(position, path, size_bytes, modified_at) VALUES (?, ?, ?, ?)",
                (position, path, size_bytes, modified_at),
            )
            self._connection.commit()
        except sqlite3.DatabaseError as error:
            raise ScanSpoolError("scan spool write failed") from error

    def append_files(self, files) -> None:
        """Consume an inventory iterator into SQLite without retaining it in memory."""
        try:
            if self._value("finished") != "0":
                raise ScanSpoolError("scan spool is already finished")
            position = int(self._connection.execute("SELECT COUNT(*) FROM files").fetchone()[0])
            for path, size_bytes, modified_at in files:
                self._connection.execute(
                    "INSERT INTO files(position, path, size_bytes, modified_at) VALUES (?, ?, ?, ?)",
                    (position, path, size_bytes, modified_at),
                )
                position += 1
            self._connection.commit()
        except sqlite3.DatabaseError as error:
            self._connection.rollback()
            raise ScanSpoolError("scan spool write failed") from error

    def finish(self) -> None:
        try:
            self._connection.execute("UPDATE metadata SET value = '1' WHERE key = 'finished'")
            self._connection.commit()
        except sqlite3.DatabaseError as error:
            raise ScanSpoolError("scan spool write failed") from error

    @property
    def finished(self) -> bool:
        return self._value("finished") == "1"

    def enqueue_directory(self, path: str) -> None:
        try:
            self._connection.execute(
                "INSERT OR IGNORE INTO directories(path, state) VALUES (?, 'pending')", (path,)
            )
            self._connection.commit()
        except sqlite3.DatabaseError as error:
            raise ScanSpoolError("scan spool write failed") from error

    def next_directory(self) -> str | None:
        try:
            row = self._connection.execute(
                "SELECT path FROM directories WHERE state IN ('pending', 'processing') ORDER BY path LIMIT 1"
            ).fetchone()
            if row is None:
                return None
            self._connection.execute(
                "UPDATE directories SET state = 'processing' WHERE path = ?", row
            )
            self._connection.commit()
            return str(row[0])
        except sqlite3.DatabaseError as error:
            raise ScanSpoolError("scan spool read failed") from error

    def complete_directory(self, path: str) -> None:
        try:
            self._connection.execute(
                "UPDATE directories SET state = 'complete' WHERE path = ?", (path,)
            )
            self._connection.commit()
        except sqlite3.DatabaseError as error:
            raise ScanSpoolError("scan spool write failed") from error

    def page(self, sequence: int) -> ScanManifestPage:
        if sequence < 0 or self._value("finished") != "1":
            raise ScanSpoolError("scan spool is not ready for pages")
        try:
            for prior in range(sequence):
                if (
                    self._connection.execute(
                        "SELECT 1 FROM pages WHERE sequence = ?", (prior,)
                    ).fetchone()
                    is None
                ):
                    self.page(prior)
            stored = self._connection.execute(
                "SELECT start_position FROM pages WHERE sequence = ?", (sequence,)
            ).fetchone()
            rows = self._connection.execute(
                "SELECT path, size_bytes, modified_at FROM files WHERE position >= ? ORDER BY position LIMIT ?",
                (
                    int(stored[0]) if stored else self._page_start(sequence),
                    REMOTE_MAX_MANIFEST_PAGE_ENTRIES,
                ),
            ).fetchall()
            total = int(self._connection.execute("SELECT COUNT(*) FROM files").fetchone()[0])
        except sqlite3.DatabaseError as error:
            raise ScanSpoolError("scan spool read failed") from error
        offset = int(stored[0]) if stored else self._page_start(sequence)
        if offset > total or (offset == total and total and sequence):
            raise ScanSpoolError("scan page is beyond inventory")
        files: list[ScanFile] = []
        for path, size_bytes, modified_at in rows:
            candidate = ScanFile(
                path=path,
                path_hash=remote_path_hash(path),
                size_bytes=size_bytes,
                modified_at=modified_at,
                content_hash=None,
            )
            page = self._make_page(
                sequence,
                [*files, candidate],
                offset + len(files) + 1 >= total,
                offset + len(files) + 1,
            )
            if len(canonical_wire_bytes(page)) > REMOTE_MAX_MANIFEST_PAGE_BYTES:
                if not files:
                    raise ScanSpoolError("single scan entry exceeds page byte limit")
                break
            files.append(candidate)
        final = offset + len(files) >= total
        result = self._make_page(sequence, files, final, offset + len(files))
        try:
            self._connection.execute(
                "INSERT OR REPLACE INTO pages(sequence, start_position, next_position) VALUES (?, ?, ?)",
                (sequence, offset, offset + len(files)),
            )
            self._connection.commit()
        except sqlite3.DatabaseError as error:
            raise ScanSpoolError("scan spool write failed") from error
        return result

    def _page_start(self, sequence: int) -> int:
        if sequence == 0:
            return 0
        row = self._connection.execute(
            "SELECT next_position FROM pages WHERE sequence = ?", (sequence - 1,)
        ).fetchone()
        if row is None:
            raise ScanSpoolError("scan spool page cursor is corrupt")
        return int(row[0])

    def _make_page(
        self, sequence: int, files: list[ScanFile], final: bool, scanned_count: int
    ) -> ScanManifestPage:
        payload = ScanManifestPagePayload(
            job_id=self.job_id,
            source_id=self.source_id,
            sequence=sequence,
            files=files,
            checkpoint=ScanCheckpoint(cursor=f"page:{sequence}", scanned_count=scanned_count),
            final=final,
        )
        return ScanManifestPage(
            checksum=hashlib.sha256(canonical_wire_bytes(payload)).hexdigest(), page=payload
        )

    def _value(self, key: str) -> str:
        row = self._connection.execute(
            "SELECT value FROM metadata WHERE key = ?", (key,)
        ).fetchone()
        if row is None:
            raise ScanSpoolError("scan spool metadata is corrupt")
        return str(row[0])

    def close(self) -> None:
        self._connection.close()
