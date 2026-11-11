"""Prepare a release: one command instead of a checklist of edits.

Usage: uv run python scripts/prepare_release.py 0.4.1 "Short title"

What it changes:

- the version in ``pyproject.toml``, ``src/chattice/__init__.py`` and the
  three documentation lines that state it;
- ``CHANGELOG.md``: the ``[Unreleased]`` section becomes the release
  section (it must exist and have content);
- ``uv.lock``, the SBOM and ``THIRD_PARTY_NOTICES.md``, regenerated.

It does not commit, tag or publish. It prints the remaining commands.
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path

_ROOT = Path(__file__).parents[1]
_VERSION = re.compile(r"\d+\.\d+\.\d+")
_UNRELEASED = "## [Unreleased]"

# (file, pattern with the version in group 2). Each must match exactly once.
VERSION_SITES: tuple[tuple[str, str], ...] = (
    ("pyproject.toml", r'(?m)^(version = ")(\d+\.\d+\.\d+)(")$'),
    ("src/chattice/__init__.py", r'(?m)^(__version__ = ")(\d+\.\d+\.\d+)(")$'),
    ("README.md", r"(\(current version )(\d+\.\d+\.\d+)(\))"),
    (
        "docs/getting-started/installation.md",
        r"(The output for this documentation line is `)(\d+\.\d+\.\d+)(`\.)",
    ),
    ("docs/reference/compatibility.md", r"(\| Chattice \| )(\d+\.\d+\.\d+)( \|)"),
    ("docs/public-api.md", r"(Public API snapshot for Chattice )(\d+\.\d+\.\d+)(\.)"),
)


class ReleaseError(Exception):
    """The repository is not in a state a release can be prepared from."""


def _as_tuple(version: str) -> tuple[int, ...]:
    return tuple(int(part) for part in version.split("."))


def current_version(root: Path) -> str:
    path, pattern = VERSION_SITES[0]
    match = re.search(pattern, (root / path).read_text())
    if match is None:
        raise ReleaseError(f"no version found in {path}")
    return match.group(2)


def bump_version_sites(root: Path, version: str) -> list[str]:
    """Write ``version`` into every place that states it; return the files."""
    changed: list[str] = []
    for path, pattern in VERSION_SITES:
        file = root / path
        text = file.read_text()
        updated, count = re.subn(pattern, rf"\g<1>{version}\g<3>", text)
        if count != 1:
            raise ReleaseError(
                f"{path}: expected exactly one version line, found {count}"
            )
        if updated != text:
            file.write_text(updated)
            changed.append(path)
    return changed


def release_changelog(text: str, version: str, title: str) -> str:
    """Turn the ``[Unreleased]`` section into the section of ``version``."""
    if text.count(_UNRELEASED) != 1:
        raise ReleaseError(
            f"CHANGELOG.md needs exactly one '{_UNRELEASED}' section to release"
        )
    start = text.index(_UNRELEASED)
    following = text.find("\n## [", start + len(_UNRELEASED))
    body = text[start + len(_UNRELEASED) : following if following != -1 else None]
    if not body.strip():
        raise ReleaseError("the [Unreleased] section of CHANGELOG.md is empty")
    return text.replace(_UNRELEASED, f"## [{version}] — {title}", 1)


def prepare(root: Path, version: str, title: str) -> list[str]:
    """Apply every file edit of a release; return the changed files."""
    if _VERSION.fullmatch(version) is None:
        raise ReleaseError(f"version must look like 1.2.3; got {version!r}")
    if not title.strip():
        raise ReleaseError("a short release title is required")
    previous = current_version(root)
    if _as_tuple(version) <= _as_tuple(previous):
        raise ReleaseError(f"{version} is not newer than the current {previous}")
    changelog = root / "CHANGELOG.md"
    # Validate the changelog before touching any file.
    released = release_changelog(changelog.read_text(), version, title.strip())
    changed = bump_version_sites(root, version)
    changelog.write_text(released)
    return [*changed, "CHANGELOG.md"]


def _run(*command: str) -> None:
    print("$", " ".join(command), flush=True)
    subprocess.run(command, cwd=_ROOT, check=True)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("version", help="the new version, for example 0.4.1")
    parser.add_argument("title", help="short title for the changelog heading")
    args = parser.parse_args(argv)
    try:
        changed = prepare(_ROOT, args.version, args.title)
    except ReleaseError as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
    for path in changed:
        print(f"updated {path}")
    # The lock records the project version; the SBOM and the notices
    # are derived from the lock.
    _run("uv", "lock")
    _run(sys.executable, "scripts/gen_sbom.py")
    _run(sys.executable, "scripts/sync_notices.py")
    print(
        f"""
Release {args.version} is prepared. Next:

  uv run ruff check . && uv run ruff format --check .
  uv run pytest -q && uv run mypy src tests
  git checkout -b release/{args.version}
  git commit -am "Release {args.version}"
  # open a pull request, merge it when CI is green, then on main:
  git tag v{args.version} && git push origin v{args.version}
  # and approve the `pypi` environment in the Release workflow run.
"""
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
