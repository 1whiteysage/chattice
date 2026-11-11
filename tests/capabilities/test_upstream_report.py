"""Tests for the upstream report (synthetic documents, no network)."""

import hashlib
import json
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

import pytest

from scripts.upstream_report import (
    ALLOWLIST_PATH,
    BASELINE_PATH,
    DISCOVERY_URL,
    PYPI_URL,
    RELEASE_FEED_URL,
    SDK_PACKAGES,
    SNAPSHOT_PATH,
    Snapshot,
    UpstreamInputError,
    UpstreamReport,
    build_baseline,
    build_report,
    build_snapshot,
    canonical_sha256,
    clip_report,
    compare_sdk_versions,
    diff_discovery,
    diff_feed,
    html_to_text,
    main,
    parse_allowlist,
    parse_feed,
    parse_snapshot,
    render_markdown,
    snapshot_discovery,
    snapshot_feed,
    structure_sha256,
    summarize,
    triage_methods,
)
from scripts.verify_registry import registry_facts

AUTH = "https://www.googleapis.com/auth/"
BOT = f"{AUTH}chat.bot"
READ = f"{AUTH}chat.messages.readonly"
IMPORT = f"{AUTH}chat.import"

REGISTRY_METHODS = frozenset({"spaces.list", "spaces.messages.create"})
ALLOWLIST = {"spaces.messages.get": "Reads stay on bot.raw."}
VERSIONS = {
    "google-apps-card": "0.7.1",
    "google-apps-chat": "0.10.9",
    "google-auth": "2.62.2",
    "google-cloud-pubsub": "2.43.0",
}


def discovery() -> dict[str, Any]:
    return {
        "revision": "20260101",
        "auth": {
            "oauth2": {
                "scopes": {
                    BOT: {"description": "Act as the app."},
                    READ: {"description": "Read messages."},
                }
            }
        },
        "schemas": {
            "Message": {
                "id": "Message",
                "description": "A message.",
                "properties": {
                    "text": {"type": "string", "description": "Body."},
                    "cards": {"type": "array", "deprecated": True},
                    "description": {"type": "string"},
                },
            },
            "Space": {
                "id": "Space",
                "properties": {
                    "spaceType": {
                        "type": "string",
                        "enum": ["SPACE", "DIRECT_MESSAGE"],
                        "enumDescriptions": ["A space.", "A DM."],
                    },
                },
            },
        },
        "resources": {
            "spaces": {
                "methods": {"list": {"scopes": [BOT]}},
                "resources": {
                    "messages": {
                        "methods": {
                            "create": {
                                "scopes": [BOT],
                                "parameters": {
                                    "threadKey": {"type": "string", "deprecated": True}
                                },
                            },
                            "get": {"scopes": [READ, BOT]},
                        }
                    }
                },
            }
        },
    }


def changed_discovery() -> dict[str, Any]:
    """The base document after one change of every tracked kind."""
    document = discovery()
    document["revision"] = "20260202"
    document["auth"]["oauth2"]["scopes"][IMPORT] = {"description": "Import."}
    messages = document["resources"]["spaces"]["resources"]["messages"]["methods"]
    messages["patch"] = {"scopes": [BOT]}
    messages["create"]["scopes"] = [BOT, IMPORT]
    del document["resources"]["spaces"]["methods"]["list"]
    properties = document["schemas"]["Message"]["properties"]
    properties["elements"] = {"type": "array"}
    del properties["text"]
    document["schemas"]["Space"]["properties"]["spaceType"]["enum"].append("GROUP_CHAT")
    document["schemas"]["Space"]["properties"]["spaceType"]["deprecated"] = True
    document["schemas"]["Poll"] = {"properties": {"question": {"type": "string"}}}
    return document


def entry(day: str, body: str) -> str:
    return (
        "<entry>"
        f"<title>January {day}, 2026</title>"
        f"<id>tag:example,2016:notes#January_{day}_2026</id>"
        f"<updated>2026-01-{day}T00:00:00-08:00</updated>"
        f'<link rel="alternate" href="https://example.com/notes#January_{day}_2026"/>'
        f'<content type="html"><![CDATA[{body}]]></content>'
        "</entry>"
    )


