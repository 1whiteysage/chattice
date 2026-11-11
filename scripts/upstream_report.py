"""Report what changed upstream since the reviewed Google Chat baseline.

The daily upstream watch used to compare hashes only, so its issue said
"something changed" without saying what. This script names the change:

* discovery methods that are neither registered nor on the reviewed
  allowlist of intentionally unwrapped methods;
* the diff between the live discovery document and the reviewed snapshot
  (methods, OAuth scopes, schema fields, enum values, deprecation flags);
* release-feed entries that are not in the reviewed snapshot;
* SDK releases newer than the reviewed versions.

Everything above ``fetch_url`` is pure: it takes parsed documents and
returns values, so the tests run on synthetic inputs without the network.
Reviewed state lives in three files under ``.github/``:

* ``upstream-baseline.json`` — source hashes and reviewed SDK versions;
* ``upstream-snapshot.json`` — the reviewed API surface, rewritten only by
  ``--update-baseline``;
* ``upstream-allowlist.json`` — hand-edited ``{method: reason}`` map of
  methods that stay unwrapped on purpose; never rewritten by this script.

Exit status: 0 nothing to review, 1 review needed, 2 an input could not be
read. Nothing is applied automatically; a human reviews the report and then
runs ``--update-baseline``.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import urllib.request
import xml.etree.ElementTree as ET
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from html.parser import HTMLParser
from pathlib import Path
from typing import Any, TypedDict

# Standalone script: runnable from anywhere without the project on
# PYTHONPATH (CI executes it with `uv run python scripts/...`).
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts.verify_registry import collect_methods, registry_facts

ROOT = Path(__file__).resolve().parent.parent
DISCOVERY_URL = "https://chat.googleapis.com/$discovery/rest?version=v1"
RELEASE_FEED_URL = "https://developers.google.com/feeds/chat-release-notes.xml"
PYPI_URL = "https://pypi.org/pypi/{package}/json"
SDK_PACKAGES = (
    "google-apps-card",
    "google-apps-chat",
    "google-auth",
    "google-cloud-pubsub",
)

BASELINE_PATH = ROOT / ".github" / "upstream-baseline.json"
SNAPSHOT_PATH = ROOT / ".github" / "upstream-snapshot.json"
ALLOWLIST_PATH = ROOT / ".github" / "upstream-allowlist.json"

SCOPE_PREFIX = "https://www.googleapis.com/auth/"
SUMMARY_LIMIT = 280
ATOM = "{http://www.w3.org/2005/Atom}"
CLIP_NOTICE = "\n\n_Report truncated; run `scripts/upstream_report.py` for the rest._\n"


class UpstreamInputError(ValueError):
    """A monitored input or a reviewed file could not be interpreted."""


class DiscoverySnapshot(TypedDict):
    """Reviewed API surface extracted from one discovery document."""

    revision: str
    structure_sha256: str
    scopes: list[str]
    methods: dict[str, list[str]]
    schemas: dict[str, dict[str, list[str]]]
    deprecated: list[str]


class FeedSnapshot(TypedDict):
    """Reviewed release-feed entries as ``{entry id: content digest}``."""

    latest_updated: str
    entries: dict[str, str]


class Snapshot(TypedDict):
    """Content of ``.github/upstream-snapshot.json``."""

    discovery: DiscoverySnapshot
    release_feed: FeedSnapshot


@dataclass(frozen=True)
class Delta:
    """Names added to and removed from one sorted set."""

    added: tuple[str, ...] = ()
    removed: tuple[str, ...] = ()

    def __bool__(self) -> bool:
        return bool(self.added or self.removed)


@dataclass(frozen=True)
class MethodTriage:
    """Coverage of the discovery methods by the registry and the allowlist."""

    total: int
    registered: int
    untriaged: tuple[str, ...]
    allowlisted_missing: tuple[str, ...]
    allowlisted_registered: tuple[str, ...]

    @property
    def needs_review(self) -> bool:
        return bool(
            self.untriaged or self.allowlisted_missing or self.allowlisted_registered
        )


@dataclass(frozen=True)
class DiscoveryDiff:
    """Difference between the reviewed and the live discovery surface.

    ``method_scopes`` and ``fields`` cover names present on both sides;
    ``enum_values`` is keyed by ``Schema.field``. ``untracked`` is set when
    the document changed structurally in a place the snapshot does not name
    (parameters, types, formats), so no such change passes silently.
    """

    revision_reviewed: str
    revision_current: str
    methods: Delta
    scopes: Delta
    method_scopes: Mapping[str, Delta]
    schemas: Delta
    fields: Mapping[str, Delta]
    enum_values: Mapping[str, Delta]
    deprecated: Delta
    untracked: bool

    @property
    def tracked_changes(self) -> int:
        """Count the named entries across every tracked section."""
        groups = [
            self.methods,
            self.scopes,
            self.schemas,
            self.deprecated,
            *self.method_scopes.values(),
            *self.fields.values(),
            *self.enum_values.values(),
        ]
        return sum(len(delta.added) + len(delta.removed) for delta in groups)

    @property
    def needs_review(self) -> bool:
        return bool(self.tracked_changes or self.untracked)


@dataclass(frozen=True)
class FeedEntry:
    """One release-feed entry reduced to what the report prints."""

    id: str
    title: str
    updated: str
    link: str
    summary: str
    digest: str


@dataclass(frozen=True)
class FeedDiff:
    """Feed entries that are unreviewed or changed after review."""

    reviewed_through: str
    new: tuple[FeedEntry, ...]
    edited: tuple[FeedEntry, ...]

    @property
    def needs_review(self) -> bool:
        return bool(self.new or self.edited)


@dataclass(frozen=True)
class VersionStatus:
    """Reviewed and latest published version of one SDK package."""

    package: str
    reviewed: str
    current: str

    @property
    def changed(self) -> bool:
        return self.reviewed != self.current


@dataclass(frozen=True)
class HashStatus:
    """Reviewed and current hash of one monitored source (informational)."""

    key: str
    reviewed: str
    current: str


@dataclass(frozen=True)
class UpstreamReport:
    """Everything the Markdown report is rendered from."""

    triage: MethodTriage
    allowlist: Mapping[str, str]
    discovery: DiscoveryDiff
    current: DiscoverySnapshot
    feed: FeedDiff
    sdk: tuple[VersionStatus, ...]
    hashes: tuple[HashStatus, ...]

    @property
    def findings(self) -> tuple[str, ...]:
        """One short phrase per kind of finding, in section order."""
        triage, found = self.triage, []
        if triage.untriaged:
            found.append(
                _count(
                    len(triage.untriaged),
                    "unwrapped method needs triage",
                    "unwrapped methods need triage",
                )
            )
        stale = len(triage.allowlisted_missing) + len(triage.allowlisted_registered)
        if stale:
            found.append(
                _count(stale, "stale allowlist entry", "stale allowlist entries")
            )
        if self.discovery.tracked_changes:
            found.append(
                _count(
                    self.discovery.tracked_changes,
                    "discovery change",
                    "discovery changes",
                )
            )
        if self.discovery.untracked:
            found.append("untracked discovery change")
        if self.feed.new:
            found.append(
                _count(len(self.feed.new), "new release note", "new release notes")
            )
        if self.feed.edited:
            found.append(
                _count(
                    len(self.feed.edited),
                    "edited release note",
                    "edited release notes",
                )
            )
        drift = sum(1 for status in self.sdk if status.changed)
        if drift:
            found.append(_count(drift, "SDK release", "SDK releases"))
        return tuple(found)

    @property
    def needs_review(self) -> bool:
        return bool(self.findings)


def canonical_sha256(document: Any) -> str:
    """Hash canonical JSON — the definition of ``chat_discovery_sha256``."""
    canonical = json.dumps(
        document,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode()
    return hashlib.sha256(canonical).hexdigest()


def _strip_prose(node: Any) -> Any:
    # Only string/list values are prose; a schema *property* that happens to
    # be named "description" has a mapping value and must be kept.
    if isinstance(node, Mapping):
        return {
            key: _strip_prose(value)
            for key, value in node.items()
            if not (key == "description" and isinstance(value, str))
            and not (key == "enumDescriptions" and isinstance(value, list))
        }
    if isinstance(node, list):
        return [_strip_prose(item) for item in node]
    return node


def structure_sha256(document: Mapping[str, Any]) -> str:
    """Hash the document without prose and without its ``revision`` stamp.

    The full-document hash moves whenever Google republishes the document,
    even when only ``revision`` differs. This digest moves only when the
    machine-readable surface does.
    """
    stripped = _strip_prose(
        {key: value for key, value in document.items() if key != "revision"}
    )
    return canonical_sha256(stripped)


def _enum_values(spec: Mapping[str, Any]) -> list[str]:
    values = spec.get("enum") or (spec.get("items") or {}).get("enum") or []
    return sorted(str(value) for value in values)


def snapshot_discovery(document: Mapping[str, Any]) -> DiscoverySnapshot:
    """Reduce a discovery document to the surface the report diffs.

    Methods map to their OAuth scopes; schemas map each property to its
    enum values (empty for non-enum properties). ``deprecated`` lists
    ``method``, ``method(parameter)``, ``Schema``, ``Schema.field`` and
    ``Schema.field=VALUE`` labels flagged by the document.
    """
    deprecated: set[str] = set()
    methods: dict[str, list[str]] = {}
    for method_id, method in sorted(collect_methods(document).items()):
        methods[method_id] = sorted(method.get("scopes") or [])
        if method.get("deprecated"):
            deprecated.add(method_id)
        for name, parameter in (method.get("parameters") or {}).items():
            if parameter.get("deprecated"):
                deprecated.add(f"{method_id}({name})")

    schemas: dict[str, dict[str, list[str]]] = {}
    for schema_name, schema in sorted((document.get("schemas") or {}).items()):
        if schema.get("deprecated"):
            deprecated.add(schema_name)
        fields: dict[str, list[str]] = {}
        for name, spec in sorted((schema.get("properties") or {}).items()):
            fields[name] = _enum_values(spec)
            if spec.get("deprecated"):
                deprecated.add(f"{schema_name}.{name}")
            flags = spec.get("enumDeprecated") or []
            for value, flagged in zip(spec.get("enum") or [], flags, strict=False):
                if flagged:
                    deprecated.add(f"{schema_name}.{name}={value}")
        schemas[schema_name] = fields

    oauth = (document.get("auth") or {}).get("oauth2") or {}
    return {
        "revision": str(document.get("revision", "")),
        "structure_sha256": structure_sha256(document),
        "scopes": sorted(oauth.get("scopes") or {}),
        "methods": methods,
        "schemas": schemas,
        "deprecated": sorted(deprecated),
    }


def _delta(reviewed: Iterable[str], current: Iterable[str]) -> Delta:
    old, new = set(reviewed), set(current)
    return Delta(added=tuple(sorted(new - old)), removed=tuple(sorted(old - new)))


def _changed(pairs: Iterable[tuple[str, Delta]]) -> dict[str, Delta]:
    return {name: delta for name, delta in sorted(pairs) if delta}


def diff_discovery(
    reviewed: DiscoverySnapshot, current: DiscoverySnapshot
) -> DiscoveryDiff:
    """Name every difference between two discovery snapshots."""
    old_methods, new_methods = reviewed["methods"], current["methods"]
    old_schemas, new_schemas = reviewed["schemas"], current["schemas"]
    shared_schemas = sorted(set(old_schemas) & set(new_schemas))
    diff = DiscoveryDiff(
        revision_reviewed=reviewed["revision"],
        revision_current=current["revision"],
        methods=_delta(old_methods, new_methods),
        scopes=_delta(reviewed["scopes"], current["scopes"]),
        method_scopes=_changed(
            (name, _delta(old_methods[name], new_methods[name]))
            for name in set(old_methods) & set(new_methods)
        ),
        schemas=_delta(old_schemas, new_schemas),
        fields=_changed(
            (name, _delta(old_schemas[name], new_schemas[name]))
            for name in shared_schemas
        ),
        enum_values=_changed(
            (
                f"{name}.{field}",
                _delta(old_schemas[name][field], new_schemas[name][field]),
            )
            for name in shared_schemas
            for field in set(old_schemas[name]) & set(new_schemas[name])
        ),
        deprecated=_delta(reviewed["deprecated"], current["deprecated"]),
        untracked=False,
    )
    untracked = (
        not diff.tracked_changes
        and reviewed["structure_sha256"] != current["structure_sha256"]
    )
    return replace(diff, untracked=untracked)


def triage_methods(
    discovery_methods: Iterable[str],
    registry_methods: Iterable[str],
    allowlist: Mapping[str, str],
) -> MethodTriage:
    """Split the discovery methods into registered, allowlisted and neither.

    An allowlist entry is stale when its method left the discovery document
    or when the method is registered after all.
    """
    discovered, registered = set(discovery_methods), set(registry_methods)
    return MethodTriage(
        total=len(discovered),
        registered=len(discovered & registered),
        untriaged=tuple(sorted(discovered - registered - set(allowlist))),
        allowlisted_missing=tuple(sorted(set(allowlist) - discovered)),
        allowlisted_registered=tuple(sorted(set(allowlist) & registered)),
    )


class _TextExtractor(HTMLParser):
    _BLOCKS = frozenset(
        {"blockquote", "br", "div", "li", "ol", "p", "pre", "table", "tr", "ul"}
    )
    _HEADINGS = frozenset({"h1", "h2", "h3", "h4", "h5", "h6"})
    _HIDDEN = frozenset({"script", "style"})

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self._hidden = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in self._HIDDEN:
            self._hidden += 1
        elif tag in self._BLOCKS or tag in self._HEADINGS:
            self.parts.append(" ")

    def handle_endtag(self, tag: str) -> None:
        if tag in self._HIDDEN:
            self._hidden = max(0, self._hidden - 1)
        elif tag in self._HEADINGS:
            heading = "".join(self.parts).rstrip()
            self.parts = [heading, ": " if heading[-1:].isalnum() else " "]
        elif tag in self._BLOCKS:
            self.parts.append(" ")

    def handle_data(self, data: str) -> None:
        if not self._hidden:
            self.parts.append(data)


def html_to_text(markup: str) -> str:
    """Strip HTML to one line of plain text; headings end with a colon."""
    extractor = _TextExtractor()
    extractor.feed(markup)
    extractor.close()
    return " ".join("".join(extractor.parts).split())


def summarize(text: str, limit: int = SUMMARY_LIMIT) -> str:
    """Cut ``text`` to at most ``limit`` characters on a word boundary."""
    if len(text) <= limit:
        return text
    head = text[: limit - 1]
    if " " in head:
        head = head.rsplit(" ", 1)[0]
    return head.rstrip(" ,;:.") + "…"


def _timestamp(updated: str) -> float:
    try:
        moment = datetime.fromisoformat(updated)
    except ValueError:
        return 0.0
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=UTC)
    return moment.timestamp()


def parse_feed(raw: bytes, *, summary_limit: int = SUMMARY_LIMIT) -> list[FeedEntry]:
    """Parse the Atom release feed into entries, newest first."""
    # The stdlib parser expands internal entities; an Atom feed needs no
    # DTD, so a document that declares one is rejected instead of parsed.
    if b"<!DOCTYPE" in raw or b"<!ENTITY" in raw:
        raise UpstreamInputError("release feed declares a DTD; refusing to parse")
    try:
        root = ET.fromstring(raw)
    except ET.ParseError as error:
        raise UpstreamInputError(f"release feed is not valid XML: {error}") from error
    entries = []
    for node in root.iter(f"{ATOM}entry"):
        title = (node.findtext(f"{ATOM}title") or "").strip()
        content = node.findtext(f"{ATOM}content") or ""
        link = next(
            (
                item.get("href", "")
                for item in node.iter(f"{ATOM}link")
                if item.get("rel", "alternate") == "alternate"
            ),
            "",
        )
        entries.append(
            FeedEntry(
                id=(node.findtext(f"{ATOM}id") or title).strip(),
                title=title,
                updated=(node.findtext(f"{ATOM}updated") or "").strip(),
                link=link,
                summary=summarize(html_to_text(content), summary_limit),
                digest=hashlib.sha256(f"{title}\n{content}".encode()).hexdigest(),
            )
        )
    return sorted(entries, key=lambda entry: (-_timestamp(entry.updated), entry.id))


def snapshot_feed(entries: Sequence[FeedEntry]) -> FeedSnapshot:
    """Record the reviewed entries; ``entries`` is newest first."""
    return {
        "latest_updated": entries[0].updated if entries else "",
        "entries": {entry.id: entry.digest for entry in entries},
    }


def diff_feed(reviewed: FeedSnapshot, entries: Sequence[FeedEntry]) -> FeedDiff:
    """Return entries missing from the reviewed snapshot or edited since.

    Entries that merely scrolled out of the feed window are not a finding.
    """
    known = reviewed["entries"]
    return FeedDiff(
        reviewed_through=reviewed["latest_updated"],
        new=tuple(entry for entry in entries if entry.id not in known),
        edited=tuple(
            entry
            for entry in entries
            if entry.id in known and known[entry.id] != entry.digest
        ),
    )


def baseline_key(package: str) -> str:
    """Map a PyPI package name to its ``upstream-baseline.json`` key."""
    return package.replace("-", "_")


def compare_sdk_versions(
    baseline: Mapping[str, Any], latest: Mapping[str, str]
) -> tuple[VersionStatus, ...]:
    """Pair every monitored package's reviewed version with the latest."""
    return tuple(
        VersionStatus(
            package=package,
            reviewed=str(baseline.get(baseline_key(package), "missing")),
            current=latest[package],
        )
        for package in sorted(latest)
    )


