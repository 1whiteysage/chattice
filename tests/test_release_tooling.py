"""Release and dependency bookkeeping scripts (no network, no subprocess)."""

from __future__ import annotations

import re
import shutil
from pathlib import Path

import pytest

from scripts import prepare_release, sync_notices

_ROOT = Path(__file__).parents[1]


def _copy_release_files(target: Path) -> Path:
    for path, _ in prepare_release.VERSION_SITES:
        destination = target / path
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(_ROOT / path, destination)
    (target / "CHANGELOG.md").write_text(
        "# Changelog\n\n## [Unreleased]\n\n### Fixed\n\n- A thing.\n\n"
        "## [0.0.1] — First\n\n- Initial.\n"
    )
    return target


def test_every_version_site_exists_exactly_once_in_the_repository() -> None:
    # If a documentation line is reworded, the release script must be
    # updated with it — this fails first.
    version = prepare_release.current_version(_ROOT)
    for path, pattern in prepare_release.VERSION_SITES:
        matches = re.findall(pattern, (_ROOT / path).read_text())
        assert len(matches) == 1, path
        assert matches[0][1] == version, path


def test_prepare_bumps_every_site_and_releases_the_changelog(tmp_path: Path) -> None:
    root = _copy_release_files(tmp_path)

    changed = prepare_release.prepare(root, "99.0.0", "Next")

    assert prepare_release.current_version(root) == "99.0.0"
    assert set(changed) == {path for path, _ in prepare_release.VERSION_SITES} | {
        "CHANGELOG.md"
    }
    for path, _ in prepare_release.VERSION_SITES:
        assert "99.0.0" in (root / path).read_text(), path
    changelog = (root / "CHANGELOG.md").read_text()
    assert "## [99.0.0] — Next" in changelog
    assert "[Unreleased]" not in changelog
    assert "## [0.0.1] — First" in changelog


@pytest.mark.parametrize(
    ("version", "title", "message"),
    [
        ("0.0.1", "Old", "not newer"),
        ("1.2", "Short", "look like"),
        ("99.0.0", " ", "title"),
    ],
)
def test_prepare_rejects_bad_input_without_touching_files(
    tmp_path: Path, version: str, title: str, message: str
) -> None:
    root = _copy_release_files(tmp_path)
    before = {
        path: (root / path).read_text() for path, _ in prepare_release.VERSION_SITES
    }

    with pytest.raises(prepare_release.ReleaseError, match=message):
        prepare_release.prepare(root, version, title)

    for path, text in before.items():
        assert (root / path).read_text() == text


@pytest.mark.parametrize(
    "changelog",
    [
        "# Changelog\n\n## [0.0.1] — First\n",
        "# Changelog\n\n## [Unreleased]\n\n## [0.0.1] — First\n",
    ],
)
def test_prepare_needs_a_non_empty_unreleased_section(
    tmp_path: Path, changelog: str
) -> None:
    root = _copy_release_files(tmp_path)
    (root / "CHANGELOG.md").write_text(changelog)
    version = prepare_release.current_version(root)

    with pytest.raises(prepare_release.ReleaseError, match="Unreleased"):
        prepare_release.prepare(root, "99.0.0", "Next")

    # Nothing was bumped: the changelog is validated first.
    assert prepare_release.current_version(root) == version


_NOTICES = """# Notices

| Package | Version | License |
| --- | --- | --- |
| [Some_Pkg](https://example.com/a) | 1.0.0 | MIT |
| [tool[extra]](https://example.com/b) | 2.0.0 | ISC |
| [backend](https://example.com/c) | >=1.27 (build backend) | MIT |
"""
_LOCK = """
[[package]]
name = "some-pkg"
version = "1.2.0"

[[package]]
name = "tool"
version = "2.0.0"
"""


def test_notices_take_versions_from_the_lock() -> None:
    updated, problems = sync_notices.sync(_NOTICES, sync_notices.locked_versions(_LOCK))

    assert problems == []
    assert "| [Some_Pkg](https://example.com/a) | 1.2.0 | MIT |" in updated
    assert "| [tool[extra]](https://example.com/b) | 2.0.0 | ISC |" in updated
    # A range, not a locked version, stays as written.
    assert "| >=1.27 (build backend) |" in updated


def test_notices_report_a_listed_package_missing_from_the_lock() -> None:
    _, problems = sync_notices.sync(_NOTICES, {"tool": "2.0.0"})
    assert problems == ["Some_Pkg is listed but not in uv.lock"]


def test_notices_check_mode_fails_without_rewriting(tmp_path: Path) -> None:
    notices = tmp_path / "NOTICES.md"
    lock = tmp_path / "uv.lock"
    notices.write_text(_NOTICES)
    lock.write_text(_LOCK)
    arguments = ["--notices", str(notices), "--lock", str(lock)]

    assert sync_notices.main(["--check", *arguments]) == 1
    assert notices.read_text() == _NOTICES
    assert sync_notices.main(arguments) == 0
    assert sync_notices.main(["--check", *arguments]) == 0


def test_committed_notices_match_the_lockfile() -> None:
    assert sync_notices.main(["--check"]) == 0