def feed(*entries: str) -> bytes:
    return (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<feed xmlns="http://www.w3.org/2005/Atom"><title>Notes</title>'
        f"{''.join(entries)}</feed>"
    ).encode()


OLD_ENTRY = entry("05", "<h3>Feature</h3><p>Spaces can be <b>listed</b>.</p>")
NEW_ENTRY = entry(
    "20",
    "<h3>Announcement</h3>\n<p>Use <code>@mention</code> &amp; see #42 "
    "<a href='https://example.com'>the *guide*</a>.</p><script>x()</script>",
)
FEED = feed(OLD_ENTRY)


def baseline_for(document: Mapping[str, Any], feed_raw: bytes) -> dict[str, Any]:
    return build_baseline(
        {}, discovery=document, feed_raw=feed_raw, sdk_versions=VERSIONS
    )


def report(
    *,
    document: Mapping[str, Any] | None = None,
    feed_raw: bytes = FEED,
    snapshot: Snapshot | None = None,
    allowlist: Mapping[str, str] = ALLOWLIST,
    registry_methods: frozenset[str] = REGISTRY_METHODS,
    sdk_versions: Mapping[str, str] = VERSIONS,
) -> UpstreamReport:
    """Report on ``document`` against the reviewed base document and feed."""
    return build_report(
        discovery=discovery() if document is None else document,
        feed_raw=feed_raw,
        baseline=baseline_for(discovery(), FEED),
        snapshot=build_snapshot(discovery(), FEED) if snapshot is None else snapshot,
        allowlist=allowlist,
        registry_methods=registry_methods,
        sdk_versions=sdk_versions,
    )


def fake_fetch(
    document: Mapping[str, Any],
    feed_raw: bytes,
    versions: Mapping[str, str],
) -> Callable[[str], bytes]:
    responses = {
        DISCOVERY_URL: json.dumps(document).encode(),
        RELEASE_FEED_URL: feed_raw,
        **{
            PYPI_URL.format(package=package): json.dumps(
                {"info": {"version": version}}
            ).encode()
            for package, version in versions.items()
        },
    }
    return lambda url: responses[url]


def reviewed_files(tmp_path: Path) -> list[str]:
    """Write reviewed state for the base document and return its CLI flags."""
    paths = {
        name: tmp_path / f"{name}.json" for name in ("baseline", "snapshot", "allow")
    }
    paths["baseline"].write_text(json.dumps(baseline_for(discovery(), FEED)))
    paths["snapshot"].write_text(json.dumps(build_snapshot(discovery(), FEED)))
    paths["allow"].write_text(json.dumps(ALLOWLIST))
    return [
        "--baseline",
        str(paths["baseline"]),
        "--snapshot",
        str(paths["snapshot"]),
        "--allowlist",
        str(paths["allow"]),
    ]


# --- hashes ---------------------------------------------------------------


def test_canonical_sha256_matches_the_baseline_definition() -> None:
    document = {"b": "é", "a": [1, 2]}
    expected = hashlib.sha256('{"a":[1,2],"b":"é"}'.encode()).hexdigest()
    assert canonical_sha256(document) == expected


def test_structure_hash_ignores_revision_and_prose() -> None:
    republished = discovery()
    republished["revision"] = "20260102"
    republished["schemas"]["Message"]["description"] = "Reworded."
    republished["schemas"]["Space"]["properties"]["spaceType"]["enumDescriptions"] = []
    assert canonical_sha256(republished) != canonical_sha256(discovery())
    assert structure_sha256(republished) == structure_sha256(discovery())


def test_structure_hash_keeps_a_property_named_description() -> None:
    document = discovery()
    del document["schemas"]["Message"]["properties"]["description"]
    assert structure_sha256(document) != structure_sha256(discovery())


# --- discovery snapshot and diff -------------------------------------------


