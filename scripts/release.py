#!/usr/bin/env python3
"""
Release script for OneSearch.

Usage:
    python scripts/release.py patch     # 0.8.0 -> 0.8.1  (bug fixes)
    python scripts/release.py minor     # 0.8.0 -> 0.9.0  (new features)
    python scripts/release.py major     # 0.8.0 -> 1.0.0  (breaking changes)
    python scripts/release.py 0.9.1     # explicit version

What this does:
  1. Bumps version in all 5 places:
       pyproject.toml (root workspace)
       backend/pyproject.toml
       cli/pyproject.toml
       cli/onesearch/__init__.py
       frontend/package.json + package-lock.json (via npm)
  2. Promotes [Unreleased] section in CHANGELOG.md to versioned entry
  3. Appends comparison link at the CHANGELOG footer
  4. Commits all changed files
  5. Creates and pushes git tag (e.g. v0.9.0)
  6. Creates GitHub release with CHANGELOG notes
  -> Docker CI picks up the release and builds/pushes:
       ghcr.io/demigodmode/onesearch:0.9.0
       ghcr.io/demigodmode/onesearch:0.9
       ghcr.io/demigodmode/onesearch:latest
       docker.io/demigodmode/onesearch:0.9.0  (same tags)
"""

import json
import os
import re
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).parent.parent

# Version files
ROOT_PYPROJECT   = ROOT / "pyproject.toml"
BACKEND_PYPROJECT = ROOT / "backend" / "pyproject.toml"
CLI_PYPROJECT    = ROOT / "cli" / "pyproject.toml"
CLI_INIT         = ROOT / "cli" / "onesearch" / "__init__.py"
FRONTEND_PKG     = ROOT / "frontend" / "package.json"
CHANGELOG        = ROOT / "CHANGELOG.md"

REPO = "demigodmode/OneSearch"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def run(cmd, check=True, capture=False, cwd=None):
    return subprocess.run(
        cmd, shell=True, check=check,
        capture_output=capture, text=True,
        cwd=cwd or ROOT,
    )


def die(msg: str):
    print(f"\nError: {msg}", file=sys.stderr)
    sys.exit(1)


def confirm(prompt: str) -> bool:
    return input(f"{prompt} [y/N] ").strip().lower() == "y"


# ---------------------------------------------------------------------------
# Version helpers
# ---------------------------------------------------------------------------

def get_current_version() -> str:
    content = ROOT_PYPROJECT.read_text(encoding="utf-8")
    m = re.search(r'^version = "([^"]+)"', content, re.MULTILINE)
    if not m:
        die("Could not find version in pyproject.toml")
    return m.group(1)


def bump_version(current: str, bump: str) -> str:
    if re.match(r'^\d+\.\d+\.\d+$', bump):
        return bump
    major, minor, patch = (int(x) for x in current.split("."))
    if bump == "major":
        return f"{major + 1}.0.0"
    if bump == "minor":
        return f"{major}.{minor + 1}.0"
    if bump == "patch":
        return f"{major}.{minor}.{patch + 1}"
    die(f"Unknown bump type: {bump}")


def bump_toml_version(path: Path, new_version: str):
    content = path.read_text(encoding="utf-8")
    new_content, count = re.subn(
        r'^(version = ")[^"]+(")',
        rf'\g<1>{new_version}\g<2>',
        content,
        flags=re.MULTILINE,
    )
    if count == 0:
        die(f"Could not find version field in {path}")
    path.write_text(new_content, encoding="utf-8")


def bump_cli_init(new_version: str):
    content = CLI_INIT.read_text(encoding="utf-8")
    new_content, count = re.subn(
        r'^(__version__ = ")[^"]+(")',
        rf'\g<1>{new_version}\g<2>',
        content,
        flags=re.MULTILINE,
    )
    if count == 0:
        die(f"Could not find __version__ in {CLI_INIT}")
    CLI_INIT.write_text(new_content, encoding="utf-8")


def bump_frontend(new_version: str):
    # npm version updates both package.json and package-lock.json atomically
    # --no-git-tag-version: don't let npm create a commit or tag
    result = run(
        f"npm version {new_version} --no-git-tag-version",
        check=False,
        capture=True,
        cwd=ROOT / "frontend",
    )
    if result.returncode != 0:
        die(f"npm version failed:\n{result.stderr}")