def build_baseline(
    previous: Mapping[str, Any],
    *,
    discovery: Mapping[str, Any],
    feed_raw: bytes,
    sdk_versions: Mapping[str, str],
) -> dict[str, Any]:
    """Return the baseline with every monitored key set to the live value."""
    return {
        **previous,
        "chat_discovery_sha256": canonical_sha256(discovery),
        "chat_release_feed_sha256": hashlib.sha256(feed_raw).hexdigest(),
        **{baseline_key(package): version for package, version in sdk_versions.items()},
    }


def build_snapshot(discovery: Mapping[str, Any], feed_raw: bytes) -> Snapshot:
    """Return the reviewed snapshot for the live discovery document and feed."""
    return {
        "discovery": snapshot_discovery(discovery),
        "release_feed": snapshot_feed(parse_feed(feed_raw)),
    }


def build_report(
    *,
    discovery: Mapping[str, Any],
    feed_raw: bytes,
    baseline: Mapping[str, Any],
    snapshot: Snapshot,
    allowlist: Mapping[str, str],
    registry_methods: Iterable[str],
    sdk_versions: Mapping[str, str],
) -> UpstreamReport:
    """Compare the live inputs with the reviewed state."""
    current = snapshot_discovery(discovery)
    live = build_baseline(
        {}, discovery=discovery, feed_raw=feed_raw, sdk_versions=sdk_versions
    )
    return UpstreamReport(
        triage=triage_methods(current["methods"], registry_methods, allowlist),
        allowlist=dict(sorted(allowlist.items())),
        discovery=diff_discovery(snapshot["discovery"], current),
        current=current,
        feed=diff_feed(snapshot["release_feed"], parse_feed(feed_raw)),
        sdk=compare_sdk_versions(baseline, sdk_versions),
        hashes=tuple(
            HashStatus(key, str(baseline.get(key, "missing")), live[key])
            for key in ("chat_discovery_sha256", "chat_release_feed_sha256")
        ),
    )


