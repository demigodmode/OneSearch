"""Heartbeat runtime; claims only when a worker callback exists."""

from __future__ import annotations

import asyncio
import platform

from . import __version__
from .client import AgentDisabled, AgentError, AgentIncompatible, AgentPending, AgentRevoked


async def run_runtime(
    client,
    *,
    worker=None,
    interval=30,
    sleep=asyncio.sleep,
    random=lambda: 0,
    stopped=lambda: False,
):
    failures = 0
    while True:
        if stopped():
            return
        try:
            await client.heartbeat(__version__, platform.platform())
            if worker is not None:
                lease = await client.claim()
                if lease is not None:
                    await worker(lease, client)
        except AgentPending:
            pass
        except (AgentRevoked, AgentIncompatible, AgentDisabled):
            raise
        except AgentError:
            failures += 1
            if stopped():
                return
            await sleep(min(60, 2 ** min(failures, 6) + random()))
            continue
        failures = 0
        await sleep(interval)
