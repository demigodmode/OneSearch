# Copyright (C) 2025 demigodmode
# SPDX-License-Identifier: AGPL-3.0-only

"""Behavior checks for the local release-version helpers."""

from pathlib import Path
from stat import S_IMODE

import pytest


def _write_pyproject(path: Path, version: str | None = "1.3.0") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    version_line = f'version = "{version}"\n' if version is not None else ""
    path.write_text(f"[project]\n{version_line}", encoding="utf-8")


def _write_release_sources(root: Path, shared_version: str | None = "1.3.0") -> None:
    for directory in ("", "backend", "cli", "agent"):
        _write_pyproject(root / directory / "pyproject.toml")
    _write_pyproject(root / "shared" / "pyproject.toml", shared_version)
    agent_init = root / "agent" / "onesearch_agent" / "__init__.py"
    agent_init.parent.mkdir()
    agent_init.write_text('__version__ = "1.3.0"\n', encoding="utf-8")
    cli_init = root / "cli" / "onesearch" / "__init__.py"
    cli_init.parent.mkdir()
    cli_init.write_text('__version__ = "1.3.0"\n', encoding="utf-8")
    frontend = root / "frontend"
    frontend.mkdir()
    (frontend / "package.json").write_text('{"version": "1.3.0"}', encoding="utf-8")
    (frontend / "package-lock.json").write_text('{"version": "1.3.0"}', encoding="utf-8")


def _version_files(root: Path) -> tuple[Path, ...]:
    return (
        *(root / directory / "pyproject.toml" for directory in ("", "backend", "cli", "agent", "shared")),
        root / "agent" / "onesearch_agent" / "__init__.py",
        root / "cli" / "onesearch" / "__init__.py",
        root / "frontend" / "package.json",
        root / "frontend" / "package-lock.json",
    )


def _configure_update(release, version_files: tuple[Path, ...], monkeypatch) -> None:
    monkeypatch.setattr(release, "TOML_VERSION_FILES", version_files[:5])
    monkeypatch.setattr(release, "AGENT_INIT", version_files[5])
    monkeypatch.setattr(release, "CLI_INIT", version_files[6])
    monkeypatch.setattr(release, "FRONTEND_PKG", version_files[7])
    monkeypatch.setattr(release, "FRONTEND_LOCK", version_files[8])
    monkeypatch.setattr(release, "VERSION_FILES", version_files)


def test_release_bumps_shared_pyproject_with_every_other_pyproject(tmp_path, monkeypatch):
    import scripts.release as release

    _write_release_sources(tmp_path)
    toml_files = tuple(
        tmp_path / directory / "pyproject.toml"
        for directory in ("", "backend", "cli", "agent", "shared")
    )
    monkeypatch.setattr(release, "TOML_VERSION_FILES", toml_files)

    release.bump_toml_versions("1.4.0")

    assert all('version = "1.4.0"' in path.read_text(encoding="utf-8") for path in toml_files)


def test_release_does_not_partially_bump_pyprojects_when_shared_is_missing(tmp_path, monkeypatch):
    import scripts.release as release

    _write_release_sources(tmp_path)
    toml_files = tuple(
        tmp_path / directory / "pyproject.toml"
        for directory in ("", "backend", "cli", "agent", "shared")
    )
    (tmp_path / "shared" / "pyproject.toml").unlink()
    monkeypatch.setattr(release, "TOML_VERSION_FILES", toml_files)

    with pytest.raises(OSError, match=r"shared/pyproject.toml"):
        release.bump_toml_versions("1.4.0")

    assert all(
        'version = "1.3.0"' in path.read_text(encoding="utf-8")
        for path in toml_files[:-1]
    )


def test_verify_accepts_all_matching_sources_including_shared(tmp_path):
    from scripts.verify_release_version import verify

    _write_release_sources(tmp_path)

    verify(tmp_path, "1.3.0")


def test_verify_rejects_a_shared_package_version_mismatch(tmp_path):
    from scripts.verify_release_version import verify

    _write_release_sources(tmp_path, shared_version="9.9.9")

    with pytest.raises(
        ValueError,
        match=r"shared version 9.9.9 does not match release version 1.3.0",
    ):
        verify(tmp_path, "1.3.0")


def test_verify_rejects_a_cli_runtime_version_mismatch(tmp_path):
    from scripts.verify_release_version import verify

    _write_release_sources(tmp_path)
    (tmp_path / "cli" / "onesearch" / "__init__.py").write_text(
        '__version__ = "9.9.9"\n', encoding="utf-8"
    )

    with pytest.raises(
        ValueError,
        match=r"cli runtime version 9.9.9 does not match release version 1.3.0",
    ):
        verify(tmp_path, "1.3.0")


def test_verifier_covers_every_release_version_source():
    import scripts.release as release
    import scripts.verify_release_version as verifier

    assert verifier.RELEASE_VERSION_SOURCES is release.RELEASE_VERSION_SOURCES