def _count(number: int, singular: str, plural: str) -> str:
    return f"{number} {singular if number == 1 else plural}"


def _code(value: str) -> str:
    # Names come from fetched documents: keep them inside one code span.
    return "`" + " ".join(value.replace("`", "'").split()) + "`"


def _codes(values: Iterable[str]) -> str:
    return ", ".join(_code(value) for value in values)


def _scopes(values: Iterable[str]) -> str:
    return _codes(value.removeprefix(SCOPE_PREFIX) for value in values) or "none"


def _plain(value: str) -> str:
    # Fetched prose lands in a GitHub issue. Escape Markdown punctuation and
    # break "@name" / "#123" with a zero-width space so that a release note
    # about @mentions cannot notify a GitHub user or link an issue.
    escaped = "".join(f"\\{char}" if char in "\\`*_[]<>|~" else char for char in value)
    return escaped.replace("@", "@​").replace("#", "#​")


def _row(*cells: str) -> str:
    return "| " + " | ".join(cell.replace("|", "\\|") for cell in cells) + " |"


def _delta_text(delta: Delta, render: Callable[[Iterable[str]], str] = _codes) -> str:
    parts = []
    if delta.added:
        parts.append(f"added {render(delta.added)}")
    if delta.removed:
        parts.append(f"removed {render(delta.removed)}")
    return "; ".join(parts)


