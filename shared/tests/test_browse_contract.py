import pytest
from onesearch_shared import (
    REMOTE_MAX_BROWSE_DIRECTORIES,
    BrowseDirectoryEntry,
    BrowseResult,
    JobCompletion,
    JobStatus,
)
from pydantic import ValidationError


def test_browse_completion_is_strict_and_bounded():
    result = BrowseResult(
        root_id="docs",
        path="team",
        entries=[BrowseDirectoryEntry(name="child", path="team/child")],
        truncated=False,
    )
    completion = JobCompletion(job_id="job", status=JobStatus.SUCCEEDED, browse_result=result)
    assert completion.model_dump(mode="json")["browse_result"] == result.model_dump(mode="json")

    with pytest.raises(ValidationError):
        JobCompletion(job_id="job", status=JobStatus.FAILED, browse_result=result)
    with pytest.raises(ValidationError):
        BrowseResult(root_id="docs", path="../secret", entries=[], truncated=False)
    with pytest.raises(ValidationError):
        BrowseResult(
            root_id="docs",
            path="",
            entries=[BrowseDirectoryEntry(name=str(i), path=str(i)) for i in range(REMOTE_MAX_BROWSE_DIRECTORIES + 1)],
            truncated=True,
        )


@pytest.mark.parametrize("value", ["bad\x00name", "bad\x1fname", "bad\x85name"])
def test_browse_wire_rejects_control_characters_but_allows_unicode(value):
    with pytest.raises(ValidationError):
        BrowseDirectoryEntry(name=value, path="safe")
    with pytest.raises(ValidationError):
        BrowseDirectoryEntry(name="safe", path=value)
    assert BrowseDirectoryEntry(name="資料", path="資料").name == "資料"


@pytest.mark.parametrize(
    "kwargs",
    [
        {"name": "x" * 256, "path": "safe"},
        {"name": "safe", "path": "x" * 4097},
    ],
)
def test_browse_entry_bounds_are_enforced(kwargs):
    with pytest.raises(ValidationError):
        BrowseDirectoryEntry(**kwargs)


@pytest.mark.parametrize("kwargs", [{"root_id": "x" * 121}, {"path": "x" * 4097}])
def test_browse_result_bounds_are_enforced(kwargs):
    with pytest.raises(ValidationError):
        BrowseResult(**{"root_id": "docs", "entries": [], "truncated": False, **kwargs})


def test_browse_wire_accepts_values_at_bounds():
    result = BrowseResult(
        root_id="r" * 120, path="p" * 4096,
        entries=[BrowseDirectoryEntry(name="n" * 255, path="n" * 255)], truncated=False,
    )
    assert len(result.path) == 4096
