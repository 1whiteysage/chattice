# Changelog

All notable changes are documented here. Versions follow Python packaging
conventions. Before 1.0, incompatible changes may be released in a minor
version and will include upgrade notes.

## [Unreleased]

No change to the public API or to runtime behavior.

### Changed

- Every function is within enforced limits: cyclomatic complexity 10,
  12 branches, 50 statements (`ruff` rules `C901`, `PLR0912`, `PLR0915`).
  Twelve functions were split to get there, among them the Pub/Sub delivery
  state machine, the dispatcher routing pass, the card section parser, and
  `Bot.close`.
- Dependabot uses the `uv` ecosystem, so its pull requests update `uv.lock`
  together with `pyproject.toml`.
- CI runs can be requested for a branch (`workflow_dispatch`), cancel
  superseded pull request runs, and have a time limit.

### Added

- `MAINTAINING.md` — the maintainer runbook: what runs by itself, the weekly
  routine, how to triage a Google change, how to release.
- `scripts/prepare_release.py` — bumps the version everywhere it is stated,
  turns `[Unreleased]` into the release section, and regenerates the lock,
  SBOM and notices.
- `scripts/sync_notices.py` — keeps the version column of
  `THIRD_PARTY_NOTICES.md` equal to `uv.lock`; `--check` runs in CI.
- `Dependency refresh` workflow — one weekly pull request with every in-range
  upgrade, with the SBOM and notices regenerated.
- `Dependabot fixup` workflow — regenerates the SBOM and notices on
  Dependabot pull requests that change the lock.

### Fixed

- `THIRD_PARTY_NOTICES.md` listed pyjwt 2.13.0; the lock has 2.15.1.

## [0.4.0] — Google Chat API catch-up

Covers the Google Chat API release notes through 2026-11-04.

### Added

- `bot.user.message_pins` — create, list, and delete message pins (generally
  available at Google since 2026-09-18).
- `bot.app.messages.replace_cards(name, cards)` — replace or remove app-owned
  cards without a user interaction (`spaces.messages.replaceCards`).
- `citations=` and `cited_sources=` on `messages.create` — inline citations
  and footer sources, with local validation of markup syntax and citation ids.
- `markup_syntax=` on `messages.update`.
- `bot.user.messages.search(query)`, `bot.user.spaces.search(query)`, and
  `bot.user.spaces.find_group_chats(users)`.
- `spaces.create`, `spaces.update`, `spaces.delete`, and
  `memberships.update(name, role=)` on both identities.
- `bot.user.users.availability` — own presence state and custom status;
  `bot.user.users.sections` — sidebar sections and their items;
  `bot.user.custom_emojis` — create, get, list, and delete custom emojis.
  Each adds `users/me` defaults, local validation, and paging over the SDK.
- `SystemCommandEvent`, `router.system_command`, and
  `EventFactory.system_command()` for Google's `SYSTEM_COMMAND` interaction
  (stream cancellation). Typed routing needs
  `PreviewFeature.MESSAGE_STREAMING`.
- `chattice.experimental.streaming` — `MessageStreams` / `MessageStream` over
  `spaces.streamMessages` (Developer Preview): start, append, replace, commit,
  discard, and an `async with` form that commits or discards.
- `chattice.experimental.sessions` — `ThreadSessions` over `spaces.threads`
  for 1:1 app direct messages (Developer Preview).
- `PreviewFeature.MESSAGE_STREAMING` and `PreviewFeature.THREAD_SESSIONS`.
- `FakeChatTransport` implements every newly wrapped method; `MockBot`
  mirrors the new message keywords and `replace_cards`.
- **Chat apps built as Google Workspace add-ons** (ADR-014). The interaction
  adapter accepts the add-on event object (`chat.<trigger>Payload`) and
  produces the same domain events; `Event.wire_format` records the family and
  the synchronous response is written in it (`createMessageAction`,
  `updateMessageAction`, `updateInlinePreviewAction`, `action.navigations`,
  `modifyOperations`, `basic_authorization_prompt`). New:
  `chattice.events.WireFormat`, `AddOnTokenVerifier`,
  `serialize_response()`, `create_chat_router(addon_action_url=)`,
  `Bot(addon_action_url=)`, `chattice.cards.addon.bind_addon_actions()`,
  `RequestConfigResponse(resource=)`. See
  [Workspace add-ons](docs/guides/workspace-addons.md). Written from Google's
  documentation; not yet exercised against a live add-on deployment.
- Administrator access: `admin_access=True` on `spaces.get/search/update/
  delete` and `memberships.create/get/list/update/delete` (USER identity).
  The `ADMIN` execution variant, modeled since 0.2.0, is now registered for
  the nine methods that document `useAdminAccess` and enforced by preflight.