# ---------------------------------------------------------------------------
# CHANGELOG helpers
# ---------------------------------------------------------------------------

UNRELEASED_RE = re.compile(
    r"(^## \[Unreleased\][^\n]*\n)(.*?)(?=^## \[|\Z)",
    re.MULTILINE | re.DOTALL,
)

FOOTER_LINKS_RE = re.compile(r"^\[[\d.]+\]: https://", re.MULTILINE)


def get_unreleased_notes() -> str | None:
    content = CHANGELOG.read_text(encoding="utf-8")
    m = UNRELEASED_RE.search(content)
    if not m:
        return None
    notes = re.sub(r"<!--.*?-->", "", m.group(2), flags=re.DOTALL).strip()
    return notes or None


def promote_unreleased(new_version: str, today: str) -> str:
    content = CHANGELOG.read_text(encoding="utf-8")
    m = UNRELEASED_RE.search(content)

    if m:
        body = m.group(2).strip()
        entry = f"## [{new_version}] - {today}\n\n{body}\n\n---\n\n"
        new_content = content[: m.start()] + entry + content[m.end():]
    else:
        body = "### Changed\n\n- See commit history for details."
        entry = f"## [{new_version}] - {today}\n\n{body}\n\n---\n\n"
        first = re.search(r"^## \[", content, re.MULTILINE)
        if first:
            new_content = content[: first.start()] + entry + content[first.start():]
        else:
            new_content = content.rstrip() + "\n\n" + entry

    CHANGELOG.write_text(new_content, encoding="utf-8")
    return body


def get_previous_version() -> str | None:
    """Find the most recent versioned entry in CHANGELOG."""
    content = CHANGELOG.read_text(encoding="utf-8")
    matches = re.findall(r"^## \[(\d+\.\d+\.\d+)\]", content, re.MULTILINE)
    return matches[0] if matches else None


def append_changelog_link(new_version: str):
    content = CHANGELOG.read_text(encoding="utf-8")
    prev = get_previous_version()

    if prev:
        new_link = f"[{new_version}]: https://github.com/{REPO}/compare/v{prev}...v{new_version}"
    else:
        new_link = f"[{new_version}]: https://github.com/{REPO}/releases/tag/v{new_version}"

    # Insert before existing footer links, or append at end
    first_link = FOOTER_LINKS_RE.search(content)
    if first_link:
        new_content = content[: first_link.start()] + new_link + "\n" + content[first_link.start():]
    else:
        new_content = content.rstrip() + "\n\n" + new_link + "\n"

    CHANGELOG.write_text(new_content, encoding="utf-8")


def get_version_notes(version: str) -> str:
    content = CHANGELOG.read_text(encoding="utf-8")
    m = re.search(
        rf"^## \[{re.escape(version)}\][^\n]*\n(.*?)(?=^---|\Z)",
        content,
        re.MULTILINE | re.DOTALL,
    )
    return m.group(1).strip() if m else f"Release {version}"


# ---------------------------------------------------------------------------
# Git / gh helpers
# ---------------------------------------------------------------------------

def check_git_clean():
    result = run("git status --porcelain", capture=True)
    dirty = result.stdout.strip()
    if dirty:
        print("Uncommitted changes detected:")
        print(dirty)
        if not confirm("Continue anyway?"):
            sys.exit(0)


def check_on_main():
    result = run("git branch --show-current", capture=True)
    branch = result.stdout.strip()
    if branch != "main":
        print(f"Current branch: {branch}")
        if not confirm("You're not on main. Continue?"):
            sys.exit(0)


def tag_exists(tag: str) -> bool:
    result = run(f"git tag -l {tag}", capture=True)
    return bool(result.stdout.strip())


def check_gh():
    r = run("gh --version", check=False, capture=True)
    if r.returncode != 0:
        die("gh CLI not found. Install from https://cli.github.com/")


