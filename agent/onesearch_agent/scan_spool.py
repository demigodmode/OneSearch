"""Durable, bounded protocol-v3 scan inventories."""

from __future__ import annotations

import hashlib
import json
import os
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

_SCHEMA_VERSION = "3"


class ScanSpoolError(RuntimeError):
    """A persisted scan cannot safely be resumed."""


class ScanSpool:
    """Append an inventory to SQLite and reproduce bounded, checksummed pages."""

    def __init__(self, connection: sqlite3.Connection, *, job_id: str, source_id: str):
        self._connection = connection
        self.job_id = job_id
        self.source_id = source_id

    @classmethod
    def exists(cls, state_dir: Path, job_id: str) -> bool:
        return cls._spool_path(state_dir, job_id).is_file()

    @classmethod
    def lifecycle_exists(cls, state_dir: Path, job_id: str) -> bool:
        return cls._marker_path(state_dir, job_id).is_file()

    @classmethod
    def create(
        cls, state_dir: Path, *, job_id: str, payload_identity: str, source_id: str
    ) -> ScanSpool:
        """Atomically begin a new lifecycle; terminal-job cleanup owns marker removal later."""
        marker = cls._marker_path(state_dir, job_id)
        marker.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        payload = cls._marker_payload(job_id, payload_identity, source_id)
        try:
            descriptor = os.open(marker, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        except FileExistsError as error:
            raise ScanSpoolError("scan lifecycle already exists; resume is required") from error
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
                handle.write(json.dumps(payload, sort_keys=True, separators=(",", ":")))
                handle.flush()
                os.fsync(handle.fileno())
        except OSError as error:
            raise ScanSpoolError("scan lifecycle marker cannot be created") from error
        return cls.open(
            state_dir,
            job_id=job_id,
            payload_identity=payload_identity,
            source_id=source_id,
        )

    @classmethod
    def resume(
        cls, state_dir: Path, *, job_id: str, payload_identity: str, source_id: str
    ) -> ScanSpool:
        marker = cls._marker_path(state_dir, job_id)
        try:
            with marker.open(encoding="utf-8") as handle:
                stored = json.load(handle)
        except (OSError, json.JSONDecodeError) as error:
            raise ScanSpoolError("scan lifecycle marker is missing or corrupt") from error
        if stored != cls._marker_payload(job_id, payload_identity, source_id):
            raise ScanSpoolError("scan lifecycle payload mismatch")
        return cls.open(
            state_dir,
            job_id=job_id,
            payload_identity=payload_identity,
            source_id=source_id,
            resume=True,
        )

    @staticmethod
    def _marker_payload(job_id: str, payload_identity: str, source_id: str) -> dict[str, str]:
        return {"job_id": job_id, "payload_identity": payload_identity, "source_id": source_id}

    @staticmethod
    def _spool_path(state_dir: Path, job_id: str) -> Path:
        key = hashlib.sha256(job_id.encode()).hexdigest()
        return state_dir / "scan-spool" / f"{key}.sqlite3"

    @classmethod
    def _marker_path(cls, state_dir: Path, job_id: str) -> Path:
        return cls._spool_path(state_dir, job_id).with_suffix(".lifecycle")

    @classmethod
    def open(
        cls,
        state_dir: Path,
        *,
        job_id: str,
        payload_identity: str,
        source_id: str,
        resume: bool = False,
    ) -> ScanSpool:
        if not job_id or not payload_identity or not source_id:
            raise ScanSpoolError("scan spool identity is incomplete")
        directory = state_dir / "scan-spool"
        path = cls._spool_path(state_dir, job_id)
        if resume and not path.is_file():
            raise ScanSpoolError("scan spool is missing for resume")
        if not path.exists():
            directory.mkdir(mode=0o700, parents=True, exist_ok=True)
        connection = None
        try:
            if path.exists():
                with path.open("rb") as handle:
                    if handle.read(16) != b"SQLite format 3\x00":
                        raise ScanSpoolError("scan spool is unavailable or corrupt")
            connection = sqlite3.connect(path, isolation_level=None)
            connection.execute("PRAGMA journal_mode=WAL")
            connection.execute("PRAGMA synchronous=FULL")
            connection.execute("PRAGMA foreign_keys=ON")
            cls._create_schema(connection)
            existing = dict(connection.execute("SELECT key, value FROM metadata"))
            required = {
                "schema_version": _SCHEMA_VERSION,
                "job_id": job_id,
                "payload_identity": payload_identity,
                "source_id": source_id,
            }
            if existing and any(existing.get(key) != value for key, value in required.items()):
                raise ScanSpoolError("scan spool payload mismatch or semantic corruption")
            if existing and existing.get("finished") == "0" and not resume:
                raise ScanSpoolError("scan spool resume is required")
            if not existing:
                connection.executemany(
                    "INSERT INTO metadata(key, value) VALUES (?, ?)", required.items()
                )
                connection.executemany(
                    "INSERT INTO metadata(key, value) VALUES (?, ?)",
                    (
                        ("finished", "0"),
                        ("inventory_count", "0"),
                        ("inventory_digest", ""),
                        ("page_count", "0"),
                        ("final_cursor", "0"),
                    ),
                )
            else:
                cls._validate(connection)
                spool = cls(connection, job_id=job_id, source_id=source_id)
                for (sequence,) in connection.execute(
                    "SELECT sequence FROM pages ORDER BY sequence"
                ):
                    spool.page(sequence)
                if spool.finished:
                    spool._validate_finished_page_chain()
                if resume:
                    connection.execute(
                        "UPDATE directories SET state = 'pending' WHERE state = 'claimed'"
                    )
            return cls(connection, job_id=job_id, source_id=source_id)
        except (sqlite3.DatabaseError, OSError) as error:
            if connection is not None:
                connection.close()
            raise ScanSpoolError("scan spool is unavailable or corrupt") from error
        except ScanSpoolError:
            if connection is not None:
                connection.close()
            raise

    @staticmethod
    def _create_schema(connection: sqlite3.Connection) -> None:
        connection.execute(
            "CREATE TABLE IF NOT EXISTS metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL)"
        )
        connection.execute(
            "CREATE TABLE IF NOT EXISTS files (position INTEGER PRIMARY KEY, path TEXT UNIQUE NOT NULL, size_bytes INTEGER NOT NULL, modified_at INTEGER NOT NULL)"
        )
        connection.execute(
            "CREATE TABLE IF NOT EXISTS directories (path TEXT PRIMARY KEY, state TEXT NOT NULL, attempt INTEGER NOT NULL DEFAULT 0, members_ready INTEGER NOT NULL DEFAULT 0)"
        )
        connection.execute(
            "CREATE TABLE IF NOT EXISTS directory_members (directory TEXT NOT NULL, path TEXT NOT NULL, is_dir INTEGER NOT NULL, size_bytes INTEGER NOT NULL, modified_at INTEGER NOT NULL, last_attempt INTEGER NOT NULL, PRIMARY KEY(directory, path))"
        )
        connection.execute(
            "CREATE TABLE IF NOT EXISTS pages (sequence INTEGER PRIMARY KEY, start_position INTEGER NOT NULL, next_position INTEGER NOT NULL, checksum TEXT NOT NULL)"
        )

    @staticmethod
    def _validate(connection: sqlite3.Connection) -> None:
        if connection.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
            raise ScanSpoolError("scan spool semantic corruption")
        required = {
            "schema_version",
            "job_id",
            "payload_identity",
            "source_id",
            "finished",
            "inventory_count",
            "inventory_digest",
            "page_count",
            "final_cursor",
        }
        metadata = dict(connection.execute("SELECT key, value FROM metadata"))
        if not required.issubset(metadata) or metadata["schema_version"] != _SCHEMA_VERSION:
            raise ScanSpoolError("scan spool semantic corruption")
        rows = list(
            connection.execute(
                "SELECT sequence, start_position, next_position, checksum FROM pages ORDER BY sequence"
            )
        )
        if metadata["finished"] == "1":
            count, digest = ScanSpool._inventory_signature(connection)
            if metadata["inventory_count"] != str(count) or metadata["inventory_digest"] != digest:
                raise ScanSpoolError("scan spool semantic corruption")
            try:
                page_count = int(metadata["page_count"])
                final_cursor = int(metadata["final_cursor"])
            except ValueError as error:
                raise ScanSpoolError("scan spool semantic corruption") from error
            if page_count != len(rows) or final_cursor != count:
                raise ScanSpoolError("scan spool semantic corruption")
        elif rows or metadata["page_count"] != "0" or metadata["final_cursor"] != "0":
            raise ScanSpoolError("scan spool semantic corruption")
        expected_start = 0
        for expected_sequence, (sequence, start, next_position, checksum) in enumerate(rows):
            empty_initial = sequence == 0 and start == 0 and next_position == 0
            if (
                sequence != expected_sequence
                or start != expected_start
                or (next_position <= start and not empty_initial)
                or len(checksum) != 64
            ):
                raise ScanSpoolError("scan spool semantic corruption")
            expected_start = next_position
        if metadata["finished"] == "1" and expected_start != int(metadata["final_cursor"]):
            raise ScanSpoolError("scan spool semantic corruption")

    @staticmethod
    def _inventory_signature(connection: sqlite3.Connection) -> tuple[int, str]:
        digest = hashlib.sha256()
        count = 0
        for row in connection.execute(
            "SELECT position, path, size_bytes, modified_at FROM files ORDER BY position"
        ):
            digest.update("\0".join(map(str, row)).encode())
            digest.update(b"\n")
            count += 1
        return count, digest.hexdigest()

    def append_file(self, path: str, size_bytes: int, modified_at: int) -> None:
        if self._value("finished") != "0":
            raise ScanSpoolError("scan spool is already finished")
        try:
            existing = self._connection.execute(
                "SELECT size_bytes, modified_at FROM files WHERE path = ?", (path,)
            ).fetchone()
            if existing is not None:
                if tuple(existing) != (size_bytes, modified_at):
                    raise ScanSpoolError("scan inventory changed while resuming")
                return
            position = self._connection.execute("SELECT COUNT(*) FROM files").fetchone()[0]
            self._connection.execute(
                "INSERT INTO files VALUES (?, ?, ?, ?)", (position, path, size_bytes, modified_at)
            )
        except sqlite3.DatabaseError as error:
            raise ScanSpoolError("scan spool write failed") from error

    def append_files(self, files) -> None:
        try:
            self._connection.execute("BEGIN IMMEDIATE")
            if self._value("finished") != "0":
                raise ScanSpoolError("scan spool is already finished")
            position = self._connection.execute("SELECT COUNT(*) FROM files").fetchone()[0]
            self._connection.executemany(
                "INSERT INTO files VALUES (?, ?, ?, ?)",
                (
                    (position + number, path, size_bytes, modified_at)
                    for number, (path, size_bytes, modified_at) in enumerate(files)
                ),
            )
            self._connection.execute("COMMIT")
        except Exception:
            self._connection.execute("ROLLBACK")
            raise

    def finish(self) -> None:
        if self._connection.execute(
            "SELECT 1 FROM directories WHERE state != 'complete' LIMIT 1"
        ).fetchone():
            raise ScanSpoolError("scan spool has claimed or pending directories")
        if self._connection.execute("SELECT 1 FROM pages LIMIT 1").fetchone():
            raise ScanSpoolError("scan spool page state is invalid before finish")
        count, digest = self._inventory_signature(self._connection)
        sequence = 0
        start = 0
        while True:
            page, next_position = self._build_page(sequence, start)
            self._connection.execute(
                "INSERT INTO pages VALUES (?, ?, ?, ?)",
                (sequence, start, next_position, page.checksum),
            )
            if page.page.final:
                break
            sequence += 1
            start = next_position
        self._connection.executemany(
            "UPDATE metadata SET value = ? WHERE key = ?",
            (
                ("1", "finished"),
                (str(count), "inventory_count"),
                (digest, "inventory_digest"),
                (str(sequence + 1), "page_count"),
                (str(next_position), "final_cursor"),
            ),
        )

    @property
    def finished(self) -> bool:
        return self._value("finished") == "1"

    def enqueue_directory(self, path: str) -> None:
        self._connection.execute(
            "INSERT OR IGNORE INTO directories(path, state) VALUES (?, 'pending')", (path,)
        )

    def next_directory(self) -> str | None:
        try:
            self._connection.execute("BEGIN IMMEDIATE")
            row = self._connection.execute(
                "SELECT path FROM directories WHERE state = 'pending' ORDER BY path LIMIT 1"
            ).fetchone()
            if row is None:
                self._connection.execute("COMMIT")
                return None
            changed = self._connection.execute(
                "UPDATE directories SET state = 'claimed', attempt = attempt + 1 WHERE path = ? AND state = 'pending'",
                row,
            ).rowcount
            if changed:
                ready = self._connection.execute(
                    "SELECT members_ready FROM directories WHERE path = ?", row
                ).fetchone()[0]
                if not ready:
                    self._connection.execute(
                        "DELETE FROM directory_members WHERE directory = ?", row
                    )
            self._connection.execute("COMMIT")
            return str(row[0]) if changed == 1 else None
        except sqlite3.DatabaseError as error:
            self._connection.execute("ROLLBACK")
            raise ScanSpoolError("scan spool claim failed") from error

    def observe_directory_member(
        self, directory: str, path: str, is_dir: bool, size_bytes: int, modified_at: int
    ) -> None:
        attempt = self._attempt(directory)
        existing = self._connection.execute(
            "SELECT is_dir, size_bytes, modified_at FROM directory_members WHERE directory = ? AND path = ?",
            (directory, path),
        ).fetchone()
        values = (int(is_dir), size_bytes, modified_at)
        if existing is not None and tuple(existing) != values:
            raise ScanSpoolError("directory membership changed while resuming")
        ready = self._connection.execute(
            "SELECT members_ready FROM directories WHERE path = ?", (directory,)
        ).fetchone()[0]
        if existing is None and attempt > 1 and ready:
            raise ScanSpoolError("directory membership changed while resuming")
        self._connection.execute(
            "INSERT INTO directory_members VALUES (?, ?, ?, ?, ?, ?) ON CONFLICT(directory, path) DO UPDATE SET last_attempt = excluded.last_attempt",
            (directory, path, *values, attempt),
        )

    def complete_directory(self, directory: str) -> None:
        self.seal_directory_membership(directory)
        changed = self._connection.execute(
            "UPDATE directories SET state = 'complete' WHERE path = ? AND state = 'claimed'",
            (directory,),
        ).rowcount
        if changed != 1:
            raise ScanSpoolError("directory claim is no longer valid")

    def seal_directory_membership(self, directory: str) -> None:
        attempt = self._attempt(directory)
        ready = self._connection.execute(
            "SELECT members_ready FROM directories WHERE path = ?", (directory,)
        ).fetchone()[0]
        missing = self._connection.execute(
            "SELECT 1 FROM directory_members WHERE directory = ? AND last_attempt != ? LIMIT 1",
            (directory, attempt),
        ).fetchone()
        if ready and missing:
            raise ScanSpoolError("directory membership changed while resuming")
        self._connection.execute(
            "UPDATE directories SET members_ready = 1 WHERE path = ?", (directory,)
        )

    def directory_members(self, directory: str):
        return self._connection.execute(
            "SELECT path, is_dir, size_bytes, modified_at FROM directory_members WHERE directory = ? ORDER BY path",
            (directory,),
        )

    def page(self, sequence: int) -> ScanManifestPage:
        if sequence < 0 or not self.finished:
            raise ScanSpoolError("scan spool is not ready for pages")
        record = self._connection.execute(
            "SELECT start_position, next_position, checksum FROM pages WHERE sequence = ?",
            (sequence,),
        ).fetchone()
        if record is None:
            raise ScanSpoolError("scan page sequence gap or semantic corruption")
        result, next_position = self._build_page(sequence, int(record[0]))
        if next_position != record[1] or result.checksum != record[2]:
            raise ScanSpoolError("scan spool semantic corruption")
        return result

    def _validate_finished_page_chain(self) -> None:
        expected_pages = int(self._value("page_count"))
        final_pages = 0
        for sequence in range(expected_pages):
            page = self.page(sequence)
            if page.page.final:
                final_pages += 1
                if sequence != expected_pages - 1:
                    raise ScanSpoolError("scan spool semantic corruption")
        if final_pages != 1:
            raise ScanSpoolError("scan spool semantic corruption")

    def _build_page(self, sequence: int, start: int) -> tuple[ScanManifestPage, int]:
        total = self._connection.execute("SELECT COUNT(*) FROM files").fetchone()[0]
        if start > total or (start == total and (sequence or total)):
            raise ScanSpoolError("scan page sequence is invalid")
        rows = self._connection.execute(
            "SELECT path, size_bytes, modified_at FROM files WHERE position >= ? ORDER BY position LIMIT ?",
            (start, REMOTE_MAX_MANIFEST_PAGE_ENTRIES),
        ).fetchall()
        candidates = [
            ScanFile(
                path=path,
                path_hash=remote_path_hash(path),
                size_bytes=size_bytes,
                modified_at=modified_at,
                content_hash=None,
            )
            for path, size_bytes, modified_at in rows
        ]
        low, high = 0, len(candidates)
        while low < high:
            middle = (low + high + 1) // 2
            candidate_page = self._make_page(
                sequence,
                candidates[:middle],
                start + middle >= total,
                start + middle,
            )
            if len(canonical_wire_bytes(candidate_page)) <= REMOTE_MAX_MANIFEST_PAGE_BYTES:
                low = middle
            else:
                high = middle - 1
        if candidates and not low:
            raise ScanSpoolError("single scan entry exceeds page byte limit")
        files = candidates[:low]
        next_position = start + len(files)
        return self._make_page(
            sequence, files, next_position >= total, next_position
        ), next_position

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

    def _attempt(self, directory: str) -> int:
        row = self._connection.execute(
            "SELECT attempt FROM directories WHERE path = ? AND state = 'claimed'", (directory,)
        ).fetchone()
        if row is None:
            raise ScanSpoolError("directory claim is no longer valid")
        return int(row[0])

    def _value(self, key: str) -> str:
        row = self._connection.execute(
            "SELECT value FROM metadata WHERE key = ?", (key,)
        ).fetchone()
        if row is None:
            raise ScanSpoolError("scan spool metadata is corrupt")
        return str(row[0])

    def close(self) -> None:
        self._connection.close()
