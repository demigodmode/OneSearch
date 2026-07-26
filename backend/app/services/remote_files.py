"""Bounded, checksum-verified byte transport for remote agent files."""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import multiprocessing
import tempfile
import time
from collections.abc import AsyncIterator
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path

from ..config import settings as runtime_settings
from ..schemas import Document
from .extractor_config import choose_extractor


class RemoteFileError(RuntimeError):
    code = "remote_stream_timeout"


class RemoteFileMissing(RemoteFileError):  # noqa: N818 - public wire error name
    code = "remote_file_missing"


class RemoteFileChanged(RemoteFileError):  # noqa: N818 - public wire error name
    code = "remote_file_changed"


class RemoteStreamTimeout(RemoteFileError):  # noqa: N818 - public wire error name
    code = "remote_stream_timeout"


def _verify_chunk_checksum(data: bytes, checksum: str | None) -> None:
    if not isinstance(checksum, str) or len(checksum) != 64:
        raise RemoteFileChanged("chunk checksum required")
    if not hmac.compare_digest(hashlib.sha256(data).hexdigest(), checksum):
        raise RemoteFileChanged("chunk checksum mismatch")


class RemoteExtractionError(RuntimeError):
    pass


def _send_extraction_message(connection, payload) -> None:
    data = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    if len(data) > 1_000_000:
        data = (
            b'{"error_type":"RemoteExtractionError","error":"extraction result exceeds IPC limit"}'
        )
    connection.send_bytes(data)


def extraction_process(snapshot, source_id, extraction, connection) -> None:
    try:
        extractor = choose_extractor(snapshot, source_id, extraction["source_name"], extraction)
        document = asyncio.run(extractor.extract_with_timeout(snapshot)) if extractor else None
        _send_extraction_message(
            connection, {"document": document.model_dump(mode="json") if document else None}
        )
    except BaseException as error:
        detail = "".join(
            char for char in str(error).replace(snapshot, "<temporary>") if char >= " "
        )
        _send_extraction_message(
            connection, {"error_type": type(error).__name__, "error": detail[:500]}
        )
    finally:
        connection.close()