def create_gh_release(tag: str, notes: str):
    with tempfile.NamedTemporaryFile(mode="w", suffix=".md", delete=False, encoding="utf-8") as f:
        f.write(notes)
        notes_file = f.name
    try:
        run(f'gh release create {tag} --title "{tag}" --notes-file "{notes_file}"')
    finally:
        os.unlink(notes_file)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)

    bump = sys.argv[1]
    if bump not in ("patch", "minor", "major") and not re.match(r'^\d+\.\d+\.\d+$', bump):
        die(f"Invalid argument: {bump}\nUse: patch, minor, major, or X.Y.Z")

    check_gh()
    check_on_main()
    check_git_clean()

    current = get_current_version()
    new_version = bump_version(current, bump)
    tag = f"v{new_version}"
    today = datetime.now(timezone.utc).date().isoformat()

    print(f"\n  {current}  ->  {new_version}  ({tag})\n")

    if tag_exists(tag):
        die(f"Tag {tag} already exists.")

    # CHANGELOG check
    unreleased = get_unreleased_notes()
    if unreleased:
        lines = unreleased.count("\n") + 1
        print(f"CHANGELOG [Unreleased] found ({lines} lines) — will be promoted to {new_version}")
    else:
        print("No [Unreleased] section found in CHANGELOG.md")
        print("Will insert a placeholder entry. Update CHANGELOG.md first for a real release.")
        if not confirm("Continue with placeholder?"):
            print("Aborting. Add an [Unreleased] section to CHANGELOG.md first.")
            sys.exit(0)

    print(f"\nThis will:")
    print(f"  1. Bump version in 5 files to {new_version}")
    print(f"       pyproject.toml (root workspace)")
    print(f"       backend/pyproject.toml")
    print(f"       cli/pyproject.toml")
    print(f"       cli/onesearch/__init__.py")
    print(f"       frontend/package.json + package-lock.json")
    print(f"  2. Promote CHANGELOG.md [Unreleased] -> {new_version}")
    print(f"  3. Append comparison link to CHANGELOG.md footer")
    print(f"  4. Commit all changed files")
    print(f"  5. Create and push tag {tag}")
    print(f"  6. Create GitHub release {tag}")
    print(f"  -> Docker CI builds and pushes:")
    print(f"       ghcr.io/demigodmode/onesearch:{new_version}")
    print(f"       ghcr.io/demigodmode/onesearch:{new_version.rsplit('.', 1)[0]}")
    print(f"       ghcr.io/demigodmode/onesearch:latest")
    print(f"       docker.io/demigodmode/onesearch (same tags)\n")

    if not confirm("Proceed?"):
        sys.exit(0)

    # --- Bump version files ---
    print("\nBumping version files...")
    bump_toml_version(ROOT_PYPROJECT, new_version)
    print(f"  ✓ pyproject.toml")
    bump_toml_version(BACKEND_PYPROJECT, new_version)
    print(f"  ✓ backend/pyproject.toml")
    bump_toml_version(CLI_PYPROJECT, new_version)
    print(f"  ✓ cli/pyproject.toml")
    bump_cli_init(new_version)
    print(f"  ✓ cli/onesearch/__init__.py")
    bump_frontend(new_version)
    print(f"  ✓ frontend/package.json + package-lock.json")

    # --- CHANGELOG ---
    print("\nUpdating CHANGELOG.md...")
    promote_unreleased(new_version, today)
    append_changelog_link(new_version)
    print(f"  ✓ Promoted [Unreleased] -> [{new_version}]")
    print(f"  ✓ Added comparison link")

    # --- Commit ---
    print("\nCommitting...")
    run(
        "git add "
        "pyproject.toml "
        "backend/pyproject.toml "
        "cli/pyproject.toml "
        "cli/onesearch/__init__.py "
        "frontend/package.json "
        "frontend/package-lock.json "
        "CHANGELOG.md"
    )
    run(f'git commit -m "release {tag}"')
    print(f"  ✓ Committed")

    # --- Tag & push ---
    print(f"\nTagging {tag}...")
    run(f"git tag {tag}")
    print("Pushing commits and tag...")
    run("git push")
    run("git push --tags")
    print(f"  ✓ Pushed")

    # --- GitHub release ---
    print("\nCreating GitHub release...")
    notes = get_version_notes(new_version)
    create_gh_release(tag, notes)
    print(f"  ✓ GitHub release created")

    # --- Done ---
    minor_tag = new_version.rsplit('.', 1)[0]
    print(f"""
Done. {tag} is live.

  GitHub release:  https://github.com/{REPO}/releases/tag/{tag}
  Actions (build): https://github.com/{REPO}/actions
  GHCR image:      ghcr.io/demigodmode/onesearch:{new_version}
  Docker Hub:      docker.io/demigodmode/onesearch:{new_version}
  Latest tags:     :{minor_tag}  :latest

Docker build is running in CI — check Actions for progress.
""")


if __name__ == "__main__":
    main()
