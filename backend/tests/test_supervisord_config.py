# Copyright (C) 2026 demigodmode
# SPDX-License-Identifier: AGPL-3.0-only

"""Tests for container supervisor config rendering."""

import re

import pytest

from app.container.meili_sizing import MemoryFacts, read_memory_facts, size_meilisearch
from app.container.supervisord import render_supervisord_config


def test_managed_meili_config_starts_meilisearch_and_points_api_at_localhost():
    config = render_supervisord_config(managed_meili=True)

    assert "[program:meilisearch]" in config
    assert "command=/usr/local/bin/meilisearch --db-path /app/meili_data" in config
    assert "--master-key" not in config
    assert "MEILI_URL=\"http://127.0.0.1:7700\"" in config
    assert "MEILI_MASTER_KEY=\"%(ENV_MEILI_MASTER_KEY)s\"" in config
    assert "MEILI_ENV=\"production\"" in config
    assert "directory=/app/meili_data" in config
    assert "command=/app/start-backend.sh" in config


def test_external_meili_config_does_not_start_meilisearch():
    config = render_supervisord_config(managed_meili=False)

    assert "[program:meilisearch]" not in config
    assert "MEILI_URL=\"http://127.0.0.1:7700\"" not in config


GIB = 1024 ** 3


def _meili_limits(limit_gb=None, total_gb=64, cpus=20, env=None):
    """Render the managed config for a memory picture, return (threads, memory bytes or raw value)."""
    facts = MemoryFacts(
        limit_bytes=int(limit_gb * GIB) if limit_gb else None,
        total_bytes=int(total_gb * GIB),
        cpus=cpus,
    )
    sizing = size_meilisearch(facts, env or {})
    config = render_supervisord_config(managed_meili=True, sizing=sizing)
    threads = re.search(r'MEILI_MAX_INDEXING_THREADS="([^"]*)"', config).group(1)
    memory = re.search(r'MEILI_MAX_INDEXING_MEMORY="([^"]*)"', config).group(1)
    return int(threads), memory, sizing


@pytest.mark.parametrize(
    "limit_gb, threads",
    [(1, 2), (2, 2), (3, 3), (3.6, 4), (4, 4), (8, 10), (32, 10)],
)
def test_threads_follow_the_container_limit(limit_gb, threads):
    assert _meili_limits(limit_gb=limit_gb)[0] == threads


def test_no_visible_limit_stays_at_four_threads():
    # Docker inside an LXC sees the host's RAM, the real limit may be far lower
    threads, memory, sizing = _meili_limits(limit_gb=None, total_gb=62)

    assert threads == 4
    assert int(memory) == 1800 * 1024 * 1024
    assert "no container limit" in sizing.summary


def test_threads_never_exceed_what_meilisearch_would_pick():
    assert _meili_limits(limit_gb=32, cpus=8)[0] == 4


def test_small_machines_still_get_two_threads():
    assert _meili_limits(limit_gb=8, cpus=2)[0] == 2
    assert _meili_limits(limit_gb=None, total_gb=1, cpus=1)[0] == 2


def test_memory_cap_stays_inside_the_meilisearch_share():
    _, memory, _ = _meili_limits(limit_gb=2)

    # two threads want 1200 MiB but half of 2 GB is all Meilisearch gets
    assert int(memory) == 1024 * 1024 * 1024


def test_warns_below_two_gigabytes_but_still_starts():
    assert _meili_limits(limit_gb=2)[2].warnings == []

    threads, _, sizing = _meili_limits(limit_gb=1)

    assert threads == 2
    assert len(sizing.warnings) == 1
    assert "MEILI_MAX_INDEXING_THREADS" in sizing.warnings[0]


def test_user_thread_count_wins_and_memory_is_still_sized():
    threads, memory, sizing = _meili_limits(limit_gb=8, env={"MEILI_MAX_INDEXING_THREADS": "3"})

    assert threads == 3
    assert int(memory) == 1500 * 1024 * 1024
    assert "set by you" in sizing.summary


def test_user_memory_cap_wins_and_threads_are_still_sized():
    threads, memory, _ = _meili_limits(limit_gb=4, env={"MEILI_MAX_INDEXING_MEMORY": "512Mb"})

    assert threads == 4
    assert memory == "512Mb"


def test_user_can_set_both():
    env = {"MEILI_MAX_INDEXING_THREADS": "16", "MEILI_MAX_INDEXING_MEMORY": "6 GiB"}
    threads, memory, _ = _meili_limits(limit_gb=2, env=env)

    assert threads == 16
    assert memory == "6 GiB"


def test_empty_values_count_as_unset():
    env = {"MEILI_MAX_INDEXING_THREADS": "", "MEILI_MAX_INDEXING_MEMORY": " "}

    assert _meili_limits(limit_gb=4, env=env)[0] == 4


@pytest.mark.parametrize(
    "name, value",
    [
        ("MEILI_MAX_INDEXING_THREADS", "0"),
        ("MEILI_MAX_INDEXING_THREADS", "four"),
        ("MEILI_MAX_INDEXING_THREADS", "2.5"),
        ("MEILI_MAX_INDEXING_MEMORY", "lots"),
        ("MEILI_MAX_INDEXING_MEMORY", "50%"),
    ],
)
def test_invalid_user_values_are_rejected_by_name(name, value):
    with pytest.raises(ValueError, match=name):
        _meili_limits(limit_gb=4, env={name: value})


def test_external_meili_is_not_sized():
    config = render_supervisord_config(managed_meili=False)

    assert "MEILI_MAX_INDEXING" not in config


def _cgroup(tmp_path, files, mem_total_kb=16 * 1024 * 1024):
    cgroup = tmp_path / "cgroup"
    for name, content in files.items():
        path = cgroup / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)
    cgroup.mkdir(exist_ok=True)
    meminfo = tmp_path / "meminfo"
    meminfo.write_text(f"MemTotal:       {mem_total_kb} kB\nMemFree:         1000 kB\n")
    return read_memory_facts(cgroup=cgroup, meminfo=meminfo)


def test_reads_a_cgroup_v2_limit(tmp_path):
    facts = _cgroup(tmp_path, {"memory.max": "2147483648\n", "cpu.max": "200000 100000\n"})

    assert facts.limit_bytes == 2 * GIB
    assert facts.total_bytes == 16 * GIB
    assert facts.cpus <= 2


def test_reads_a_cgroup_v1_limit(tmp_path):
    facts = _cgroup(tmp_path, {"memory/memory.limit_in_bytes": "4294967296\n"})

    assert facts.limit_bytes == 4 * GIB


@pytest.mark.parametrize(
    "files",
    [
        {"memory.max": "max\n", "cpu.max": "max 100000\n"},
        # v1 reports a number close to 2^63 when there is no limit
        {"memory/memory.limit_in_bytes": "9223372036854771712\n"},
        {},
    ],
)
def test_no_limit_is_reported_as_none(tmp_path, files):
    assert _cgroup(tmp_path, files).limit_bytes is None
