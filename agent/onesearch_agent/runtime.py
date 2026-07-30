"""Heartbeat runtime; claims only when a worker callback exists."""

from __future__ import annotations

import asyncio
import platform
import time

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
    wait_stopped=None,
    on_healthy_heartbeat=None,
):
    async def pause(seconds):
        if wait_stopped is None:
            await sleep(seconds)
            return stopped()
        timer = asyncio.create_task(sleep(seconds))
        stopper = asyncio.create_task(wait_stopped())
        done, pending = await asyncio.wait({timer, stopper}, return_when=asyncio.FIRST_COMPLETED)
        for task in pending:
            task.cancel()
        await asyncio.gather(*pending, return_exceptions=True)
        return stopper in done

    async def heartbeat():
        if wait_stopped is None:
            await client.heartbeat(__version__, platform.platform())
            if on_healthy_heartbeat is not None:
                on_healthy_heartbeat(__version__, time.time())
            return False
        request = asyncio.create_task(client.heartbeat(__version__, platform.platform()))
        stopper = asyncio.create_task(wait_stopped())
        done, pending = await asyncio.wait({request, stopper}, return_when=asyncio.FIRST_COMPLETED)
        for task in pending:
            task.cancel()
        await asyncio.gather(*pending, return_exceptions=True)
        if stopper in done:
            return True
        await request
        if on_healthy_heartbeat is not None:
            on_healthy_heartbeat(__version__, time.time())
        return False

    failures = 0
    while True:
        if stopped():
            return
        try:
            if await heartbeat():
                return
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
            if await pause(min(60, 2 ** min(failures, 6) + random())):
                return
            continue
        failures = 0
        if await pause(interval):
            return
