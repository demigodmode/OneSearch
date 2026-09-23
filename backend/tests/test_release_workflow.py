# Copyright (C) 2025 demigodmode
# SPDX-License-Identifier: AGPL-3.0-only

"""Static safety checks for release workflows."""
from pathlib import Path

import yaml

DOCKER_WORKFLOW = Path(".github/workflows/docker-publish.yml")
AGENT_WORKFLOW = Path(".github/workflows/agent-release.yml")


def _step(text: str, name: str, next_name: str | None = None) -> str:
    start = text.index(f"      - name: {name}")
    if next_name is None:
        return text[start:]
    end = text.index(f"      - name: {next_name}", start)
    return text[start:end]


def _agent_workflow() -> dict:
    return yaml.safe_load(AGENT_WORKFLOW.read_text(encoding="utf-8"))


def _action_name(uses: str | None) -> str:
    # dependabot bumps the @version, the checks care about which action it is
    return (uses or "").split("@", 1)[0]


def _action_step(job: dict, action: str) -> list[dict]:
    return [step for step in job["steps"] if _action_name(step.get("uses")) == action]


def test_release_reclaims_only_build_cache_before_buildx():
    text = DOCKER_WORKFLOW.read_text(encoding="utf-8")
    cleanup = _step(text, "Reclaim Docker build space", "Set up Docker Buildx")

    assert text.index("Reclaim Docker build space") < text.index("Set up Docker Buildx")
    assert "rm -rf /tmp/.buildx-cache /tmp/.buildx-cache-new" in cleanup
    assert "docker builder prune --all --force" in cleanup
    assert "docker system prune" not in cleanup
    assert "docker volume prune" not in cleanup


def test_release_cleans_incomplete_cache_even_after_failure():
    text = DOCKER_WORKFLOW.read_text(encoding="utf-8")
    cleanup = _step(text, "Clean up Docker build data")

    assert "if: always()" in cleanup
    assert "rm -rf /tmp/.buildx-cache-new" in cleanup
    assert "docker builder prune --all --force" in cleanup


def test_agent_workflow_yaml_parses_and_preserves_release_trigger():
    workflow = _agent_workflow()

    assert workflow[True]["release"]["types"] == ["published"]


def test_agent_manual_validation_job_has_only_a_read_token_and_no_secrets():
    workflow = _agent_workflow()
    job = workflow["jobs"]["validate"]

    assert workflow["permissions"] == {"contents": "read"}
    assert job["if"] == "github.event_name == 'workflow_dispatch'"
    assert job["permissions"] == {"contents": "read"}
    assert "environment" not in job
    assert "secrets." not in str(job)
    assert _action_step(job, "actions/checkout")[0]["with"]["ref"] == "${{ inputs.ref }}"


def test_agent_manual_validation_always_records_a_nonpublication_summary():
    job = _agent_workflow()["jobs"]["validate"]
    summary = next(step for step in job["steps"] if step.get("name") == "Summarize validation-only build")

    assert "if" not in summary
    assert "No registry or release publication occurred." in summary["run"]


def test_agent_release_publication_is_isolated_in_a_protected_write_job():
    workflow = _agent_workflow()
    job = workflow["jobs"]["release-publish"]

    assert job["if"] == "github.event_name == 'release'"
    assert job["permissions"] == {"contents": "write", "packages": "write"}
    assert job["environment"] == "release"
    assert _action_step(job, "actions/checkout")[0]["with"]["ref"] == "${{ github.sha }}"
    assert job["env"]["DOCKERHUB_USERNAME"] == "${{ secrets.DOCKERHUB_USERNAME }}"
    assert job["env"]["DOCKERHUB_TOKEN"] == "${{ secrets.DOCKERHUB_TOKEN }}"


def test_agent_release_tag_and_version_are_verified_before_every_publish_side_effect():
    workflow = _agent_workflow()
    jobs = workflow["jobs"]

    for name in ("release-native", "release-publish"):
        job = jobs[name]
        assert job["if"] == "github.event_name == 'release'"
        assert _action_step(job, "actions/checkout")[0]["with"]["ref"] == "${{ github.sha }}"
        tag_check = next(
            index
            for index, step in enumerate(job["steps"])
            if step.get("name") == "Verify immutable release tag and source versions"
        )
        assert "refs/tags/$TAG^{commit}" in job["steps"][tag_check]["run"]
        assert "GITHUB_SHA" in job["steps"][tag_check]["run"]
        for index, step in enumerate(job["steps"]):
            if _action_name(step.get("uses")) in {
                "actions/upload-artifact",
                "docker/login-action",
                "docker/build-push-action",
                "softprops/action-gh-release",
            } or step.get("name") == "Create signed manifests and checksums":
                assert tag_check < index

    publish = jobs["release-publish"]
    dockerhub_steps = _action_step(publish, "docker/login-action")[1:]
    assert all("env.DOCKERHUB_" in step["if"] for step in dockerhub_steps)
    assert all("secrets." not in step["if"] for step in dockerhub_steps)
    image_pushes = _action_step(publish, "docker/build-push-action")
    assert all(step["with"]["push"] is True for step in image_pushes)
    assert all(":latest" in step["with"]["tags"] for step in image_pushes)
    assert _action_step(publish, "softprops/action-gh-release")
    assert any(step.get("name") == "Create signed manifests and checksums" for step in publish["steps"])


def test_agent_release_native_embeds_a_valid_key_only_after_tag_verification():
    job = _agent_workflow()["jobs"]["release-native"]
    tag_check = next(
        index
        for index, step in enumerate(job["steps"])
        if step.get("name") == "Verify immutable release tag and source versions"
    )
    key_setup = next(
        index
        for index, step in enumerate(job["steps"])
        if step.get("name") == "Validate and embed release public key"
    )
    package = next(
        index for index, step in enumerate(job["steps"]) if "pyinstaller" in step.get("run", "")
    )

    assert job["permissions"] == {"contents": "read"}
    assert job["environment"] == "release"
    assert job["env"]["AGENT_UPDATE_PUBLIC_KEY"] == "${{ secrets.AGENT_UPDATE_PUBLIC_KEY }}"
    assert tag_check < key_setup < package
    assert "validate_public_key" in job["steps"][key_setup]["run"]
    assert "release_public_key.txt" in job["steps"][key_setup]["run"]

    publish = _agent_workflow()["jobs"]["release-publish"]
    assert all(
        "AGENT_UPDATE_PUBLIC_KEY=${{ env.AGENT_UPDATE_PUBLIC_KEY }}" in step["with"]["build-args"]
        for step in _action_step(publish, "docker/build-push-action")
    )
    dockerfile = Path("agent/Dockerfile").read_text(encoding="utf-8")
    assert "ARG AGENT_UPDATE_PUBLIC_KEY" in dockerfile
    assert "release_public_key.txt" in dockerfile
