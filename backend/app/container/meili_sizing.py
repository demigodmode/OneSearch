# Copyright (C) 2026 demigodmode
# SPDX-License-Identifier: AGPL-3.0-only

"""Pick indexing limits for the managed Meilisearch.

Meilisearch v1.12 sizes itself from the host and ignores the container's
memory limit, so on a big machine it happily takes 10 threads and gets
OOM-killed over and over in a small container. We set the limits ourselves.
"""
import math
import os
import re
from dataclasses import dataclass, field
from pathlib import Path

MIB = 1024 * 1024

# Measured on Meilisearch v1.12 while indexing 200k documents: roughly 0.6 GB
# resident no matter what, plus about 0.3 GB for every indexing thread. The
# memory cap made no difference on that version, threads did. Measure again
# when the bundled Meilisearch version changes.
BASE_MB = 600
PER_THREAD_MB = 300

# the backend needs the rest for text extraction
MEILI_SHARE = 0.5

# a single indexing thread barely made progress
MIN_THREADS = 2

# No limit we can read doesn't mean there isn't one. Docker inside an LXC sees
# the host's RAM, not the LXC's limit, so stay modest.
MAX_THREADS_WITHOUT_LIMIT = 4

MIN_RECOMMENDED_MB = 2048

THREADS_VAR = "MEILI_MAX_INDEXING_THREADS"
MEMORY_VAR = "MEILI_MAX_INDEXING_MEMORY"

_MEMORY_VALUE = re.compile(r"^\d+(\.\d+)?\s*([kmgt]i?b?|b)?$", re.IGNORECASE)


@dataclass
class MemoryFacts:
    limit_bytes: int | None  # the container's own memory limit, if it has one
    total_bytes: int  # RAM of the machine as seen from inside
    cpus: int


@dataclass
class MeiliSizing:
    threads: str
    memory: str
    summary: str
    warnings: list[str] = field(default_factory=list)


def _read_int(path: Path) -> int | None:
    try:
        return int(path.read_text().strip())
    except (OSError, ValueError):
        return None


def _read_limit(cgroup: Path) -> int | None:
    # cgroup v2 first, then v1. v2 says "max" when unlimited, which fails the int parse.
    for name in ("memory.max", "memory/memory.limit_in_bytes"):
        limit = _read_int(cgroup / name)
        if limit is not None and limit > 0:
            return limit
    return None


def _read_total(meminfo: Path) -> int:
    try:
        for line in meminfo.read_text().splitlines():
            if line.startswith("MemTotal:"):
                return int(line.split()[1]) * 1024
    except (OSError, ValueError, IndexError):
        pass
    return 0


def _read_cpus(cgroup: Path) -> int:
    try:
        cpus = len(os.sched_getaffinity(0))
    except AttributeError:
        cpus = os.cpu_count() or 1

    quota = period = None
    try:
        first, second = (cgroup / "cpu.max").read_text().split()
        if first != "max":
            quota, period = int(first), int(second)
    except (OSError, ValueError):
        quota = _read_int(cgroup / "cpu/cpu.cfs_quota_us")
        period = _read_int(cgroup / "cpu/cpu.cfs_period_us")

    if quota and period and quota > 0:
        cpus = min(cpus, math.ceil(quota / period))
    return max(cpus, 1)


def read_memory_facts(
    cgroup: Path = Path("/sys/fs/cgroup"),
    meminfo: Path = Path("/proc/meminfo"),
) -> MemoryFacts:
    total = _read_total(meminfo)
    limit = _read_limit(cgroup)
    # cgroup v1 reports a huge number instead of "unlimited"
    if limit is not None and total and limit >= total:
        limit = None
    return MemoryFacts(limit_bytes=limit, total_bytes=total, cpus=_read_cpus(cgroup))


def _user_value(env, name: str, valid) -> str | None:
    value = (env.get(name) or "").strip()
    if not value:
        return None
    if not valid(value):
        raise ValueError(f"{name} has an invalid value: {value!r}")
    return value


def size_meilisearch(facts: MemoryFacts, env=None) -> MeiliSizing:
    """Work out indexing threads and memory cap. Values set in env win."""
    env = os.environ if env is None else env
    user_threads = _user_value(env, THREADS_VAR, lambda v: v.isdigit() and int(v) > 0)
    user_memory = _user_value(env, MEMORY_VAR, _MEMORY_VALUE.match)

    has_limit = facts.limit_bytes is not None
    effective_mb = (facts.limit_bytes if has_limit else facts.total_bytes) // MIB
    share_mb = int(effective_mb * MEILI_SHARE)

    # never more than Meilisearch would take by itself (half the cores)
    most = max(facts.cpus // 2, 1)
    if not has_limit:
        most = min(most, MAX_THREADS_WITHOUT_LIMIT)
    fits = (share_mb - BASE_MB) // PER_THREAD_MB
    threads = max(min(fits, most), MIN_THREADS)
    if user_threads:
        threads = int(user_threads)

    cap_mb = BASE_MB + PER_THREAD_MB * threads
    if share_mb:
        cap_mb = min(cap_mb, share_mb)

    source = "container limit" if has_limit else "no container limit, host has"
    summary = (
        f"Meilisearch indexing: {threads} threads"
        f"{' (set by you)' if user_threads else ''}, "
        f"{user_memory + ' memory (set by you)' if user_memory else f'{cap_mb} MiB memory'}"
        f" ({source} {effective_mb} MiB)"
    )

    warnings = []
    if 0 < effective_mb < MIN_RECOMMENDED_MB:
        warnings.append(
            f"WARNING: only {effective_mb} MiB of memory available. OneSearch needs about "
            f"2 GB, indexing a large library may get Meilisearch killed. Give the container "
            f"more memory, or lower {THREADS_VAR}."
        )

    return MeiliSizing(
        threads=str(threads),
        memory=user_memory or str(cap_mb * MIB),
        summary=summary,
        warnings=warnings,
    )
