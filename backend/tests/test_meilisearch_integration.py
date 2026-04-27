# Copyright (C) 2026 demigodmode
# SPDX-License-Identifier: AGPL-3.0-only

"""
Live Meilisearch contract tests.

These tests are skipped unless a Meilisearch server is reachable. CI starts one so
we catch client/server API mismatches that mocked tests can miss.
"""
import json
import os
import uuid

import pytest
from meilisearch import Client

from app.services.search import (
    FILTERABLE_FIELDS,
    SEARCHABLE_FIELDS,
    SORTABLE_FIELDS,
    MeilisearchService,
)


RANKING_RULES = [
    "words",
    "typo",
    "proximity",
    "attribute",
    "sort",
    "exactness",
]


@pytest.fixture(scope="session")
def live_meili_client():
    url = os.environ.get("MEILI_URL", "http://localhost:7700")
    key = os.environ.get("MEILI_MASTER_KEY", "")
    client = Client(url, key)

    try:
        client.health()
    except Exception as exc:
        pytest.skip(f"Meilisearch is not available at {url}: {exc}")

    return client


@pytest.fixture
def live_index(live_meili_client):
    index_name = f"onesearch_test_{uuid.uuid4().hex}"
    task = live_meili_client.create_index(index_name, {"primaryKey": "id"})
    live_meili_client.wait_for_task(task.task_uid, timeout_in_ms=30000)

    index = live_meili_client.get_index(index_name)
    try:
        yield index
    finally:
        task = live_meili_client.delete_index(index_name)
        live_meili_client.wait_for_task(task.task_uid, timeout_in_ms=30000)


def wait_for_task_from_dict(client: Client, task: dict):
    task_uid = task.get("task_uid") or task.get("taskUid")
    client.wait_for_task(task_uid, timeout_in_ms=30000)


def document_id(document):
    return document["id"] if isinstance(document, dict) else document.id


@pytest.mark.asyncio
async def test_onesearch_meilisearch_contract(live_meili_client, live_index):
    service = MeilisearchService()
    service.client = live_meili_client
    service.index = live_index

    for task in (
        live_index.update_searchable_attributes(SEARCHABLE_FIELDS),
        live_index.update_filterable_attributes(FILTERABLE_FIELDS),
        live_index.update_sortable_attributes(SORTABLE_FIELDS),
        live_index.update_ranking_rules(RANKING_RULES),
    ):
        live_meili_client.wait_for_task(task.task_uid, timeout_in_ms=30000)

    add_task = await service.index_documents([
        {
            "id": "doc-a",
            "source_id": "source-a",
            "source_name": "Source A",
            "path": "/data/source-a/readme.md",
            "basename": "readme.md",
            "title": "Readme",
            "content": "OneSearch test document about homelab search",
            "type": "markdown",
            "extension": "md",
            "size_bytes": 100,
            "modified_at": 20,
            "indexed_at": "2026-04-27T00:00:00Z",
            "metadata": {},
        },
        {
            "id": "doc-b",
            "source_id": "source-b",
            "source_name": "Source B",
            "path": "/data/source-b/notes.txt",
            "basename": "notes.txt",
            "title": "Notes",
            "content": "Another test document for filter cleanup",
            "type": "text",
            "extension": "txt",
            "size_bytes": 200,
            "modified_at": 10,
            "indexed_at": "2026-04-27T00:00:00Z",
            "metadata": {},
        },
    ])
    wait_for_task_from_dict(live_meili_client, add_task)

    basic = await service.search("test", limit=10)
    assert basic["estimatedTotalHits"] == 2
    assert basic["hits"][0]["id"] in {"doc-a", "doc-b"}
    assert "_formatted" in basic["hits"][0]

    source_filtered = await service.search(
        "test",
        filters=[f"source_id = {json.dumps('source-a')}"],
        limit=10,
    )
    assert [hit["id"] for hit in source_filtered["hits"]] == ["doc-a"]

    type_filtered = await service.search(
        "test",
        filters=[f"type = {json.dumps('text')}"],
        limit=10,
    )
    assert [hit["id"] for hit in type_filtered["hits"]] == ["doc-b"]

    sorted_results = await service.search("test", sort="modified_at:desc", limit=10)
    assert [hit["id"] for hit in sorted_results["hits"]] == ["doc-a", "doc-b"]

    document = await service.get_document("doc-a")
    assert document_id(document) == "doc-a"

    delete_task = await service.delete_documents_by_filter(
        f"source_id = {json.dumps('source-a')}"
    )
    wait_for_task_from_dict(live_meili_client, delete_task)

    after_delete = await service.search("test", limit=10)
    assert [hit["id"] for hit in after_delete["hits"]] == ["doc-b"]
