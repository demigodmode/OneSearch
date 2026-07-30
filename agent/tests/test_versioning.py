from pathlib import Path


def test_release_script_updates_agent_runtime_version():
    script = Path("scripts/release.py").read_text(encoding="utf-8")
    assert "AGENT_INIT" in script
    assert "bump_agent_init" in script
