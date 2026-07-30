"""Verify every checked-out release version source agrees before publishing."""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path


def _pyproject_version(path: Path) -> str:
    match = re.search(r'^version = "([^"]+)"$', path.read_text(), re.MULTILINE)
    if match is None:
        raise ValueError(f"missing version in {path}")
    return match.group(1)


def verify(root: Path, expected: str) -> None:
    sources = {
        "root": _pyproject_version(root / "pyproject.toml"),
        "backend": _pyproject_version(root / "backend" / "pyproject.toml"),
        "cli": _pyproject_version(root / "cli" / "pyproject.toml"),
        "agent": _pyproject_version(root / "agent" / "pyproject.toml"),
        "agent runtime": re.search(
            r'^__version__ = "([^"]+)"$',
            (root / "agent" / "onesearch_agent" / "__init__.py").read_text(),
            re.MULTILINE,
        ).group(1),
        "frontend": json.loads((root / "frontend" / "package.json").read_text())["version"],
    }
    for name, actual in sources.items():
        if actual != expected:
            raise ValueError(f"{name} version {actual} does not match release version {expected}")


if __name__ == "__main__":
    try:
        verify(Path.cwd(), sys.argv[1])
    except (IndexError, OSError, ValueError, AttributeError) as error:
        raise SystemExit(str(error)) from error