- `Bot(preview_features={...})` and `bot.preview_capabilities`: per-feature
  Developer Preview enrollment. `Dispatcher(bot=bot)` routes preview events by
  the Bot's enrollment, so one setting covers both directions.
  `DEVELOPER_PREVIEW_FEATURES` and `PreviewCapabilities.all()` name what is in
  preview today.
- `chattice.testing.fake_bot()` — the real `Bot` on a `FakeChatTransport` in
  one call, returning `(bot, transport)`.
- Live smoke tests for message streaming, thread sessions, and
  `replace_cards` (`tests/integration/live`), and a manual
  `Live Google smoke` workflow. They are the only check of
  `chattice.experimental` against Google.
- Python 3.14 is tested in CI.

### Changed

- Cards can be sent with the USER identity: the local Developer Preview
  rejection is removed because Google made the feature generally available.
  The Chat app must be a member of the space.
- `PreviewFeature.REPLACE_CARDS`, `USER_AUTH_CARDS`, `PINNED_MESSAGES`, and
  `CUSTOMER_LEVEL_SUBSCRIPTIONS` describe generally available features. The
  values remain accepted.
- Every `Operation` now has a registry spec; the seven previously declared but
  unregistered operations are implemented.
- Availability is no longer raw-only: the wrapper qualifies for the curated
  facade (ADR-012) through identity preflight and local validation.
- Minimum `google-apps-chat` is 0.10.9 (message pins, `replaceCards`,
  citation types). The lock moves to google-auth 2.62.2, google-cloud-pubsub
  2.43.0, and google-apps-card 0.7.1.
- Each preview gate checks its own `PreviewFeature` and names it in the
  error. `Bot(enable_preview=True)` still enrolls in everything.
- `MockBot` raises an `AttributeError` that names any resource or method it
  does not mirror and points to `fake_bot()`. A test compares the mirrored
  signatures with the real client.
- The daily upstream monitor reports what changed
  (`scripts/upstream_report.py`): discovery methods that are neither
  registered nor on the reviewed allowlist
  (`.github/upstream-allowlist.json`); methods, OAuth scopes, schema fields,
  enum values and deprecation flags added or removed since the reviewed
  snapshot (`.github/upstream-snapshot.json`); new or edited release notes;
  SDK releases. A republished discovery document with only a new `revision`
  no longer opens an issue. After review run
  `uv run python scripts/upstream_report.py --update-baseline`.
- Internal: resource clients reach the SDK through one typed helper, and
  `Messages.create`, the interaction parser, and the response serializer are
  split into focused functions. No behavior change.
- The `gemini` extra accepts google-genai 3.x (`>=1,<4`).
- The lock updates certifi, filelock, msgpack, opentelemetry-api, and pyasn1 to
  versions without known advisories, so `pip-audit` passes again.

### Fixed

- `bot.user.users.read_state`, `thread_read_state`, and
  `notification_setting` sent the space or thread name as the resource name;
  Google expects `users/{user}/spaces/{space}/spaceReadState` (and the
  matching thread and notification names). A space, a thread, or the full
  resource name is now accepted and the correct name is sent.
  `notification_setting.update` no longer modifies the caller's `setting`.
- MockBot `messages.update/replace_cards/get/delete` and `spaces.get` accept
  `config=` like the real client.
- `FakeChatTransport.close()` no longer raises `NotImplementedError`, so
  `Bot.close()` works on a fake transport.

### Upgrade notes

- Install `google-apps-chat>=0.10.9`.
- A `SYSTEM_COMMAND` interaction is now parsed as `SystemCommandEvent`
  instead of `UnknownEvent`. Without the `MESSAGE_STREAMING` opt-in it reaches
  only `router.event` handlers, so a `router.unknown_event` handler that
  relied on it no longer receives it.
- Code that caught `CapabilityNotSupported` to detect USER-identity card
  sends no longer gets that error; the request goes to Google.
- Tests that used `Operation.SPACES_SEARCH` (or another formerly unregistered
  operation) to trigger `UnknownOperation` need an empty `OperationRegistry`.
- A payload with a `chat` object and no `type` used to be rejected with
  `UnsupportedEnvelopeError`; it is now parsed as an add-on event object.
- `Event` has a new field `wire_format`; event equality includes it.
- The action parameter name `chattice_function` is reserved when add-on
  action binding is enabled.
- `PreviewCapabilities.require()` has a new error text that names the
  feature and the Bot options.
- Code that patches `OperationExecutor.execute` in tests keeps working for
  normal calls; calls with `admin_access=True` also pass `variant=`.