async def extract_in_process(
    snapshot,
    source_id,
    extraction,
    timeout_seconds,
    *,
    process_target=extraction_process,
    on_process_start=None,
):
    """Spawn-isolated extraction with bounded IPC and unconditional child cleanup."""
    context = multiprocessing.get_context("spawn")
    receiver, sender = context.Pipe(duplex=False)
    process = context.Process(
        target=process_target, args=(snapshot, source_id, extraction, sender), daemon=True
    )
    try:
        process.start()
        sender.close()
        if on_process_start is not None:
            on_process_start(process.pid)
        deadline = asyncio.get_running_loop().time() + timeout_seconds
        while asyncio.get_running_loop().time() < deadline:
            if receiver.poll():
                try:
                    message = json.loads(receiver.recv_bytes(1_000_000).decode())
                except (EOFError, OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
                    raise RemoteExtractionError("invalid extractor process result") from error
                if "error" in message:
                    if message.get("error_type") == "ValueError":
                        raise ValueError(message["error"])
                    raise RemoteExtractionError(message["error"])
                return Document.model_validate(message["document"]) if message["document"] else None
            if not process.is_alive():
                raise RemoteExtractionError("extractor process exited without a result")
            await asyncio.sleep(0.02)
        raise RemoteExtractionError("extraction timed out")
    finally:
        with suppress(OSError):
            sender.close()
        if process.pid is not None:
            if process.is_alive():
                process.terminate()
            process.join(timeout=2)
            if process.is_alive():
                process.kill()
                process.join(timeout=2)
            if not process.is_alive():
                process.close()
        receiver.close()


class BoundedByteQueue:
    """A byte-counted async queue; producers cannot accumulate unbounded memory."""

    def __init__(self, *, max_bytes: int, expected_size: int):
        if max_bytes < 1 or expected_size < 0:
            raise ValueError("stream limits must be nonnegative")
        self.max_bytes, self.expected_size = max_bytes, expected_size
        self._items: asyncio.Queue[bytes | None] = asyncio.Queue()
        self._space = asyncio.Condition()
        self._bytes = 0
        self._received = 0
        self._producer_lock = asyncio.Lock()
        self._next_sequence = 0
        self._digest = hashlib.sha256()
        self._finished = False
        self._error: RemoteFileError | None = None

    async def put(self, sequence: int, chunk: bytes, checksum: str | None = None) -> None:
        async with self._producer_lock:
            if self._finished or sequence != self._next_sequence:
                if self._error is not None:
                    raise self._error
                raise RemoteFileChanged("invalid chunk sequence")
            if not chunk or len(chunk) > self.max_bytes:
                raise RemoteFileChanged("invalid chunk size")
            _verify_chunk_checksum(chunk, checksum)
            if self._received + len(chunk) > self.expected_size:
                raise RemoteFileChanged("stream size exceeds expected size")
            async with self._space:
                await self._space.wait_for(
                    lambda: self._finished or self._bytes + len(chunk) <= self.max_bytes
                )
                if self._finished:
                    if self._error is not None:
                        raise self._error
                    raise RemoteStreamTimeout("stream closed")
                self._bytes += len(chunk)
            self._digest.update(chunk)
            self._received += len(chunk)
            self._next_sequence += 1
            await self._items.put(chunk)

    def validate_finish(self, sequence: int, checksum: str) -> None:
        if self._finished or sequence != self._next_sequence:
            raise RemoteFileChanged("invalid chunk sequence")
        if self._received != self.expected_size:
            raise RemoteFileChanged("stream size differs from expected size")
        if self._digest.hexdigest() != checksum:
            raise RemoteFileChanged("stream checksum mismatch")

    async def finish(self, sequence: int, checksum: str) -> None:
        self.validate_finish(sequence, checksum)
        self._finished = True
        await self._items.put(None)

    async def fail(self, error: RemoteFileError) -> None:
        if self._finished:
            return
        self._error, self._finished = error, True
        async with self._space:
            self._space.notify_all()
        await self._items.put(None)

    async def get(self) -> bytes | None:
        item = await self._items.get()
        if item is None and self._error is not None:
            raise self._error
        if item is not None:
            async with self._space:
                self._bytes -= len(item)
                self._space.notify_all()
        return item

    async def iterate(self) -> AsyncIterator[bytes]:
        while (item := await self.get()) is not None:
            yield item


class RemoteStreamRegistry:
    """Short-lived in-process handoff between a leased agent and one HTTP response."""

    def __init__(self):
        self._streams: dict[str, BoundedByteQueue] = {}

    def open(self, job_id: str, *, expected_size: int, max_bytes: int = 512 * 1024) -> BoundedByteQueue:
        existing = self._streams.get(job_id)
        if existing is not None:
            if existing.expected_size != expected_size or existing.max_bytes != max_bytes:
                raise RemoteFileChanged("incompatible stream limits")
            return existing
        queue = BoundedByteQueue(max_bytes=max_bytes, expected_size=expected_size)
        self._streams[job_id] = queue
        return queue

    def get(self, job_id: str) -> BoundedByteQueue | None:
        return self._streams.get(job_id)

    def require(self, job_id: str) -> BoundedByteQueue:
        queue = self.get(job_id)
        if queue is None:
            raise RemoteStreamTimeout("stream is not open")
        return queue

    async def close(self, job_id: str, error: RemoteFileError | None = None) -> None:
        queue = self._streams.pop(job_id, None)
        if queue is not None:
            await queue.fail(error or RemoteStreamTimeout("stream closed"))


remote_streams = RemoteStreamRegistry()


@dataclass
class _ExtractUpload:
    handle: object
    path: Path
    expected_size: int
    maximum_size: int
    next_sequence: int = 0
    copied: int = 0
    touched_at: float = 0
    digest: object = None

    def __post_init__(self):
        self.touched_at = time.monotonic()
        self.digest = hashlib.sha256()


class ExtractUploadRegistry:
    """Private disk-backed sessions for extract jobs; originals never outlive a job."""

    def __init__(self, directory: Path, *, chunk_bytes: int = 512 * 1024):
        self.directory, self.chunk_bytes, self._sessions = Path(directory), chunk_bytes, {}

    def append(
        self,
        job_id: str,
        *,
        sequence: int,
        data: bytes,
        checksum: str | None,
        expected_size: int,
        maximum_size: int,
        suffix: str = "",
    ) -> None:
        if not data or len(data) > self.chunk_bytes:
            raise RemoteFileChanged("chunk exceeds limit")
        session = self._sessions.get(job_id)
        try:
            _verify_chunk_checksum(data, checksum)
        except RemoteFileChanged:
            self.cleanup(job_id)
            raise
        if session is None:
            if expected_size < 0 or expected_size > maximum_size:
                raise RemoteFileChanged("declared size exceeds limit")
            self.directory.mkdir(parents=True, exist_ok=True)
            safe_suffix = suffix if suffix.startswith(".") and suffix[1:].isalnum() else ""
            handle = tempfile.NamedTemporaryFile(  # noqa: SIM115 - session owns close lifecycle
                prefix="onesearch-remote-", suffix=safe_suffix, dir=self.directory, delete=False
            )
            session = _ExtractUpload(handle, Path(handle.name), expected_size, maximum_size)
            self._sessions[job_id] = session
        if sequence != session.next_sequence or session.copied + len(data) > session.maximum_size:
            self.cleanup(job_id)
            raise RemoteFileChanged("invalid chunk sequence or size")
        session.handle.write(data)
        session.handle.flush()
        session.digest.update(data)
        session.copied += len(data)
        session.next_sequence += 1
        session.touched_at = time.monotonic()

    def finish(self, job_id: str, *, sequence: int, checksum: str) -> Path:
        session = self._sessions.get(job_id)
        if session is None or sequence != session.next_sequence:
            self.cleanup(job_id)
            raise RemoteFileChanged("invalid chunk sequence")
        session.handle.close()
        if session.copied != session.expected_size or session.digest.hexdigest() != checksum:
            self.cleanup(job_id)
            raise RemoteFileChanged("stream checksum or size changed")
        return session.path

    def cleanup(self, job_id: str) -> None:
        session = self._sessions.pop(job_id, None)
        if session is not None:
            try:
                session.handle.close()
            finally:
                session.path.unlink(missing_ok=True)

    def cleanup_all(self) -> None:
        for job_id in list(self._sessions):
            self.cleanup(job_id)

    def has(self, job_id: str) -> bool:
        return job_id in self._sessions

    def expire(self, maximum_age: float) -> None:
        cutoff = time.monotonic() - maximum_age
        for job_id, session in list(self._sessions.items()):
            if session.touched_at <= cutoff:
                self.cleanup(job_id)


class RemoteFileCoordinator:
    """Coordinates durable parent cancellation with ephemeral upload cleanup."""

    def __init__(self, db, uploads: ExtractUploadRegistry):
        self.db, self.uploads = db, uploads

    def cancel_server_parent(self, parent_id: str):
        from ..models import AgentJob
        from .agent_jobs import AgentJobService, JobConflict

        parent = self.db.get(AgentJob, parent_id)
        if parent is None or parent.kind != "scan" or parent.processing_mode != "on_server":
            raise JobConflict("on-server scan required")
        AgentJobService(self.db).cancel(parent_id)
        children = [
            child
            for child in self.db.query(AgentJob).filter(AgentJob.kind == "extract_file")
            if __import__("json").loads(child.payload).get("parent_job_id") == parent_id
        ]
        for child in children:
            self.uploads.cleanup(child.id)
        if all(child.status == "cancelled" for child in children):
            parent.status, parent.active_key = "cancelled", None
        return parent


def app_data_temp_directory(database_url: str) -> Path:
    """Keep transient originals next to the configured application database."""
    prefix = "sqlite:///"
    if database_url.startswith(prefix):
        return Path(database_url.removeprefix(prefix)).parent / "tmp"
    return Path("/app/data/tmp")


# Process-local transient state. Durable job transitions target exact job IDs.
extract_uploads = ExtractUploadRegistry(app_data_temp_directory(runtime_settings.database_url))
EXTRACT_UPLOAD_MAX_AGE_SECONDS = 15 * 60
EXTRACT_UPLOAD_SWEEP_SECONDS = 60


async def sweep_extract_uploads(
    registry: ExtractUploadRegistry,
    *,
    maximum_age: float = EXTRACT_UPLOAD_MAX_AGE_SECONDS,
    interval: float = EXTRACT_UPLOAD_SWEEP_SECONDS,
    sleep=asyncio.sleep,
) -> None:
    """Periodically discard stalled process-local uploads until cancelled."""
    while True:
        registry.expire(maximum_age)
        await sleep(interval)


async def copy_bounded(
    chunks: AsyncIterator[bytes],
    target: Path,
    *,
    expected_size: int,
    maximum_size: int,
    expected_checksum: str | None = None,
) -> str:
    """Persist one verified temporary transfer, deleting it on every failure."""
    if expected_size < 0 or expected_size > maximum_size:
        raise RemoteFileChanged("declared size exceeds limit")
    digest, copied = hashlib.sha256(), 0
    try:
        with target.open("xb") as output:
            async for chunk in chunks:
                copied += len(chunk)
                if copied > maximum_size:
                    raise RemoteFileChanged("stream size exceeds limit")
                digest.update(chunk)
                output.write(chunk)
        if copied != expected_size:
            raise RemoteFileChanged("stream size changed")
        actual = digest.hexdigest()
        if expected_checksum is not None and actual != expected_checksum:
            raise RemoteFileChanged("stream checksum changed")
        return actual
    except BaseException:
        target.unlink(missing_ok=True)
        raise
