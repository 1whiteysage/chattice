"""Keep the versions in THIRD_PARTY_NOTICES.md equal to uv.lock.

Usage: python scripts/sync_notices.py [--check]

The notices file lists the direct dependencies with their locked
versions. Names, links and licenses are written by a person; only the
version column is derived, so it is rewritten here instead of by hand.
A row whose version is not a plain locked version (for example the
build backend's ``>=1.27``) is left as written.

Standard library only: it runs before any dependency is installed.
"""

from __future__ import annotations

import argparse
import re
import sys
import tomllib
from pathlib import Path

_ROOT = Path(__file__).parents[1]
_NOTICES = _ROOT / "THIRD_PARTY_NOTICES.md"
_LOCK = _ROOT / "uv.lock"

# | [name[extra]](url) | version | ...
_ROW = re.compile(
    r"^(?P<head>\| \[(?P<name>[A-Za-z0-9._-]+)(?:\[[^\]]*\])?\]\([^)]*\) \| )"
    r"(?P<version>[^|]*?)(?P<tail> \|.*)$"
)
_PLAIN_VERSION = re.compile(r"\d+(\.\d+)*([a-z]+\d*|\.post\d+|\.dev\d+)*")


def _normalize(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def locked_versions(lock_text: str) -> dict[str, str]:
    """Return ``{normalized package name: version}`` from a uv lockfile."""
    lock = tomllib.loads(lock_text)
    return {
        _normalize(package["name"]): package["version"]
        for package in lock.get("package", [])
        if "version" in package
    }


def sync(notices: str, versions: dict[str, str]) -> tuple[str, list[str]]:
    """Return the notices text with locked versions and the problems found.

    A listed package that is not in the lockfile is a problem: the row
    describes a dependency the project no longer resolves.
    """
    problems: list[str] = []
    lines: list[str] = []
    for line in notices.splitlines():
        match = _ROW.match(line)
        if match is None or not _PLAIN_VERSION.fullmatch(match["version"].strip()):
            lines.append(line)
            continue
        locked = versions.get(_normalize(match["name"]))
        if locked is None:
            problems.append(f"{match['name']} is listed but not in uv.lock")
            lines.append(line)
            continue
        lines.append(f"{match['head']}{locked}{match['tail']}")
    return "\n".join(lines) + "\n", problems


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--check", action="store_true", help="fail instead of rewriting the file"
    )
    parser.add_argument("--notices", type=Path, default=_NOTICES)
    parser.add_argument("--lock", type=Path, default=_LOCK)
    args = parser.parse_args(argv)

    current = args.notices.read_text()
    updated, problems = sync(current, locked_versions(args.lock.read_text()))
    for problem in problems:
        print(f"error: {problem}", file=sys.stderr)
    if problems:
        return 1
    if updated == current:
        print("THIRD_PARTY_NOTICES.md matches the lockfile")
        return 0
    if args.check:
        print(
            "THIRD_PARTY_NOTICES.md is out of date; run python scripts/sync_notices.py",
            file=sys.stderr,
        )
        return 1
    args.notices.write_text(updated)
    print("THIRD_PARTY_NOTICES.md updated from the lockfile")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
