import time

import pytest
from onesearch_agent import worker
from onesearch_shared import AgentJobLease, AllowedRoot, JobKind, JobStatus


class _Client:
    def __init__(self):
        self.completions = []

    async def complete(self, _job_id, completion, _token):
        self.completions.append(completion)

    async def get_job_status(self, _job_id):
        raise AssertionError("unexpected recovery poll")

    async def job_heartbeat(self, *_args):
        return None

    async def cancel_ack(self, *_args):
        return None


@pytest.mark.asyncio
async def test_list_browse_returns_only_sorted_directories_and_omits_symlink_escape(tmp_path):
    (tmp_path / "zeta").mkdir()
    (tmp_path / "alpha").mkdir()
    (tmp_path / "file.txt").write_text("not a directory")
    (tmp_path / "escape").symlink_to(tmp_path.parent, target_is_directory=True)
    lease = AgentJobLease(
        id="browse", kind=JobKind.BROWSE,
        payload={"operation": "list", "root_id": "docs", "path": ""}, lease_token="token"
    )
    client = _Client()

    await worker.run_browse_job(lease, client, roots=[AllowedRoot(root_id="docs", path=str(tmp_path))])

    completion = client.completions[0]
    assert completion.status is JobStatus.SUCCEEDED
    assert completion.browse_result.root_id == "docs"
    assert [item.name for item in completion.browse_result.entries] == ["alpha", "zeta"]
    assert completion.browse_result.truncated is False


@pytest.mark.asyncio
async def test_list_browse_applies_ui_cap_and_reports_truncation(tmp_path):
    for number in range(501):
        (tmp_path / f"directory-{number:03d}").mkdir()
    lease = AgentJobLease(
        id="cap", kind=JobKind.BROWSE,
        payload={"operation": "list", "root_id": "docs", "path": ""}, lease_token="token"
    )
    client = _Client()
    await worker.run_browse_job(lease, client, roots=[AllowedRoot(root_id="docs", path=str(tmp_path))])
    result = client.completions[0].browse_result
    assert len(result.entries) == 500 and result.truncated is True
    assert result.entries[0].name == "directory-000"
    assert result.entries[-1].name == "directory-499"


def test_browse_name_heap_is_bounded_deterministic_and_marks_only_unseen_results_truncated():
    from onesearch_agent.paths import _bounded_browse_names

    names = (f"directory-{number:06d}" for number in range(100_000, -1, -1))
    selected, truncated, scanned = _bounded_browse_names(names, max_entries=500, scan_budget=700)
    assert selected == [f"directory-{number:06d}" for number in range(99_301, 99_801)]
    assert truncated is True and scanned == 701
    exact, exact_truncated, exact_scanned = _bounded_browse_names(
        (f"d{number:03d}" for number in range(500)), max_entries=500, scan_budget=1000
    )
    assert len(exact) == 500 and exact_truncated is False and exact_scanned == 500

    one_more, one_more_truncated, one_more_scanned = _bounded_browse_names(
        (f"d{number:03d}" for number in range(501)), max_entries=500, scan_budget=1000
    )
    assert len(one_more) == 500 and one_more_truncated is True and one_more_scanned == 501


def test_posix_browse_exact_cap_is_not_truncated_but_budget_exhaustion_is(tmp_path):
    from onesearch_agent.paths import list_confined_browse_directories_page

    for number in range(3):
        (tmp_path / f"directory-{number}").mkdir()
    roots = [AllowedRoot(root_id="docs", path=str(tmp_path))]

    exact = list_confined_browse_directories_page("docs", "", roots, max_entries=3, scan_budget=10)
    budget_limited = list_confined_browse_directories_page(
        "docs", "", roots, max_entries=3, scan_budget=2
    )

    assert [entry.name for entry in exact.entries] == ["directory-0", "directory-1", "directory-2"]
    assert exact.truncated is False
    assert len(budget_limited.entries) == 2
    assert [entry.name for entry in budget_limited.entries] == sorted(
        entry.name for entry in budget_limited.entries
    )
    assert budget_limited.truncated is True


def test_windows_browse_heap_is_bounded_and_deterministic_without_materializing(monkeypatch):
    import onesearch_agent.paths as paths

    opened = []
    monkeypatch.setattr(paths, "_windows_verified_directory", lambda *_args: (1, "root", 2, "dir"))
    monkeypatch.setattr(
        paths,
        "_windows_directory_names",
        lambda _handle: (f"directory-{number:06d}" for number in range(100_000, -1, -1)),
    )
    monkeypatch.setattr(paths, "_windows_open_relative", lambda _handle, name: opened.append(name) or name)
    monkeypatch.setattr(paths, "_windows_is_reparse_point", lambda _child: False)
    monkeypatch.setattr(paths, "_windows_final_path", lambda child: child)
    monkeypatch.setattr(paths, "_windows_handle_metadata", lambda _child: (True, 0, 0))
    monkeypatch.setattr(paths, "_windows_is_within", lambda *_args: True)
    monkeypatch.setattr(paths, "_windows_close", lambda _handle: None)

    page = paths._windows_browse_directory_page("docs", "", [], 500, 700)

    assert len(opened) == 700
    assert [entry.name for entry in page.entries] == [
        f"directory-{number:06d}" for number in range(99_301, 99_801)
    ]
    assert page.truncated is True


