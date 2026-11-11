# ADR-012: Curated outbound facade over an operation registry

- Status: Accepted; partially superseded by ADR-013 (the frozen legacy facade was removed in 0.3.0; the curated resource facade and registry remain the architecture).

## Context

The high-level `Bot` API wraps a small subset of the Google Chat RPC
surface (message CRUD, space get/list, partial memberships), while the
public docs send everything else to `raw_client`. Google is expanding the
API quickly, adding GA features in rapid succession, and each method
carries its own combination of identity, OAuth scopes, execution
variants, and preview status. Continuing to add methods ad hoc would
either grow `Bot` into an unmaintainable monolith or duplicate the
generated SDK (`google-apps-chat`) with a permanent lag.

ADR-003 commits to official Google models, ADR-010 positions the project
as an ergonomic framework rather than a generated SDK clone, and ADR-011
requires public API compatibility even before 1.0.

## Decision

1. **Curated facade.** A method enters the stable high-level API only
   when Chattice adds real value over the generated SDK: identity
   routing, capability preflight, semantic validation, pagination
   abstraction, error normalization, integration with typed cards/events,
   or a meaningful semantic helper. Transparent 1:1 passthrough methods
   stay on the raw tier.

2. **Operation registry as the single source of auth truth.**
   - `Operation` becomes the fundamental public concept
     (e.g. `Operation.MESSAGES_SEARCH`).
   - Each operation declares an `OperationSpec` with one or more
     `AuthPath`s. An `AuthPath` names the identity (`AuthMode.APP` or
     `AuthMode.USER`), the admissible scopes, and optionally an execution
     variant. Admin and import are variants of an identity, not
     `AuthMode` values: `variant="admin"` adds `use_admin_access`,
     `variant="import"` selects import scopes.
   - The registry answers only "the local configuration allows an
     attempt", never "the call will succeed" — Google remains the final
     authority (403s from membership, role, policy, admin approval, or
     resource state are still possible). Preflight is local and typed.

3. **`OutboundCapability` is frozen as a legacy compatibility facade.**
   The enum, its members, and their `auto()` values stay unchanged, and
   no new members are added after 0.1.x. All authorization and scope
   logic associated with the enum is removed: `OutboundCapability`
   carries no authorization metadata. A one-way static mapping
   (`LEGACY_CAPABILITY_MAP`) resolves each member to an `Operation`, and
   `require(OutboundCapability.X)` delegates to the registry preflight.
   `OperationRegistry` is the only source of truth. Removal is not
   committed to any release; the facade is eligible for removal only
   after the normal deprecation process.

4. **Identity is explicit, never auto-selected for dual-auth
   operations.**
   - Dual-auth operations (messages.create, spaces.list,
     memberships.list, spaces.update, and similar) require the caller to
     choose: `bot.app.messages.create(...)` or
     `bot.user.messages.create(...)`. App and user calls differ in
     semantics (message author, content rules, visible spaces), so the
     framework must not choose silently.
   - Single-identity operations may resolve automatically
     (`bot.messages.search(...)` uses the user client).
   - Legacy methods (`send_message`, `list_spaces`, and similar) keep
     their current identity behavior unchanged.

5. **Raw tier is split by identity.** `await bot.raw.app()` and
   `await bot.raw.user()` return the underlying SDK client for the chosen
   identity. They are async because credential resolution is lazy and
   asynchronous; a plain property must not trigger credential I/O. The
   existing `raw_client` property keeps its current behavior.

6. **Registry verification in CI.** The existing upstream watch is
   extended with a registry check: the discovery document is compared
   against the registry for machine-checkable facts (method existence,
   scopes, request/response types, parameters). Semantic constraints
   (identity selection, admin approval, preview status, resource
   restrictions) stay human-reviewed metadata and are never generated.
   The watch also reports coverage: a discovery method that is neither
   registered nor on the reviewed allowlist of intentionally unwrapped
   methods (`.github/upstream-allowlist.json`) is listed for triage, so
   "not wrapped" is always a recorded decision.

7. **Pagination is explicit.** List and search methods expose async
   iteration by default and a convenience `limit=` / `collect()` for
   bounded materialization. Full silent materialization is not a default.

8. **Official response models.** Resource clients return official Google
   models (per ADR-003). New Chattice response dataclasses appear only
   where they add real ergonomics.

9. **Typed `RequestConfig`.** The `REQUEST_CONFIG` interaction response
   gets a typed form (`RequestConfig(auth_url=...)`) alongside the raw
   JSON path.

10. **Preview features stay separate.** Pinned messages, card
    replacement, and other Developer Preview surface live behind explicit
    `PreviewFeature` flags.

## Consequences

- Tests are data-driven: registry invariant tests over all operations,
  contract tests (every stable resource method has a spec, every legacy
  capability maps to an operation, every preview wrapper has a feature
  flag), and one or two representative tests per route class (app-only,
  user-only, dual identity, admin variant, import variant, preview,
  missing scopes). No cartesian product of methods x scopes x modes.
- `docs/guides/advanced-apis.md` is rewritten: the raw tier is the
  documented home for passthrough and niche surface, not an apology.
- Maintenance burden concentrates in one reviewed table plus CI alerts
  instead of scattered enum edits.
- Dual-auth call sites become explicit about identity; this is
  intentional and documented in upgrade notes.

## Alternatives considered

- Full RPC facade over every Google Chat method: rejected — duplicates
  the generated SDK with a permanent lag and multiplies maintenance
  (ADR-010).
- Extending `OutboundCapability` with all new operations: rejected — the
  enum grows back into the monolith the registry removes.
- Treating admin/import as `AuthMode` values: rejected — they are
  execution variants of an identity and would blur scope semantics.
- Automatic identity resolution from the registry: rejected — silently
  switching message authorship or visible-space semantics is too risky.
- Generating the registry from the discovery document: rejected — the
  document cannot express semantic constraints; those stay reviewed.

## Sources

- ADR-003 (official Google models), ADR-005 (authentication
  abstraction), ADR-010 (project identity), ADR-011 (versioning policy).
- Google Chat REST reference (spaces, messages, memberships, reactions,
  users.*) and the Workspace events API.
