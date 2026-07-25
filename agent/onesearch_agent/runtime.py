"""Heartbeat runtime; claims only when a worker callback exists."""

from __future__ import annotations

import asyncio
import platform

from . import __version__
from .client import AgentIncompatible, AgentPending, AgentRevoked


async def run_runtime(client, *, worker=None, interval=30, sleep=asyncio.sleep):
    while True:
        try:
            await client.heartbeat(__version__, platform.platform())
            if worker is not None:
                lease = await client.claim()
                if lease is not None:
                    await worker(lease, client)
        except AgentPending:
            pass
        except (AgentRevoked, AgentIncompatible):
            raise
        await sleep(interval)
