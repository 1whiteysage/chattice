# Architecture decision records

ADRs capture proposed decisions before implementation. A `Proposed` ADR is a
reviewable design direction, not shipped behavior.

| ADR | Decision | Status |
| --- | --- | --- |
| [001](ADR-001-event-domain-model.md) | Framework-owned event domain model | Accepted |
| [002](ADR-002-dispatcher-router.md) | Dispatcher, router, and observer split | Accepted |
| [003](ADR-003-raw-google-models.md) | Raw Google model escape hatches | Accepted |
| [004](ADR-004-transport-abstraction.md) | Envelope-based transport abstraction | Accepted |
| [005](ADR-005-authentication-abstraction.md) | Separate request verification and API credentials | Accepted |
| [006](ADR-006-fsm-key-strategy.md) | Explicit FSM key strategy | Accepted |
| [007](ADR-007-cards-builder.md) | Independent typed Cards v2 builder | Accepted |
| [008](ADR-008-sync-async-responses.md) | Separate synchronous and asynchronous response APIs | Accepted |
| [009](ADR-009-google-interaction-normalization.md) | Google interaction envelope and common-data normalization | Accepted (add-on exclusion superseded by 014) |
| [010](ADR-010-project-identity.md) | Project identity | Accepted |
| [011](ADR-011-versioning-policy.md) | Versioning policy (pre-1.0 development releases) | Accepted |
| [012](ADR-012-curated-outbound-facade.md) | Curated outbound facade over an operation registry | Accepted (legacy facade removed by 013) |
| [013](ADR-013-legacy-facade-removal.md) | Remove the legacy outbound facade | Accepted |
| [014](ADR-014-workspace-addon-payload-family.md) | Workspace add-on payload family for Chat apps | Accepted |

New records copy [the template](template.md). Accepted decisions are immutable;
later changes supersede them with a new ADR.