def _entry_line(entry: FeedEntry) -> str:
    date = entry.updated[:10] if _timestamp(entry.updated) else entry.updated
    title = _plain(entry.title)
    safe_link = entry.link.startswith("https://") and not set(entry.link) & set(" ()<>")
    label = f"[{title}]({entry.link})" if safe_link else title
    return f"- {_plain(date)} — {label}: {_plain(entry.summary)}"


def _triage_section(report: UpstreamReport) -> list[str]:
    triage = report.triage
    lines = [
        "## Unwrapped methods",
        "",
        f"{triage.registered} of {triage.total} discovery methods are registered; "
        f"{_count(len(report.allowlist), 'is', 'are')} on the reviewed allowlist.",
        "",
    ]
    if triage.untriaged:
        lines.append("**Needs triage** (neither registered nor allowlisted):")
        lines.append("")
        lines.extend(
            f"- {_code(method)} — scopes: {_scopes(report.current['methods'][method])}"
            for method in triage.untriaged
        )
    else:
        lines.append("No method needs triage.")
    if triage.allowlisted_missing or triage.allowlisted_registered:
        lines.extend(["", "**Stale allowlist entries:**", ""])
        lines.extend(
            f"- {_code(method)} — no longer in the discovery document"
            for method in triage.allowlisted_missing
        )
        lines.extend(
            f"- {_code(method)} — now registered; remove it from the allowlist"
            for method in triage.allowlisted_registered
        )
    if report.allowlist:
        lines.extend(["", "Reviewed allowlist (intentionally not wrapped):", ""])
        lines.extend(
            f"- {_code(method)} — {reason}"
            for method, reason in report.allowlist.items()
        )
    return lines