def test_snapshot_discovery_extracts_the_tracked_surface() -> None:
    snapshot = snapshot_discovery(discovery())
    assert snapshot["revision"] == "20260101"
    assert snapshot["scopes"] == [BOT, READ]
    assert snapshot["methods"] == {
        "spaces.list": [BOT],
        "spaces.messages.create": [BOT],
        "spaces.messages.get": [BOT, READ],
    }
    assert snapshot["schemas"] == {
        "Message": {"cards": [], "description": [], "text": []},
        "Space": {"spaceType": ["DIRECT_MESSAGE", "SPACE"]},
    }
    assert snapshot["deprecated"] == [
        "Message.cards",
        "spaces.messages.create(threadKey)",
    ]


def test_diff_discovery_names_every_tracked_change() -> None:
    diff = diff_discovery(
        snapshot_discovery(discovery()), snapshot_discovery(changed_discovery())
    )
    assert (diff.revision_reviewed, diff.revision_current) == ("20260101", "20260202")
    assert diff.methods.added == ("spaces.messages.patch",)
    assert diff.methods.removed == ("spaces.list",)
    assert diff.scopes.added == (IMPORT,)
    assert set(diff.method_scopes) == {"spaces.messages.create"}
    assert diff.method_scopes["spaces.messages.create"].added == (IMPORT,)
    assert diff.schemas.added == ("Poll",)
    assert diff.fields["Message"].added == ("elements",)
    assert diff.fields["Message"].removed == ("text",)
    assert diff.enum_values["Space.spaceType"].added == ("GROUP_CHAT",)
    assert diff.deprecated.added == ("Space.spaceType",)
    assert diff.tracked_changes == 9
    assert diff.needs_review
    assert not diff.untracked


def test_republished_document_needs_no_review() -> None:
    republished = discovery()
    republished["revision"] = "20260102"
    republished["schemas"]["Message"]["description"] = "Reworded."
    result = report(document=republished)
    assert not result.discovery.needs_review
    assert not result.needs_review
    assert result.hashes[0].reviewed != result.hashes[0].current
    assert "Revision: `20260101` → `20260102`" in render_markdown(result)


def test_change_outside_the_tracked_surface_is_flagged() -> None:
    document = discovery()
    document["schemas"]["Message"]["properties"]["text"]["type"] = "integer"
    result = report(document=document)
    assert result.discovery.untracked
    assert result.discovery.tracked_changes == 0
    assert result.findings == ("untracked discovery change",)
    assert "changed outside the tracked surface" in render_markdown(result)


# --- registry coverage and allowlist ---------------------------------------


def test_triage_lists_methods_that_are_neither_registered_nor_allowlisted() -> None:
    triage = triage_methods(
        ["spaces.list", "spaces.messages.get", "spaces.setup", "media.upload"],
        {"spaces.list"},
        ALLOWLIST,
    )
    assert triage.untriaged == ("media.upload", "spaces.setup")
    assert (triage.total, triage.registered) == (4, 1)
    assert triage.needs_review


def test_triage_flags_stale_allowlist_entries() -> None:
    triage = triage_methods(
        ["spaces.list"],
        {"spaces.list"},
        {"spaces.gone": "Removed upstream.", "spaces.list": "Wrapped later."},
    )
    assert triage.untriaged == ()
    assert triage.allowlisted_missing == ("spaces.gone",)
    assert triage.allowlisted_registered == ("spaces.list",)
    assert triage.needs_review


def test_allowlist_requires_a_reason_for_every_method() -> None:
    assert parse_allowlist(ALLOWLIST) == ALLOWLIST
    with pytest.raises(UpstreamInputError, match=r"spaces\.list"):
        parse_allowlist({"spaces.list": " "})
    with pytest.raises(UpstreamInputError):
        parse_allowlist(["spaces.list"])


# --- release feed ------------------------------------------------------------


def test_html_to_text_strips_markup() -> None:
    markup = (
        "<h3>Feature</h3>\n<p>Use <code>a.b</code> &amp; <b>c</b>.</p>"
        "<ul><li>x</li></ul>"
    )
    assert html_to_text(markup) == "Feature: Use a.b & c. x"


def test_summarize_cuts_on_a_word_boundary() -> None:
    assert summarize("short", 10) == "short"
    assert summarize("alpha beta gamma delta", 14) == "alpha beta…"


