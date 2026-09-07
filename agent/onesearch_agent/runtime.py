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
    claim_idle_floor=2.0,
    sleep=asyncio.sleep,
    random=lambda: 0,
    monotonic=time.monotonic,
    stopped=lambda: False,
    wait_stopped=None,
    on_healthy_heartbeat=None,
    update_reporter=None,
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
        if update_reporter is not None:
            update_reporter.check_if_due()
        report = None if update_reporter is None else update_reporter.report()
        if wait_stopped is None:
            await client.heartbeat(__version__, platform.platform(), report)
            if on_healthy_heartbeat is not None:
                on_healthy_heartbeat(__version__, time.time())
            return False
        request = asyncio.create_task(client.heartbeat(__version__, platform.platform(), report))
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
        handled = False
        empty_claim_seconds = None
        try:
            if await heartbeat():
                return
            if worker is not None:
                started = monotonic()
                lease = await client.claim()
                if lease is not None:
                    await worker(lease, client)
                    handled = True
                else:
                    # Time only the claim so a long-poll's own wait paces us.
                    empty_claim_seconds = monotonic() - started
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
        if handled:
            # A job ran; re-claim immediately so queued work drains without the
            # idle interval delaying pickup. Stop is honored at the loop top and
            # by the next heartbeat's stop race.
            continue
        if empty_claim_seconds is not None:
            # The claim long-poll already provided the idle wait. Only sleep if it
            # returned faster than the floor (a server that isn't long-polling), to
            # avoid a hot claim loop.
            if await pause(max(0.0, claim_idle_floor - empty_claim_seconds)):
                return
            continue
        # No worker (heartbeat-only) or an unapproved agent (AgentPending): hold the
        # steady interval so neither path spins.
        if await pause(interval):
            return
