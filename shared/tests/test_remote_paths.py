import pytest
from onesearch_shared.remote_paths import RemotePathError, resolve_remote_source_root


@pytest.mark.parametrize(
    ("platform", "source", "roots", "expected"),
    [
        ("linux", "/srv/docs", [{"root_id": "docs", "path": "/srv/docs"}], ("docs", "")),
        (
            "linux",
            "/srv/docs/team",
            [{"root_id": "docs", "path": "/srv/docs"}],
            ("docs", "team"),
        ),
        (
            "windows-x64",
            r"C:\Data\Docs\Team",
            [{"root_id": "docs", "path": r"c:\data\docs"}],
            ("docs", "Team"),
        ),
        (
            "linux",
            "/srv/docs/team/private",
            [
                {"root_id": "docs", "path": "/srv/docs"},
                {"root_id": "team", "path": "/srv/docs/team"},
            ],
            ("team", "private"),
        ),
    ],
)
def test_resolve_remote_source_root(platform, source, roots, expected):
    assert resolve_remote_source_root(platform, source, roots) == expected


@pytest.mark.parametrize(
    ("platform", "source", "roots"),
    [
        ("linux", "/srv/docs2", [{"root_id": "docs", "path": "/srv/docs"}]),
        ("linux", "/srv/docs/../secret", [{"root_id": "docs", "path": "/srv/docs"}]),
        ("linux", r"\srv\docs", [{"root_id": "docs", "path": "/srv/docs"}]),
        ("windows", r"C:\Data\Docs", [{"root_id": "docs", "path": "C:/Data/Docs"}]),
        ("windows", r"C:Data\Docs", [{"root_id": "docs", "path": r"C:\Data"}]),
        ("linux", "/srv/docs", [{"root_id": "docs", "path": "relative"}]),
        (
            "linux",
            "/srv/docs",
            [
                {"root_id": "docs", "path": "/srv"},
                {"root_id": "docs", "path": "/srv/docs"},
            ],
        ),
        (
            "linux",
            "/srv/docs",
            [
                {"root_id": "one", "path": "/srv/docs"},
                {"root_id": "two", "path": "/srv/docs"},
            ],
        ),
        ("linux", "/srv/docs", [{"root_id": "docs"}]),
    ],
)
def test_resolve_remote_source_root_rejects_unsafe_or_ambiguous_mappings(platform, source, roots):
    with pytest.raises(RemotePathError):
        resolve_remote_source_root(platform, source, roots)