def _method_status(report: UpstreamReport, method: str) -> str:
    if method in report.triage.untriaged:
        return "needs triage"
    return "allowlisted" if method in report.allowlist else "registered"


def _discovery_section(report: UpstreamReport) -> list[str]:
    diff, current = report.discovery, report.current
    revision = _code(diff.revision_current)
    if diff.revision_reviewed != diff.revision_current:
        revision = f"{_code(diff.revision_reviewed)} → {revision}"
    lines = ["## Discovery document", "", f"Revision: {revision}", ""]
    if not diff.needs_review:
        lines.append("No change in methods, scopes, schema fields, or enum values.")
        return lines
    if diff.untracked:
        lines.append(
            "The document changed outside the tracked surface (for example "
            "method parameters, types, or formats). Diff the live document "
            "against the previous revision before updating the baseline."
        )
        return lines

    def block(title: str, items: list[str]) -> None:
        if items:
            lines.extend([f"**{title}**", "", *items, ""])

    block(
        "Methods added",
        [
            f"- {_code(method)} — scopes: {_scopes(current['methods'][method])} "
            f"— {_method_status(report, method)}"
            for method in diff.methods.added
        ],
    )
    block("Methods removed", [f"- {_code(name)}" for name in diff.methods.removed])
    block(
        "OAuth scopes",
        [f"- {_delta_text(diff.scopes, _scopes)}"] if diff.scopes else [],
    )
    block(
        "Method scope changes",
        [
            f"- {_code(method)}: {_delta_text(delta, _scopes)}"
            for method, delta in diff.method_scopes.items()
        ],
    )
    block(
        "Schemas added",
        [
            f"- {_code(name)} — fields: {_codes(current['schemas'][name]) or 'none'}"
            for name in diff.schemas.added
        ],
    )
    block("Schemas removed", [f"- {_code(name)}" for name in diff.schemas.removed])
    block(
        "Schema fields",
        [
            f"- {_code(name)}: {_delta_text(delta)}"
            for name, delta in diff.fields.items()
        ],
    )
    block(
        "Enum values",
        [
            f"- {_code(name)}: {_delta_text(delta)}"
            for name, delta in diff.enum_values.items()
        ],
    )
    block(
        "Deprecation flags",
        [f"- {_delta_text(diff.deprecated)}"] if diff.deprecated else [],
    )
    return lines[:-1]


