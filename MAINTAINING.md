# Maintaining Chattice

The runbook for keeping the project healthy with one maintainer. It lists
what runs by itself, what needs a decision, and how to make each decision
quickly. Contribution rules are in [CONTRIBUTING.md](CONTRIBUTING.md).

## What runs by itself

| Workflow | When | It produces | You do |
| --- | --- | --- | --- |
| `CI` | every pull request and push to `main` | lint, format, complexity limits, tests on Python 3.11–3.14, types, audit, docs, package build | fix what is red |
| `Google upstream watch` | daily | one issue labeled `upstream` that names what changed at Google | [triage it](#google-changes) |
| `Dependency refresh` | Mondays | one pull request with every in-range upgrade; lock, SBOM and notices together | [review and merge](#dependency-updates) |
| Dependabot | weekly / monthly | pull requests for upgrades that need a wider version range, GitHub Actions, security fixes | review and merge |
| `Dependabot fixup` | on Dependabot pull requests that change `uv.lock` | regenerated SBOM and notices on that branch | nothing |
| `Release` | on a `v*` tag | PyPI release and GitHub Release, after your approval | [approve](#release) |
| `Live Google smoke` | manual | proof that the code works against the real Google API | [run before a release that touches it](#live-verification) |

Nothing merges, tags or publishes without you.

## Weekly routine

About ten minutes when nothing changed at Google.

1. Open pull requests: merge **Refresh locked dependencies** and Dependabot
   pull requests whose CI is green.
2. Open issues labeled `upstream`: if there is one, triage it.
3. Nothing else is periodic.

## Google changes

The `upstream` issue body is the output of `scripts/upstream_report.py`. Work
through its sections in order; each has one decision.

| Section | Decision |
| --- | --- |
| **Needs triage** (an unwrapped method) | Wrap it if a wrapper adds identity routing, preflight, validation or paging ([ADR-012](docs/adr/ADR-012-curated-outbound-facade.md)). Otherwise add it to `.github/upstream-allowlist.json` with a one-line reason. |
| **Methods / scopes changed** | Update the matching `OperationSpec` in `src/chattice/capabilities/registry.py`. `scripts/verify_registry.py` fails until it matches. |
| **Schema fields added** | Usually nothing: unknown fields stay reachable through `raw`. Add typed support only when a handler would need it. |
| **Release notes** | Read each new entry. "Generally available" for something behind a preview gate: drop it from `DEVELOPER_PREVIEW_FEATURES`. A new Developer Preview: decide whether it belongs in `chattice.experimental`. |
| **SDK versions** | Covered by the dependency pull requests. |

Then record the review:

```bash
uv run python scripts/upstream_report.py --update-baseline
```

Commit `.github/upstream-baseline.json` and `.github/upstream-snapshot.json`
with the change. The next daily run closes the issue.

What the monitor cannot see: Developer Preview methods are not in the public
discovery document, and the add-on event format is documented only in prose.
For those, the release notes are the only signal and the
[live tests](#live-verification) are the only check.

Reproduce the report locally at any time:

```bash
uv run python scripts/upstream_report.py
```

## Dependency updates

- **Refresh locked dependencies** changes only `uv.lock`,
  `docs/release/sbom-chattice.spdx.json` and `THIRD_PARTY_NOTICES.md`. Green
  CI is enough for everything except the Google SDKs.
- For `google-apps-chat`, `google-apps-card` and `google-auth`, skim the
  SDK's release notes first: these define the wire layer. The `upstream`
  issue lists the same version change.
- A Dependabot pull request that widens a version range (for example a new
  major version of `mypy`) may need code changes; treat it as a normal change.
- By hand, when needed:

  ```bash
  uv lock --upgrade
  uv run python scripts/gen_sbom.py
  uv run python scripts/sync_notices.py
  ```

## Release

1. During development, describe changes under `## [Unreleased]` at the top of
   `CHANGELOG.md`.
2. Prepare the release. This updates the version in every file that states
   it, turns `[Unreleased]` into the release section, and regenerates the
   lock, SBOM and notices:

   ```bash
   uv run python scripts/prepare_release.py 0.4.1 "Short title"
   ```

3. Open a pull request, wait for CI, merge.
4. Tag the merge commit on `main`:

   ```bash
   git tag v0.4.1
   ```

   ```bash
   git push origin v0.4.1
   ```

5. In the `Release` workflow run, choose **Review deployments → pypi →
   Approve and deploy**.

A version number cannot be reused on PyPI. If a release is wrong, fix it and
publish the next patch version.

Versioning: before 1.0 an incompatible change needs a minor version and
upgrade notes ([ADR-011](docs/adr/ADR-011-versioning-policy.md)).

## Live verification

Unit tests use Google's documented shapes, not Google. Two areas have no other
check: `chattice.experimental` and the Workspace add-on payload family.

Run **Actions → Live Google smoke → Run workflow** before releasing a change
to outbound calls or to `chattice.experimental`. Setup (a test space and a
service-account key in the `google-live` environment) is described in
[tests/integration/live/README.md](tests/integration/live/README.md).

## Code health limits

CI enforces these; they are limits, not targets.

| Limit | Value | Where |
| --- | --- | --- |
| Cyclomatic complexity of a function | 10 | `[tool.ruff.lint.mccabe]` |
| Branches in a function | 12 | `[tool.ruff.lint.pylint]` |
| Statements in a function | 50 | `[tool.ruff.lint.pylint]` |
| Test coverage | 90% | `[tool.coverage.report]` |

When a change trips a limit, split the function along its steps or move a
`if`/`elif` chain into a table. Do not raise the limit or add `noqa` for it.

## Repository settings

These are not stored in the repository; check them once.

- **Actions → General → Allow GitHub Actions to create and approve pull
  requests**: required by `Dependency refresh`.
- **Branches → `main`**: require the `quality` and `docs` checks before
  merging.
- **Code security**: enable secret scanning with push protection and
  Dependabot security updates.
- **Environments**: `pypi` has a required reviewer (publishing gate);
  `google-live` holds the live-test credentials.
- **General → Automatically delete head branches**.

## If the maintainer is unavailable

The project has no long-lived publishing secret: PyPI trusts the `Release`
workflow of this repository in the `pypi` environment. A second person can
release only if they are all of the following, so add one ahead of time:

- an admin (or a maintainer with tag push rights) on the GitHub repository;
- a required reviewer of the `pypi` environment;
- an owner of the `chattice` project on PyPI, to change the trusted publisher
  if the repository ever moves.

Everything else needed to continue is in the repository: this file, the
architecture decisions in `docs/adr/`, and the reviewed upstream baseline.

## Handing a task to an AI assistant

The routine tasks are written so that they can be delegated. Give the
assistant the repository and one of these:

- "Triage the open `upstream` issue following MAINTAINING.md and prepare a
  pull request."
- "The dependency refresh pull request is red; find out why and fix it."
- "Prepare release X.Y.Z from `[Unreleased]`."

Review the pull request as you would any other; merging, tagging and the
`pypi` approval stay with you.
