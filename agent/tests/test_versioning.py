from pathlib import Path

import pytest


def test_release_script_updates_agent_runtime_version():
    script = Path("scripts/release.py").read_text(encoding="utf-8")
    assert "AGENT_INIT" in script
    assert "bump_agent_init" in script


def test_release_bumps_actual_agent_init(tmp_path, monkeypatch):
    import scripts.release as release

    init = tmp_path / "__init__.py"
    init.write_text('__version__ = "1.3.0"\n')
    monkeypatch.setattr(release, "AGENT_INIT", init)
    release.bump_agent_init("1.4.0")
    assert init.read_text() == '__version__ = "1.4.0"\n'


def test_release_version_verifier_rejects_mismatched_checked_out_sources(tmp_path):
    from scripts.verify_release_version import verify

    for directory in ("", "backend", "cli", "agent", "shared"):
        path = tmp_path / directory / "pyproject.toml"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text('[project]\nversion = "1.3.0"\n')
    (tmp_path / "agent" / "onesearch_agent").mkdir()
    (tmp_path / "agent" / "onesearch_agent" / "__init__.py").write_text('__version__ = "1.3.0"\n')
    (tmp_path / "cli" / "onesearch").mkdir()
    (tmp_path / "cli" / "onesearch" / "__init__.py").write_text('__version__ = "1.3.0"\n')
    (tmp_path / "frontend").mkdir()
    (tmp_path / "frontend" / "package.json").write_text('{"version": "1.3.0"}')
    verify(tmp_path, "1.3.0")
    (tmp_path / "cli" / "pyproject.toml").write_text('[project]\nversion = "9.9.9"\n')
    with pytest.raises(ValueError, match="cli"):
        verify(tmp_path, "1.3.0")


def test_agent_release_verifies_source_versions_before_native_and_image_publish():
    workflow = Path(".github/workflows/agent-release.yml").read_text()
    assert workflow.count("scripts/verify_release_version.py") >= 2