def test_parse_feed_orders_entries_newest_first() -> None:
    entries = parse_feed(feed(OLD_ENTRY, NEW_ENTRY))
    assert [item.title for item in entries] == ["January 20, 2026", "January 05, 2026"]
    assert entries[1].summary == "Feature: Spaces can be listed."
    assert entries[1].updated == "2026-01-05T00:00:00-08:00"
    assert entries[1].link == "https://example.com/notes#January_05_2026"
    assert "x()" not in entries[0].summary


def test_parse_feed_rejects_dtd_and_broken_xml() -> None:
    with pytest.raises(UpstreamInputError, match="DTD"):
        parse_feed(b'<!DOCTYPE feed [<!ENTITY a "b">]><feed/>')
    with pytest.raises(UpstreamInputError, match="not valid XML"):
        parse_feed(b"<feed>")


def test_diff_feed_lists_new_and_edited_entries() -> None:
    reviewed = snapshot_feed(parse_feed(FEED))
    assert reviewed["latest_updated"] == "2026-01-05T00:00:00-08:00"
    edited = entry("05", "<h3>Feature</h3><p>Spaces can be searched.</p>")
    diff = diff_feed(reviewed, parse_feed(feed(NEW_ENTRY, edited)))
    assert [item.title for item in diff.new] == ["January 20, 2026"]
    assert [item.summary for item in diff.edited] == [
        "Feature: Spaces can be searched."
    ]
    assert diff.needs_review


def test_entry_that_left_the_feed_window_is_not_a_finding() -> None:
    reviewed = snapshot_feed(parse_feed(feed(OLD_ENTRY, NEW_ENTRY)))
    assert not diff_feed(reviewed, parse_feed(feed(NEW_ENTRY))).needs_review


# --- SDK versions ------------------------------------------------------------


def test_sdk_version_drift_is_reported_per_package() -> None:
    latest = {**VERSIONS, "google-auth": "2.63.0"}
    statuses = compare_sdk_versions({"google_auth": "2.62.2"}, latest)
    assert [status.package for status in statuses] == sorted(SDK_PACKAGES)
    changed = {status.package: status for status in statuses if status.changed}
    assert changed["google-auth"].reviewed == "2.62.2"
    assert changed["google-auth"].current == "2.63.0"
    assert changed["google-apps-chat"].reviewed == "missing"


# --- Markdown ----------------------------------------------------------------


def test_clean_report_says_nothing_to_review() -> None:
    result = report()
    markdown = render_markdown(result)
    assert not result.needs_review
    assert markdown.startswith("**Nothing to review.**")
    assert "2 of 3 discovery methods are registered; 1 is on the" in markdown
    assert "No method needs triage." in markdown
    assert "- `spaces.messages.get` — Reads stay on bot.raw." in markdown
    assert "No change in methods, scopes, schema fields, or enum values." in markdown
    assert "No new or edited entry." in markdown
    assert "**changed**" not in markdown


def test_report_renders_every_section() -> None:
    result = report(
        document=changed_discovery(),
        feed_raw=feed(NEW_ENTRY, OLD_ENTRY),
        allowlist={**ALLOWLIST, "spaces.gone": "Removed upstream."},
        sdk_versions={**VERSIONS, "google-apps-chat": "0.11.0"},
    )
    markdown = render_markdown(result)
    assert result.needs_review
    assert markdown.startswith(
        "**Review needed:** 1 unwrapped method needs triage; "
        "1 stale allowlist entry; 9 discovery changes; 1 new release note; "
        "1 SDK release.\n"
    )
    for line in (
        "- `spaces.messages.patch` — scopes: `chat.bot`",
        "- `spaces.gone` — no longer in the discovery document",
        "Revision: `20260101` → `20260202`",
        "- `spaces.messages.patch` — scopes: `chat.bot` — needs triage",
        "**Methods removed**\n\n- `spaces.list`",
        "**OAuth scopes**\n\n- added `chat.import`",
        "- `spaces.messages.create`: added `chat.import`",
        "- `Poll` — fields: `question`",
        "- `Message`: added `elements`; removed `text`",
        "- `Space.spaceType`: added `GROUP_CHAT`",
        "**Deprecation flags**\n\n- added `Space.spaceType`",
        "Reviewed through 2026-01-05.",
        "- 2026-01-20 — [January 20, 2026]"
        "(https://example.com/notes#January_20_2026): Announcement: ",
        "| `google-apps-chat` | `0.10.9` | `0.11.0` | **changed** |",
        "| `google-auth` | `2.62.2` | `2.62.2` |  |",
        "--update-baseline",
    ):
        assert line in markdown, line