def _feed_section(feed: FeedDiff) -> list[str]:
    lines = ["## Release notes", ""]
    if feed.reviewed_through:
        lines.extend([f"Reviewed through {_plain(feed.reviewed_through[:10])}.", ""])
    if not feed.needs_review:
        lines.append("No new or edited entry.")
        return lines
    if feed.new:
        lines.extend(["**New entries**", "", *map(_entry_line, feed.new)])
    if feed.edited:
        if feed.new:
            lines.append("")
        lines.extend(["**Edited after review**", "", *map(_entry_line, feed.edited)])
    return lines


def _sources_section(report: UpstreamReport) -> list[str]:
    lines = [
        "## SDK versions",
        "",
        _row("Package", "Reviewed", "Latest", ""),
        _row("---", "---", "---", "---"),
    ]
    lines.extend(
        _row(
            _code(status.package),
            _code(status.reviewed),
            _code(status.current),
            "**changed**" if status.changed else "",
        )
        for status in report.sdk
    )
    lines.extend(
        [
            "",
            "## Source hashes",
            "",
            "Informational: a hash also moves when Google republishes a source "
            "without changing anything listed above.",
            "",
            _row("Baseline key", "Reviewed", "Current", ""),
            _row("---", "---", "---", "---"),
        ]
    )
    lines.extend(
        _row(
            _code(status.key),
            _code(status.reviewed[:12]),
            _code(status.current[:12]),
            "differs" if status.reviewed != status.current else "",
        )
        for status in report.hashes
    )
    return lines


