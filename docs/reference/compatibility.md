# Compatibility and schema status

Verified at release time.

| Input | Compatible snapshot |
| --- | --- |
| Chattice | 0.4.0 |
| Python | 3.11, 3.12, 3.13, 3.14 |
| `google-apps-chat` | `>=0.10.9,<1.0.0` (latest checked: 0.10.9) |
| Google Chat REST API | v1 |
| Google Chat Discovery revision | v1, pinned at release |
| Google Workspace Events envelopes | CloudEvents 1.0 |

The discovery revision is the live v1 document observed during the
release verification. Compatibility means Chattice's curated public
surface and fixtures were validated against this snapshot; it does not imply
that every method or field in the Google API has a high-level wrapper.

New/unsupported fields remain available through raw payloads and the official
client. Schema drift must be reviewed before changing the curated stable API;
generation must not silently mutate it. The Google REST reference links the
live [Discovery document](https://chat.googleapis.com/$discovery/rest?version=v1).

Preview-to-GA transitions, new scopes, methods, enum values, and deprecations
are release-maintenance inputs. The current release gate pins public exports,
parses representative payload fixtures, builds the generated reference,
and keeps unknown-event/raw fallbacks forward-compatible.

A scheduled workflow (`upstream-check`) runs `scripts/upstream_report.py`
daily against the live discovery document, the official release feed, and the
SDK releases on PyPI. When something needs review it opens one `upstream`
issue whose body names the change:

- discovery methods that are neither in the operation registry nor on the
  reviewed allowlist of intentionally unwrapped methods
  (`.github/upstream-allowlist.json`, one reason per method);
- methods, OAuth scopes, schema fields, enum values, and deprecation flags
  added or removed since the reviewed snapshot
  (`.github/upstream-snapshot.json`);
- release-feed entries added or edited since that snapshot;
- SDK versions newer than the reviewed ones
  (`.github/upstream-baseline.json`).

A republished document whose machine-readable surface is unchanged (a new
`revision` stamp or reworded descriptions) is not a finding. Nothing is
applied automatically. After review, this command rewrites the baseline and
the snapshot; the allowlist is edited by hand:

```bash
uv run python scripts/upstream_report.py --update-baseline
```