def test_fetched_prose_cannot_mention_users_or_inject_markdown() -> None:
    markdown = render_markdown(report(feed_raw=feed(NEW_ENTRY, OLD_ENTRY)))
    assert "Use @​mention & see #​42 the \\*guide\\*." in markdown
    assert "@mention" not in markdown
    hostile = report(
        document={
            **discovery(),
            "schemas": {"Bad`name\n@x": {"properties": {}}},
        }
    )
    assert "- `Bad'name @x`" in render_markdown(hostile)


def test_report_is_deterministic_for_reordered_inputs() -> None:
    def reorder(node: Any) -> Any:
        # Object keys only: array order and feed bytes are part of the hashes.
        if isinstance(node, dict):
            return {key: reorder(node[key]) for key in reversed(list(node))}
        if isinstance(node, list):
            return [reorder(item) for item in node]
        return node

    kwargs: dict[str, Any] = {
        "allowlist": {"spaces.b": "Second.", "spaces.a": "First."},
        "sdk_versions": {**VERSIONS, "google-auth": "2.63.0"},
    }
    first = render_markdown(
        report(
            document=changed_discovery(),
            feed_raw=feed(OLD_ENTRY, NEW_ENTRY),
            **kwargs,
        )
    )
    second = render_markdown(
        report(
            document=reorder(changed_discovery()),
            feed_raw=feed(OLD_ENTRY, NEW_ENTRY),
            **{key: reorder(value) for key, value in kwargs.items()},
        )
    )
    assert first == second
    assert first.index("`spaces.a`") < first.index("`spaces.b`")


def test_clip_report_cuts_at_a_line_boundary() -> None:
    markdown = "".join(f"line {number}\n" for number in range(100))
    clipped = clip_report(markdown, 200)
    assert clip_report(markdown, 10_000) == markdown
    assert len(clipped) <= 200
    assert clipped.endswith("the rest._\n")
    assert clipped.split("\n\n")[0].splitlines()[-1].startswith("line ")


# --- snapshot file -----------------------------------------------------------


def test_snapshot_round_trips_through_json() -> None:
    snapshot = build_snapshot(discovery(), FEED)
    assert parse_snapshot(json.loads(json.dumps(snapshot))) == snapshot


def test_malformed_snapshot_is_rejected() -> None:
    broken = json.loads(json.dumps(build_snapshot(discovery(), FEED)))
    del broken["discovery"]["methods"]
    with pytest.raises(UpstreamInputError, match="--update-baseline"):
        parse_snapshot(broken)


# --- CLI ---------------------------------------------------------------------