def test_windows_browse_exact_cap_is_not_truncated(monkeypatch):
    import onesearch_agent.paths as paths

    monkeypatch.setattr(paths, "_windows_verified_directory", lambda *_args: (1, "root", 2, "dir"))
    monkeypatch.setattr(paths, "_windows_directory_names", lambda _handle: iter(("alpha", "beta")))
    monkeypatch.setattr(paths, "_windows_open_relative", lambda _handle, name: name)
    monkeypatch.setattr(paths, "_windows_is_reparse_point", lambda _child: False)
    monkeypatch.setattr(paths, "_windows_final_path", lambda child: child)
    monkeypatch.setattr(paths, "_windows_handle_metadata", lambda _child: (True, 0, 0))
    monkeypatch.setattr(paths, "_windows_is_within", lambda *_args: True)
    monkeypatch.setattr(paths, "_windows_close", lambda _handle: None)

    page = paths._windows_browse_directory_page("docs", "", [], 2, 10)

    assert [entry.name for entry in page.entries] == ["alpha", "beta"]
    assert page.truncated is False


@pytest.mark.asyncio
async def test_browse_listing_heartbeats_while_thread_is_slow(monkeypatch, tmp_path):
    class FastKeeper(worker.LeaseKeeper):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, interval=0.005, **kwargs)

    class Client(_Client):
        def __init__(self):
            super().__init__()
            self.heartbeats = 0

        async def job_heartbeat(self, *_args):
            self.heartbeats += 1

    def slow(*_args, **_kwargs):
        time.sleep(0.03)
        from onesearch_agent.paths import SafeDirectoryPage
        return SafeDirectoryPage((), False)

    monkeypatch.setattr(worker, "LeaseKeeper", FastKeeper)
    monkeypatch.setattr(worker, "list_confined_browse_directories_page", slow)
    client = Client()
    lease = AgentJobLease(id="slow", kind=JobKind.BROWSE, payload={"operation":"list", "root_id":"docs", "path":""}, lease_token="token")
    await worker.run_browse_job(lease, client, roots=[AllowedRoot(root_id="docs", path=str(tmp_path))])
    assert client.completions[0].status is JobStatus.SUCCEEDED and client.heartbeats >= 2


@pytest.mark.asyncio
async def test_browse_lost_lease_prevents_success_completion(monkeypatch, tmp_path):
    class LostLeaseClient(_Client):
        def __init__(self):
            super().__init__()
            self.cancelled = False

        async def job_heartbeat(self, *_args):
            from onesearch_agent.client import JobConflict
            raise JobConflict()

        async def cancel_ack(self, *_args):
            self.cancelled = True

        async def complete(self, *_args):
            from onesearch_agent.client import JobConflict
            raise JobConflict()

        async def job_status(self, _job_id):
            return type("Status", (), {"status": "cancelled", "handoff_released": False})()

    lease = AgentJobLease(id="lost", kind=JobKind.BROWSE, payload={"operation":"list", "root_id":"docs", "path":""}, lease_token="token")
    client = LostLeaseClient()
    await worker.run_browse_job(lease, client, roots=[AllowedRoot(root_id="docs", path=str(tmp_path))])
    assert client.cancelled is True and client.completions == []


@pytest.mark.asyncio
async def test_browse_listing_error_still_completes_failed(monkeypatch, tmp_path):
    def broken(*_args, **_kwargs):
        raise OSError("broken listing")

    monkeypatch.setattr(worker, "list_confined_browse_directories_page", broken)
    client = _Client()
    lease = AgentJobLease(id="error", kind=JobKind.BROWSE, payload={"operation":"list", "root_id":"docs", "path":""}, lease_token="token")
    await worker.run_browse_job(lease, client, roots=[AllowedRoot(root_id="docs", path=str(tmp_path))])
    assert client.completions[0].status is JobStatus.FAILED


@pytest.mark.asyncio
async def test_browse_expired_lease_returns_without_cancel_or_terminal_completion(tmp_path):
    class ExpiredLeaseClient(_Client):
        def __init__(self):
            super().__init__()
            self.cancel_acks = 0

        async def job_heartbeat(self, *_args):
            from onesearch_agent.client import JobLeaseError
            raise JobLeaseError()

        async def cancel_ack(self, *_args):
            self.cancel_acks += 1

        async def complete(self, *_args):
            raise AssertionError("expired lease must not send terminal completion")

    client = ExpiredLeaseClient()
    lease = AgentJobLease(id="expired", kind=JobKind.BROWSE, payload={"operation":"list", "root_id":"docs", "path":""}, lease_token="expired")
    await worker.run_browse_job(lease, client, roots=[AllowedRoot(root_id="docs", path=str(tmp_path))])
    assert client.cancel_acks == 0 and client.completions == []
