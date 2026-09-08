"""Verify every checked-out release version source agrees before publishing."""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

from scripts.release import RELEASE_VERSION_SOURCES


def _pyproject_version(path: Path) -> str:
    match = re.search(r'^version = "([^"]+)"$', path.read_text(), re.MULTILINE)
    if match is None:
        raise ValueError(f"missing version in {path}")
    return match.group(1)


def _runtime_version(path: Path) -> str:
    match = re.search(r'^__version__ = "([^"]+)"$', path.read_text(), re.MULTILINE)
    if match is None:
        raise ValueError(f"missing __version__ in {path}")
    return match.group(1)


def _json_version(path: Path) -> str:
    return json.loads(path.read_text())["version"]


def verify(root: Path, expected: str) -> None:
    parsers = {"toml": _pyproject_version, "runtime": _runtime_version, "json": _json_version}
    sources = {
        name: parsers[kind](root / relative_path)
        for name, (relative_path, kind) in RELEASE_VERSION_SOURCES.items()
    }
    for name, actual in sources.items():
        if actual != expected:
            raise ValueError(f"{name} version {actual} does not match release version {expected}")


if __name__ == "__main__":
    try:
        verify(Path.cwd(), sys.argv[1])
    except (IndexError, OSError, ValueError, AttributeError) as error:
        raise SystemExit(str(error)) from error
