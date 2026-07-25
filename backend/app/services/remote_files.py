"""Bounded, checksum-verified byte transport for remote agent files."""

from __future__ import annotations

import asyncio
import hashlib
from collections.abc import AsyncIterator
from pathlib import Path


class RemoteFileError(RuntimeError):
    code = "remote_stream_timeout"


class RemoteFileMissing(RemoteFileError):  # noqa: N818 - public wire error name
    code = "remote_file_missing"


class RemoteFileChanged(RemoteFileError):  # noqa: N818 - public wire error name
    code = "remote_file_changed"


class RemoteStreamTimeout(RemoteFileError):  # noqa: N818 - public wire error name
    code = "remote_stream_timeout"


class BoundedByteQueue:
    """A byte-counted async queue; producers cannot accumulate unbounded memory."""

    def __init__(self, *, max_bytes: int):
        if max_bytes < 1:
            raise ValueError("max_bytes must be positive")
        self.max_bytes = max_bytes
        self._items: asyncio.Queue[bytes | None] = asyncio.Queue()
        self._space = asyncio.Condition()
        self._bytes = 0
        self._next_sequence = 0
        self._digest = hashlib.sha256()
        self._finished = False

    async def put(self, sequence: int, chunk: bytes, checksum: str | None = None) -> None:
        if self._finished or sequence != self._next_sequence:
            raise RemoteFileChanged("invalid chunk sequence")
        if not chunk or len(chunk) > self.max_bytes:
            raise RemoteFileChanged("invalid chunk size")
        if checksum is not None and hashlib.sha256(chunk).hexdigest() != checksum:
            raise RemoteFileChanged("chunk checksum mismatch")
        async with self._space:
            await self._space.wait_for(lambda: self._bytes + len(chunk) <= self.max_bytes)
            self._bytes += len(chunk)
        self._digest.update(chunk)
        self._next_sequence += 1
        await self._items.put(chunk)

    async def finish(self, sequence: int, checksum: str) -> None:
        if self._finished or sequence != self._next_sequence:
            raise RemoteFileChanged("invalid chunk sequence")
        if self._digest.hexdigest() != checksum:
            raise RemoteFileChanged("stream checksum mismatch")
        self._finished = True
        await self._items.put(None)

    async def get(self) -> bytes | None:
        item = await self._items.get()
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

    def open(self, job_id: str, *, max_bytes: int = 512 * 1024) -> BoundedByteQueue:
        return self._streams.setdefault(job_id, BoundedByteQueue(max_bytes=max_bytes))

    def get(self, job_id: str) -> BoundedByteQueue | None:
        return self._streams.get(job_id)

    def close(self, job_id: str) -> None:
        self._streams.pop(job_id, None)


remote_streams = RemoteStreamRegistry()


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
