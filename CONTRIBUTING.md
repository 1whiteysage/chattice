# Contributing to Chattice

Chattice is an async Python framework for Google Chat apps. Contributions
that are naturally additive are the most welcome:

- new Google UI support (widgets, cards)
- Google API wrappers behind the raw escape hatch pattern
- tests, examples, docs, bug fixes

## Workflow

1. Open an issue describing the problem or idea (no PR-first for
   architectural changes — see the RFC rule below).
2. Branch off `main`; implement with tests.
3. Run the project checks:

   ```bash
   uv sync --all-groups
   uv run python scripts/gen_sbom.py --check
   uv run pytest -q
   uv run mypy src tests
   uv run ruff check . && uv run ruff format --check .
   uv run mkdocs build --strict
   bash scripts/verify_package.sh
   ```

4. Open a PR. The description must state: the problem, public API
   impact, compatibility impact, tests/docs added, risk level, and
   whether core changed.

## Rules

- New application examples must expose a `main()` and include import and
  behavior checks in `tests/test_examples.py`. Replace external services in
  tests; the examples themselves use the normal authenticated APIs.
- Fixtures must be official payload shapes with provenance recorded in
  `tests/fixtures/google_chat/interactions/README.md`.
- Public API changes require typing,
  tests, docs, deliberate export, compatibility review.
- Architectural changes (Dispatcher/Router/FSM contracts, new workflow
  engines, package splits, breaking API) require a lightweight design
  proposal first: Problem · Current behavior · Proposed API · Why the
  current API is insufficient · Alternatives · Compatibility ·
  Rollout · Maintenance cost · Simpler solutions rejected.

## License

MIT. By contributing you agree your contributions are licensed
under it. No CLA required.

## Upstream Google changes

Google updates the wire layer (`google-apps-chat`, `google-apps-card`)
and ships Developer Preview features continuously. The documented public
surface changes deliberately, so every upstream change follows one protocol:

1. An update PR arrives from dependabot (weekly, `google-sdks` group)
   or from the daily `upstream-check` workflow's `upstream` issue. The
   issue body is the output of `scripts/upstream_report.py`: unwrapped
   methods needing triage, discovery methods/scopes/fields added or
   removed, new release notes, and SDK releases.
2. CI runs the full suite, mypy/ruff, and the golden fixtures.
3. Wire analysis of the SDK diff:
   - a new event FIELD → keep it lossless (`raw`), add a round-trip
     test; no public API change;
   - a new event TYPE → decide: typed support (adapter + capability)
     or explicit `UnknownEvent`; update the Google API mapping and the
     capabilities matrix;
   - a breaking change → P0 issue, a Chattice semver decision (rare).
4. Update fixtures (reviewed), docs (mapping/capabilities), and the
   compatibility revision. Register each new method or add it to
   `.github/upstream-allowlist.json` with a one-line reason, then run
   `uv run python scripts/upstream_report.py --update-baseline` and
   commit the rewritten `.github/upstream-baseline.json` and
   `.github/upstream-snapshot.json`.
5. Pre-release: run every example (the `examples/docs/from_zero.py`
   journey plus the bots/scenarios).

Principles: Google updates are additive INSIDE the adapters; the public
Chattice surface changes only by Chattice's own semver decision. The
lossless paths (`UnknownEvent`, `RawWidget`, `bot.raw.app()` / `bot.raw.user()`) absorb
new Google types — a new type must never crash existing bots.