def render_markdown(report: UpstreamReport) -> str:
    """Render the report; identical inputs give byte-identical output."""
    if report.needs_review:
        lead = "**Review needed:** " + "; ".join(report.findings) + "."
    else:
        lead = "**Nothing to review.** No tracked change since the reviewed baseline."
    lines = [
        lead,
        "",
        *_triage_section(report),
        "",
        *_discovery_section(report),
        "",
        *_feed_section(report.feed),
        "",
        *_sources_section(report),
        "",
        "## After review",
        "",
        "1. Register each new method in `src/chattice/capabilities/registry.py` "
        "or add it to `.github/upstream-allowlist.json` with a one-line reason.",
        "2. Update compatibility tests and documentation where the change "
        'affects them (CONTRIBUTING.md, "Upstream Google changes").',
        "3. Run `uv run python scripts/upstream_report.py --update-baseline` and "
        "commit `.github/upstream-baseline.json` and "
        "`.github/upstream-snapshot.json`.",
    ]
    return "\n".join(lines) + "\n"


def clip_report(markdown: str, limit: int) -> str:
    """Cut the report at a line boundary so it fits ``limit`` characters."""
    if len(markdown) <= limit:
        return markdown
    head = markdown[: max(0, limit - len(CLIP_NOTICE))]
    return head[: head.rfind("\n") + 1].rstrip("\n") + CLIP_NOTICE


def parse_allowlist(data: Any) -> dict[str, str]:
    """Validate the ``{method: reason}`` allowlist; every entry needs a reason."""
    if not isinstance(data, dict):
        raise UpstreamInputError("allowlist must be a JSON object")
    for method, reason in data.items():
        if not isinstance(reason, str) or not reason.strip():
            raise UpstreamInputError(f"allowlist entry {method!r} needs a reason")
    return dict(data)


def parse_snapshot(data: Any) -> Snapshot:
    """Validate the shape of a reviewed snapshot loaded from JSON."""
    try:
        discovery, feed = data["discovery"], data["release_feed"]
        return {
            "discovery": {
                "revision": str(discovery["revision"]),
                "structure_sha256": str(discovery["structure_sha256"]),
                "scopes": [str(scope) for scope in discovery["scopes"]],
                "methods": {
                    str(method): [str(scope) for scope in scopes]
                    for method, scopes in discovery["methods"].items()
                },
                "schemas": {
                    str(schema): {
                        str(field): [str(value) for value in values]
                        for field, values in fields.items()
                    }
                    for schema, fields in discovery["schemas"].items()
                },
                "deprecated": [str(label) for label in discovery["deprecated"]],
            },
            "release_feed": {
                "latest_updated": str(feed["latest_updated"]),
                "entries": {
                    str(entry): str(digest) for entry, digest in feed["entries"].items()
                },
            },
        }
    except (AttributeError, KeyError, TypeError) as error:
        raise UpstreamInputError(
            f"reviewed snapshot is malformed ({error!r}); "
            "regenerate it with --update-baseline"
        ) from error


