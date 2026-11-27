# Copyright (C) 2026 demigodmode
# SPDX-License-Identifier: AGPL-3.0-only

from datetime import date

from app.schemas import METADATA_TERM_MAX_CHARS, METADATA_TERMS_MAX, Document


def make_doc(metadata):
    return Document(
        id="s--abc",
        source_id="s",
        source_name="S",
        path="/data/a.md",
        basename="a.md",
        extension="md",
        type="markdown",
        size_bytes=1,
        modified_at=1,
        indexed_at=1,
        content="",
        metadata=metadata,
    )


def test_collects_tags_keywords_subject_and_author_in_order():
    doc = make_doc({
        "author": "Ana",
        "tags": ["house", "mortgage"],
        "subject": "Loan",
        "keywords": "taxes, 2024",
        "producer": "Ghostscript",
        "creator": "Word",
    })
    assert doc.metadata_terms == ["house", "mortgage", "taxes, 2024", "Loan", "Ana"]


def test_skips_values_that_are_not_plain_text():
    doc = make_doc({
        "tags": ["ok", "", "  ", None, True, {"nested": "x"}, ["deep"], 7, 1.5],
        "author": {"name": "Ana"},
        "subject": date(2024, 1, 2),
    })
    assert doc.metadata_terms == ["ok", "7", "1.5"]


def test_is_capped_so_huge_front_matter_stays_small():
    doc = make_doc({"tags": ["x" * (METADATA_TERM_MAX_CHARS + 10)] * (METADATA_TERMS_MAX + 5)})
    assert len(doc.metadata_terms) == METADATA_TERMS_MAX
    assert all(len(term) == METADATA_TERM_MAX_CHARS for term in doc.metadata_terms)


def test_is_sent_to_the_index():
    dumped = make_doc({"tags": ["house"]}).model_dump(mode="json")
    assert dumped["metadata_terms"] == ["house"]
    assert make_doc({}).model_dump(mode="json")["metadata_terms"] == []


def test_stops_at_the_limit_even_across_keys():
    doc = make_doc({"tags": ["t"] * METADATA_TERMS_MAX, "author": "Ana"})
    assert doc.metadata_terms == ["t"] * METADATA_TERMS_MAX