### Not covered

- Organization-wide (customer-level) Workspace Events subscriptions are
  generally available, but creating subscriptions is still outside the curated
  surface; received events parse as before.
- Space events (`spaces.spaceEvents`) and import mode stay on `bot.raw`.
- `GetChatAppConfig` / `UpdateChatAppConfig` (Workspace Add-ons API,
  Developer Preview) are not wrapped.

## [0.3.5] — Google API compatibility

### Changed

- Message actions route without preview enrollment following general availability.
  The existing `PreviewFeature.MESSAGE_ACTION` value remains accepted.
- Update Google Auth to 2.57.1 and Pub/Sub to 2.40.0 in the dependency lock.
- Include Pub/Sub releases in the daily upstream monitor.

### Added

- `markup_syntax` on message creation selects Google's standard Markdown syntax.

### Fixed

- Describe user-scoped space search without requiring administrator privileges.

## [0.3.4] — Examples and documentation corrections

### Fixed

- Pub/Sub examples configure subscriber credentials separately and close bot clients reliably.
- Message filters and conversation examples handle mentions and invalid input consistently.
- Documentation reflects current transport, membership, media, and dialog APIs.
- Release metadata and the dependency inventory match the package version.

### Added

- Executable documentation examples and scenario tests for the example applications.

## [0.3.3] — Test hardening and aiogram-mirroring examples

### Added

- Pub/Sub pull runner tests for the `run()`/`close()` lifecycle, ACTIVE
  claims, renewal terminal paths, and the parse and answer-routing
  branches; runner coverage rises from 74% to 99%.
- Coverage of `chattice.testing` closed to 100% (MockBot attachments,
  identity facades, assertion failures, EventFactory coercions).
- Flat examples mirroring the aiogram example set: `echo_bot`,
  `echo_bot_webhook`, `error_handling`, `finite_state_machine`,
  `own_filter`, `specify_updates`, `context_addition_from_filter`,
  `without_dispatcher`.

### Changed

- The public API test tracks the pyproject version instead of a pinned
  literal.
- Examples use a flat module layout. The Google-native capability tour
  lives in `examples/docs/from_zero.py` and the guides.

### Fixed

- Stale documentation references to the removed example paths.

## [0.3.2] — setUpSpace human-member fix

### Fixed

- `bot.user.spaces.get_or_setup_direct_message` now marks the setup
  membership as `User.Type.HUMAN`; gRPC rejected the request with
  `TYPE_UNSPECIFIED` before.

## [0.3.1] — Documentation and release-gate alignment

### Changed

- Guides, architecture pages, examples, and the release smoke test use
  the curated facade (`bot.app.*` / `bot.user.*`) everywhere; no sample
  teaches a pre-0.3 call form.
- `scripts/gen_sbom.py` fails fast when the chattice entry is missing
  from `uv.lock`; the committed SBOM is regenerated for this release.

### Fixed

- Stale documentation statements corrected: raw-access guidance,
  attachment-download identity semantics, operation names in the Pub/Sub
  page, retry-table operation keys, and outdated version references.

## [0.3.0] — Legacy outbound surface removed (ADR-013)

### Removed

- The pre-0.2 `Bot` convenience methods: `send_message`, `update_message`,
  `get_message`, `delete_message`, `get_space`, `list_spaces`, `add_member`,
  `get_member`, `list_members`, `remove_member`, `upload_attachment`,
  `download_attachment`, `get_attachment`. Every operation lives on the
  identity-bound resource clients (`bot.app.*` / `bot.user.*`) and runs
  through the single registry → executor path.
- `Bot.raw_client`; use `await bot.raw.app()` / `await bot.raw.user()`.
- `Bot.capabilities` and the `OutboundCapabilities`/`OutboundCapability`
  matrix; `chattice.capabilities.Operation` and the `OperationRegistry`
  are the single preflight.

### Changed

- `MessageEvent.reply()`, `ThreadRef.send()`, and `SpaceRef.send()` are
  unchanged as DX and now delegate to `bot.app.messages.create(...)`
  (previously the removed wrapper). Reply-option defaults are unchanged.
- A zero-credential call fails closed with `CapabilityNotSupported`
  before any client construction or transport work, for both identities.
- `Memberships.create(parent, *, user=, group=)` canonicalizes the
  parent (`"AAA"` → `spaces/AAA`) and the user target
  (`"user-123"` → `users/user-123`); `memberships.get/delete` validate
  the canonical `spaces/{space}/members/{member}` name locally.