def fetch_url(url: str) -> bytes:
    """Download one monitored source."""
    request = urllib.request.Request(
        url,
        headers={"User-Agent": "chattice-upstream-watch/1.0"},
    )
    with urllib.request.urlopen(request, timeout=60) as response:
        body: bytes = response.read()
    return body


def latest_pypi_version(package: str, fetch: Callable[[str], bytes]) -> str:
    """Return the latest version PyPI publishes for ``package``."""
    try:
        version = json.loads(fetch(PYPI_URL.format(package=package)))["info"]["version"]
    except (KeyError, TypeError) as error:
        raise UpstreamInputError(f"unexpected PyPI response for {package}") from error
    return str(version)


def _read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, data: Mapping[str, Any]) -> None:
    text = json.dumps(data, indent=2, sort_keys=True, ensure_ascii=False)
    path.write_text(text + "\n", encoding="utf-8")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Report Google Chat upstream changes since the reviewed baseline.",
    )
    parser.add_argument(
        "--discovery", type=Path, help="read the discovery document from this file"
    )
    parser.add_argument(
        "--feed", type=Path, help="read the release feed from this file"
    )
    parser.add_argument(
        "--save-discovery", type=Path, help="write the fetched discovery document here"
    )
    parser.add_argument("--baseline", type=Path, default=BASELINE_PATH)
    parser.add_argument("--snapshot", type=Path, default=SNAPSHOT_PATH)
    parser.add_argument("--allowlist", type=Path, default=ALLOWLIST_PATH)
    parser.add_argument(
        "--output", type=Path, help="write the Markdown report here, not to stdout"
    )
    parser.add_argument(
        "--max-chars", type=int, help="clip the report to this many characters"
    )
    parser.add_argument(
        "--update-baseline",
        action="store_true",
        help="after human review: rewrite the baseline and the snapshot from "
        "the live sources, then report what still needs review",
    )
    return parser


def main(
    argv: Sequence[str] | None = None,
    *,
    fetch: Callable[[str], bytes] = fetch_url,
    registry_methods: Iterable[str] | None = None,
) -> int:
    """Run the CLI; ``fetch`` and ``registry_methods`` are test seams."""
    args = _parser().parse_args(argv)
    try:
        discovery_raw = (
            args.discovery.read_bytes() if args.discovery else fetch(DISCOVERY_URL)
        )
        feed_raw = args.feed.read_bytes() if args.feed else fetch(RELEASE_FEED_URL)
        discovery = json.loads(discovery_raw)
        if not isinstance(discovery, dict):
            raise UpstreamInputError("discovery document must be a JSON object")
        if args.save_discovery:
            args.save_discovery.parent.mkdir(parents=True, exist_ok=True)
            args.save_discovery.write_bytes(discovery_raw)
        sdk_versions = {
            package: latest_pypi_version(package, fetch) for package in SDK_PACKAGES
        }
        allowlist = parse_allowlist(_read_json(args.allowlist))
        if args.update_baseline:
            previous = _read_json(args.baseline) if args.baseline.exists() else {}
            _write_json(
                args.baseline,
                build_baseline(
                    previous,
                    discovery=discovery,
                    feed_raw=feed_raw,
                    sdk_versions=sdk_versions,
                ),
            )
            _write_json(args.snapshot, build_snapshot(discovery, feed_raw))
            print(f"Updated {args.baseline} and {args.snapshot}", file=sys.stderr)
        report = build_report(
            discovery=discovery,
            feed_raw=feed_raw,
            baseline=_read_json(args.baseline),
            snapshot=parse_snapshot(_read_json(args.snapshot)),
            allowlist=allowlist,
            registry_methods=(
                registry_facts() if registry_methods is None else registry_methods
            ),
            sdk_versions=sdk_versions,
        )
    except (OSError, ValueError) as error:
        print(f"upstream_report: {error}", file=sys.stderr)
        return 2
    markdown = render_markdown(report)
    if args.max_chars is not None:
        markdown = clip_report(markdown, args.max_chars)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(markdown, encoding="utf-8")
    else:
        sys.stdout.write(markdown)
    return 1 if report.needs_review else 0


if __name__ == "__main__":
    raise SystemExit(main())