def test_cli_exits_zero_when_nothing_changed(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    status = main(
        reviewed_files(tmp_path),
        fetch=fake_fetch(discovery(), FEED, VERSIONS),
        registry_methods=REGISTRY_METHODS,
    )
    assert status == 0
    assert capsys.readouterr().out.startswith("**Nothing to review.**")


def test_cli_writes_the_report_and_exits_one_when_review_is_needed(
    tmp_path: Path,
) -> None:
    output = tmp_path / "out" / "report.md"
    saved = tmp_path / "out" / "discovery.json"
    status = main(
        [
            *reviewed_files(tmp_path),
            "--output",
            str(output),
            "--save-discovery",
            str(saved),
            "--max-chars",
            "400",
        ],
        fetch=fake_fetch(changed_discovery(), feed(NEW_ENTRY, OLD_ENTRY), VERSIONS),
        registry_methods=REGISTRY_METHODS,
    )
    assert status == 1
    assert output.read_text().startswith("**Review needed:**")
    assert len(output.read_text()) <= 400
    assert json.loads(saved.read_text()) == changed_discovery()


def test_cli_reads_local_documents_instead_of_fetching(tmp_path: Path) -> None:
    document = tmp_path / "discovery.json"
    document.write_text(json.dumps(discovery()))
    notes = tmp_path / "feed.xml"
    notes.write_bytes(FEED)
    pypi_only = fake_fetch({}, b"", VERSIONS)
    status = main(
        [*reviewed_files(tmp_path), "--discovery", str(document), "--feed", str(notes)],
        fetch=lambda url: pypi_only(url) if "pypi.org" in url else b"unreachable",
        registry_methods=REGISTRY_METHODS,
    )
    assert status == 0


def test_cli_update_mode_rewrites_the_reviewed_state(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    flags = reviewed_files(tmp_path)
    baseline_path, snapshot_path = Path(flags[1]), Path(flags[3])
    baseline_path.write_text(
        json.dumps({**baseline_for(discovery(), FEED), "reviewed_by": "someone"})
    )
    new_feed = feed(NEW_ENTRY, OLD_ENTRY)
    new_versions = {**VERSIONS, "google-apps-chat": "0.11.0"}
    live = fake_fetch(changed_discovery(), new_feed, new_versions)
    registry = REGISTRY_METHODS | {"spaces.messages.patch"}

    assert main(flags, fetch=live, registry_methods=registry) == 1
    assert (
        main([*flags, "--update-baseline"], fetch=live, registry_methods=registry) == 0
    )
    assert "**Nothing to review.**" in capsys.readouterr().out

    baseline = json.loads(baseline_path.read_text())
    assert baseline == {
        "chat_discovery_sha256": canonical_sha256(changed_discovery()),
        "chat_release_feed_sha256": hashlib.sha256(new_feed).hexdigest(),
        "google_apps_card": "0.7.1",
        "google_apps_chat": "0.11.0",
        "google_auth": "2.62.2",
        "google_cloud_pubsub": "2.43.0",
        "reviewed_by": "someone",
    }
    assert json.loads(snapshot_path.read_text()) == build_snapshot(
        changed_discovery(), new_feed
    )
    assert json.loads(Path(flags[5]).read_text()) == ALLOWLIST
    assert main(flags, fetch=live, registry_methods=registry) == 0


def test_cli_update_mode_cannot_silence_an_unwrapped_method(tmp_path: Path) -> None:
    live = fake_fetch(changed_discovery(), FEED, VERSIONS)
    flags = [*reviewed_files(tmp_path), "--update-baseline"]
    assert main(flags, fetch=live, registry_methods=REGISTRY_METHODS) == 1


def test_cli_reports_unreadable_input_with_exit_two(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    flags = reviewed_files(tmp_path)
    Path(flags[3]).unlink()
    status = main(
        flags,
        fetch=fake_fetch(discovery(), FEED, VERSIONS),
        registry_methods=REGISTRY_METHODS,
    )
    assert status == 2
    assert "upstream_report:" in capsys.readouterr().err


# --- committed reviewed state (no network) -----------------------------------


def test_committed_baseline_keeps_the_monitored_keys() -> None:
    baseline = json.loads(BASELINE_PATH.read_text(encoding="utf-8"))
    for key in ("chat_discovery_sha256", "chat_release_feed_sha256"):
        assert len(baseline[key]) == 64
        assert int(baseline[key], 16) >= 0
    for package in SDK_PACKAGES:
        assert baseline[package.replace("-", "_")]


def test_committed_snapshot_is_fully_triaged() -> None:
    """Every reviewed discovery method is registered or allowlisted, and the
    registry only names methods of the reviewed discovery document."""
    snapshot = parse_snapshot(json.loads(SNAPSHOT_PATH.read_text(encoding="utf-8")))
    allowlist = parse_allowlist(json.loads(ALLOWLIST_PATH.read_text(encoding="utf-8")))
    methods = set(snapshot["discovery"]["methods"])
    registered = set(registry_facts())
    triage = triage_methods(methods, registered, allowlist)
    assert triage.untriaged == ()
    assert triage.allowlisted_missing == ()
    assert triage.allowlisted_registered == ()
    assert registered <= methods
    assert methods == registered | set(allowlist)