- `MockBot` exposes the same `bot.app` / `bot.user` resource facade as
  the real Bot; recorded call kinds are unchanged (`send_message`,
  `update_message`, ...).

### Upgrade notes

- `bot.send_message(space, text=...)` → `bot.app.messages.create(space,
  text=...)` (or `bot.user.messages.create(...)` for user-identity
  sends; attachment sends must use the USER namespace).
- Media: `bot.user.attachments.upload()`,
  `bot.app.attachments.download()` / `bot.user.attachments.download()`,
  `bot.app.attachments.get_metadata()`.
- The full removal → replacement map is in
  [stability](docs/stability.md).

## [0.2.1] — Media through the executor

### Changed

- `upload_attachment` and `download_attachment` run through the
  `OperationExecutor`; the legacy APP-with-USER-fallback selection of
  `download_attachment` stays in the method wrapper.

## [0.2.0] — Curated outbound facade

### Added

- Operation registry as the single source of outbound auth truth
  (`Operation`, `OperationSpec`, `AuthPath`, `ExecutionVariant`,
  `OperationRegistry`) with local preflight semantics; the legacy
  `OutboundCapability` enum is frozen and maps one-way onto operations.
- Identity-bound resource clients: `bot.app.*` / `bot.user.*` for
  `spaces`, `messages`, `memberships`, `reactions` (USER-only), and
  per-user state (`read_state`, `thread_read_state`,
  `notification_setting`). Identity is always explicit; no automatic
  APP/USER fallback.
- `OperationExecutor` — one execution path for every registered
  operation: spec lookup, preview gating, registry preflight, identity
  client resolution, and the curated error policy.
- `RequestConfig` per-call GAPIC configuration (`timeout`, `retry`,
  `metadata`) with raw-GAPIC-compatible defaults; `Pager` for explicit
  async pagination.
- `bot.raw.app()` / `bot.raw.user()` async raw access split by identity.
- `bot.user.spaces.find_direct_message` and USER-only
  `get_or_setup_direct_message` with explicit `timeout=` and the
  official `Space.space_uri` for opening a direct chat.
- `bot.warmup()` to resolve credentials and build clients before the
  first event; `Bot(enable_preview=True)` opt-in for preview operations.
- Runtime hardening: synchronous handlers rejected at registration,
  structured lifecycle diagnostics (`handler_started` before
  invocation), stage-tagged error logs, Pub/Sub delivery identity and
  age, per-message card update serialization, `RuntimeDiagnostics`
  thresholds, `Dispatcher(strict_interactions=True)`, router path
  identifiers, and observability hooks for handlers, outbound calls,
  and delivery ACK/NACK.
- Typed `RequestConfigResponse` for the `REQUEST_CONFIG` interaction
  response.
- CI verifier comparing the operation registry with the Google Chat
  discovery document.

### Changed

- Legacy `get_message`, `delete_message`, `get_space`, `list_spaces`,
  `add_member`, `get_member`, `list_members`, and `remove_member`
  delegate to resource clients and share the single executor path.
- Unhandled failures log exception classes and stages; exception text
  and tracebacks are DEBUG-only.

## [0.1.3] — Diagnostics and typed API errors

### Added

- DEBUG routing diagnostics for event receipt, observer selection, handler
  matching, and handler result types.
- Structured Pub/Sub answer and failure logs with delivery context,
  exception messages, and tracebacks without raw event payloads.
- `ChatAlreadyExistsError` for already-existing resources and HTTP 409
  Chat API failures.
- Public documentation for handler dependency injection, action data,
  typed Chat API errors, and production troubleshooting.

### Fixed

- Dependency-resolution errors now identify the handler, unresolved
  parameter, and event type.
- Membership and Space-list operations consistently expose the existing
  typed `ChatAPIError` hierarchy.

## [0.1.2] — Initial public release

### Added

- Async dispatcher, routers, middleware, dependency injection, filters, and
  typed Google Chat interaction events.
- HTTP, Pub/Sub, streaming-pull, and Google Workspace Events integrations.
- Async Google Chat API client with app and delegated-user authentication.
- Typed Cards v2 builders, dialogs, forms, App Home responses, card updates,
  attachments, and optional Card image publishing.
- Finite-state storage, idempotency storage, Redis integrations, lifecycle
  resources, and observability hooks.
- FastAPI integration, testing helpers, runnable examples, API reference, and
  deployment guidance.
- Raw Google payload and client escape hatches for forward compatibility.
- Automated dependency, Google Chat schema, Cards SDK, and release-note
  monitoring.

### Compatibility

- Python 3.11, 3.12, and 3.13.
- Google Chat API v1 and Cards v2.
- The package distribution and Python import are both named `chattice`.