def test_release_update_changes_every_version_source(tmp_path, monkeypatch):
    import scripts.release as release

    _write_release_sources(tmp_path)
    version_files = _version_files(tmp_path)
    _configure_update(release, version_files, monkeypatch)

    def bump_frontend(version: str) -> None:
        for path in version_files[-2:]:
            path.write_text(f'{{"version": "{version}"}}', encoding="utf-8")

    monkeypatch.setattr(release, "bump_frontend", bump_frontend)

    release.update_version("1.4.0")

    assert all(b"1.4.0" in path.read_bytes() for path in version_files)


def test_release_update_preserves_each_version_file_mode(tmp_path, monkeypatch):
    import scripts.release as release

    _write_release_sources(tmp_path)
    version_files = _version_files(tmp_path)
    expected_modes = {path: 0o755 if "__init__" in path.name else 0o644 for path in version_files}
    for path, mode in expected_modes.items():
        path.chmod(mode)
    _configure_update(release, version_files, monkeypatch)
    monkeypatch.setattr(release, "bump_frontend", lambda _version: None)

    release.update_version("1.4.0")

    assert {path: S_IMODE(path.stat().st_mode) for path in version_files} == expected_modes


@pytest.mark.parametrize(
    "path_suffix, content",
    [
        ("shared/pyproject.toml", b"[project]\r\nversion = \"1.3.0\"\r\nname = \"shared\""),
        ("cli/onesearch/__init__.py", b"# mixed\n__version__ = \"1.3.0\"\r\n"),
    ],
)
def test_release_update_preserves_exact_line_endings_outside_version_token(
    tmp_path, monkeypatch, path_suffix, content
):
    import scripts.release as release

    _write_release_sources(tmp_path)
    target = tmp_path / path_suffix
    target.write_bytes(content)
    version_files = _version_files(tmp_path)
    _configure_update(release, version_files, monkeypatch)
    monkeypatch.setattr(release, "bump_frontend", lambda _version: None)

    release.update_version("1.4.0")

    assert target.read_bytes() == content.replace(b"1.3.0", b"1.4.0")


@pytest.mark.parametrize("failure_point", ["toml", "agent_init", "frontend"])
def test_release_update_rolls_back_every_version_file_after_a_failure(
    tmp_path, monkeypatch, failure_point
):
    import scripts.release as release

    _write_release_sources(tmp_path)
    version_files = _version_files(tmp_path)
    original = {path: path.read_bytes() for path in version_files}
    _configure_update(release, version_files, monkeypatch)

    if failure_point == "frontend":
        def fail_frontend(_version: str) -> None:
            version_files[7].write_bytes(b'{"version": "broken"}')
            raise RuntimeError("npm failed")

        monkeypatch.setattr(release, "bump_frontend", fail_frontend)
    else:
        original_replace = release._replace_staged
        failing_path = version_files[2 if failure_point == "toml" else 5]

        def fail_replace(path: Path, content: bytes, *_args) -> None:
            if path == failing_path:
                raise OSError("injected replacement failure")
            original_replace(path, content, *_args)

        monkeypatch.setattr(release, "_replace_staged", fail_replace)

    with pytest.raises((OSError, RuntimeError)):
        release.update_version("1.4.0")

    assert {path: path.read_bytes() for path in version_files} == original
    assert not list(tmp_path.rglob(".release-version-*"))


@pytest.mark.parametrize("operation", ["chmod", "cleanup"])
def test_release_update_rolls_back_when_atomic_writer_cannot_finish(
    tmp_path, monkeypatch, operation
):
    import scripts.release as release

    _write_release_sources(tmp_path)
    version_files = _version_files(tmp_path)
    original = {path: path.read_bytes() for path in version_files}
    _configure_update(release, version_files, monkeypatch)
    monkeypatch.setattr(release, "bump_frontend", lambda _version: None)

    if operation == "chmod":
        original_chmod = release.os.chmod
        failed = False

        def fail_chmod(path, mode):
            nonlocal failed
            if not failed and Path(path).name.startswith(".release-version-"):
                failed = True
                raise OSError("injected chmod failure")
            original_chmod(path, mode)

        monkeypatch.setattr(release.os, "chmod", fail_chmod)
    else:
        original_unlink = Path.unlink
        failed = False

        def fail_once(path, *args, **kwargs):
            nonlocal failed
            if not failed and path.name.startswith(".release-version-"):
                failed = True
                raise OSError("injected cleanup failure")
            return original_unlink(path, *args, **kwargs)

        monkeypatch.setattr(release.Path, "unlink", fail_once)

    with pytest.raises(OSError):
        release.update_version("1.4.0")

    assert {path: path.read_bytes() for path in version_files} == original
    assert not list(tmp_path.rglob(".release-version-*"))


def test_verify_rejects_a_missing_shared_version(tmp_path):
    from scripts.verify_release_version import verify

    _write_release_sources(tmp_path, shared_version=None)

    with pytest.raises(ValueError, match=r"missing version in .*shared/pyproject.toml"):
        verify(tmp_path, "1.3.0")


def test_verify_rejects_a_missing_shared_pyproject(tmp_path):
    from scripts.verify_release_version import verify

    _write_release_sources(tmp_path)
    (tmp_path / "shared" / "pyproject.toml").unlink()

    with pytest.raises(OSError, match=r"shared/pyproject.toml"):
        verify(tmp_path, "1.3.0")
