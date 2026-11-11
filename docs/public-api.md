# Public API Reference

Public API snapshot for Chattice 0.4.0.

## Convention

- The package-level `__all__` in every `chattice` package/module **is** the
  public API. Everything listed below is deliberate: it is either documented in
  an [architecture doc](architecture/overview.md) or in the package docstring.
- Deep submodule paths (`chattice.cards.serialization.from_dict`, …) are
  **not** public API, with the explicit exceptions in
  [Compatibility notes](#compatibility-notes).
- `Since` identifies the first public release containing the symbol.

## Beta stability tiers

The supported surface is divided explicitly; importing a package does not blur
these promises:

1. **Stable public surface.** Every symbol exported through a stable package's
   `__all__`, plus the documented members below, follows the compatibility
   policy. Patch releases remain backward compatible.
2. **Experimental.** `chattice.experimental` and its subpackages can change or
   disappear without a compatibility promise. Preview feature flags do not by
   themselves make an experimental Google feature stable.
3. **Raw / advanced.** `bot.raw.app()` / `bot.raw.user()` and event `.raw`
   payloads expose the
   official Google client and wire data. They are deliberate escape hatches,
   but their breadth and evolution follow Google's SDK/schema rather than the
   stable Chattice facade contract.

## `chattice` (top level)

| Symbol        | Purpose                                                | Since |
| ------------- | ------------------------------------------------------ | ----- |
| `Dispatcher`  | Engine entry point: observers, middleware, DI | 0.1.2    |
| `Router`      | Handler tree for observers, commands, dialogs, forms    | 0.1.2    |
| `F`           | Magic filter DSL                                        | 0.1.2    |
| `__version__` | PEP 440 package version                                 | 0.2.0    |

## `chattice.dispatcher`

| Symbol         | Purpose                                    | Since |
| -------------- | ------------------------------------------ | ----- |
| `Dispatcher`   | Async dispatch engine (canonical home)     | 0.1.2    |
| `Router`       | Routing tree (canonical home)              | 0.1.2    |
| `EventObserver`| Primitive for observer/update registration | 0.1.2    |

## `chattice.events`

| Symbol                | Purpose                                            | Since |
| --------------------- | -------------------------------------------------- | ----- |
| `Event`               | Base domain event (frozen, slotted)                | 0.1.2    |
| `MessageEvent`        | Chat message; contextual `reply()` and lossless read metadata | 0.1.2    |
| `CommandEvent`        | Slash, quick, or message-action command            | 0.1.2    |
| `CommandKind`         | Typed Google-native command family                 | 0.1.2    |
| `ActionEvent`         | Card click / interaction                           | 0.1.2    |
| `ActionSource`        | Proven message/dialog/App Home action surface      | 0.1.2    |
| `AddedToSpaceEvent`   | Bot added to space                                 | 0.1.2    |
| `RemovedFromSpaceEvent`| Bot removed from space                             | 0.1.2    |
| `SystemCommandEvent`  | Google system command; `cancel_stream` for a stopped stream (Developer Preview routing) | 0.4.0    |
| `UnknownEvent`        | Forward-compatible unknown envelope fallback       | 0.1.2    |
| `ErrorEvent`          | Error-observer payload                             | 0.1.2    |
| `MessageRef`          | Typed message reference                            | 0.1.2    |
| `SpaceRef`            | Typed space reference with zero-fetch `send()`     | 0.1.2    |
| `ThreadRef`           | Typed thread + optional parent-space reference with `send()` | 0.1.2    |
| `UserRef`             | Typed user reference                               | 0.1.2    |
| `FormInputs`          | Form input mapping (`formInputs`)                  | 0.1.2    |
| `FormValue`           | Union of typed form input values                   | 0.1.2    |
| `StringInput`         | Single-line text input value                       | 0.1.2    |
| `DateInput`           | Date picker value                                  | 0.1.2    |
| `DateTimeInput`       | Date+time picker value                             | 0.1.2    |
| `TimeInput`           | Time picker value                                  | 0.1.2    |
| `UnknownFormInput`    | Forward-compatible form input fallback             | 0.1.2    |
| `DialogEventType`     | Dialog lifecycle type (submit/cancel)              | 0.1.2    |
| `DialogMetadata`      | Dialog metadata on interactions                    | 0.1.2    |
| `TimeZone`            | Normalized timezone value (id + offset)            | 0.1.2    |
| `AppHomeEvent`        | App Home / submit-form envelope                    | 0.1.2    |
| `FormSubmitEvent`     | App Home form submission                           | 0.1.2    |
| `WidgetUpdatedEvent`  | Widget-updated envelope                            | 0.1.2    |

## `chattice.filters`

| Symbol          | Purpose                                             | Since |
| --------------- | --------------------------------------------------- | ----- |
| `F`             | Magic filter DSL (canonical home)                   | 0.1.2    |
| `MagicExpression` | `F.x == y` intermediate expression                | 0.1.2    |
| `MagicField`    | `F.field` attribute access                          | 0.1.2    |
| `Filter`        | Async predicate protocol                            | 0.1.2    |
| `BaseFilter`    | Convenience base class                              | 0.1.2    |
| `FilterLike`    | Type alias (predicate or value)                     | 0.1.2    |
| `FilterValue`   | Type alias for filterable values                    | 0.1.2    |
| `MagicField.regexp(pattern, flags=)` | Python-regex routing, `re.match` semantics | 0.1.2    |

## `chattice.middleware`

| Symbol          | Purpose                                             | Since |
| --------------- | --------------------------------------------------- | ----- |
| `Middleware`    | Structural protocol for dispatch middleware         | 0.1.2    |
| `BaseMiddleware`| Convenience base class                              | 0.1.2    |
| `MiddlewareLike`| Type alias                                          | 0.1.2    |
| `NextHandler`   | Type alias for the `handler` argument               | 0.1.2    |

## `chattice.exceptions`

| Symbol                     | Purpose                                        | Since |
| -------------------------- | ---------------------------------------------- | ----- |
| `ChatticeError`            | Base exception for all framework errors        | 0.1.2    |
| `StopPropagation`          | Halt routing after the current handler         | 0.1.2    |
| `SkipHandler`              | Skip to the next matching handler              | 0.1.2    |
| `RoutingControl`           | Type union of routing control exceptions       | 0.1.2    |
| `RoutingError`             | Dispatch-time routing failure                  | 0.1.2    |
| `FilterError`              | Filter evaluation failure                      | 0.1.2    |
| `InvalidHandlerError`      | Handler registration/signature violation       | 0.1.2    |
| `ContextConflictError`     | Duplicate data-key injection in a handler      | 0.1.2    |
| `DependencyResolutionError`| Handler dependency plan failure                | 0.1.2    |
| `RouterConfigurationError` | Router misconfiguration                        | 0.1.2    |
| `AssetError`               | Local Card asset failure base                  | 0.1.2    |
| `AssetPublisherNotConfigured` | Local Card image used without a publisher   | 0.1.2    |
| `AssetPublishError`        | Local Card image publication/resolution failure | 0.1.2    |

## `chattice.assets`

| Symbol           | Purpose                                                    | Since |
| ---------------- | ---------------------------------------------------------- | ----- |
| `AssetPublisher` | Structural async protocol for publishing local Card images | 0.1.2    |

## `chattice.adapters.google_chat`

| Symbol                     | Purpose                                           | Since |
| -------------------------- | ------------------------------------------------- | ----- |
| `GoogleInteractionAdapter`| Pure adapter: decoded Google payload → domain event | 0.1.2    |
| `parse_interaction`        | Decode + normalize a raw interaction              | 0.1.2    |
| `GoogleInteractionError`   | Base adapter error                                | 0.1.2    |
| `InvalidInteractionPayload`| Malformed interaction payload                     | 0.1.2    |
| `UnsupportedEnvelopeError` | Unknown envelope family                           | 0.1.2    |
| `ConflictingEnvelopeError` | Ambiguous/multi-family envelope                   | 0.1.2    |

## `chattice.transports.http`

| Symbol                  | Purpose                                             | Since |
| ----------------------- | --------------------------------------------------- | ----- |
| `IncomingRequest`       | Normalized HTTP interaction request                 | 0.1.2    |
| `IncomingRequestVerifier`| Request verification protocol                      | 0.1.2    |
| `GoogleTokenVerifier`   | google-auth-based Google token verification         | 0.1.2    |
| `MockVerifier`          | Test verifier (accepts anything unless reject=True) | 0.1.2    |
| `InteractionResponse`   | Response model (text / cards / dialogs / errors)    | 0.1.2    |
| `ResponseState`         | Response state machine (double-response guard)      | 0.1.2    |
| `InteractionContext`    | HTTP-only verified request/response + 30s deadline  | 0.1.2    |
| `HTTPInteractionAdapter`| Web-framework-neutral ingress adapter               | 0.1.2    |
| `SYNC_RESPONSE_DEADLINE`| Documented 30-second sync response limit (constant) | 0.1.2    |
| `HTTPInteractionError`  | HTTP ingress error base                             | 0.1.2    |
| `VerificationError`     | Token verification failure                          | 0.1.2    |
| `DoubleResponseError`   | Sync response after ack or repeated send            | 0.1.2    |

## `chattice.transports.pubsub`

| Symbol               | Purpose                                            | Since |
| -------------------- | -------------------------------------------------- | ----- |
| `PubSubPushAdapter`  | CloudEvent envelope → interaction event            | 0.1.2    |
| `PubSubEnvelopeError`| Pub/Sub envelope decoding error                    | 0.1.2    |
| `decode_message_data`| Decode + base64-decode the CloudEvent payload      | 0.1.2    |

## `chattice.integrations.fastapi`

| Symbol                        | Purpose                                  | Since |
| ----------------------------- | ---------------------------------------- | ----- |
| `create_chat_router`          | Chat HTTP interactions router            | 0.1.2    |
| `create_pubsub_router`        | Pub/Sub push router (204 ack)            | 0.1.2    |
| `create_workspace_events_router`| Workspace Events push router           | 0.1.2    |

## `chattice.integrations.gcs`

| Symbol              | Purpose                                                   | Since |
| ------------------- | --------------------------------------------------------- | ----- |
| `GCSAssetPublisher` | Optional GCS implementation of the Card AssetPublisher    | 0.1.2    |

## `chattice.client`

| Symbol                         | Purpose                                        | Since |
| ------------------------------ | ---------------------------------------------- | ----- |
| `Bot`                          | Async outgoing Chat API client                 | 0.1.2    |
| `ChatAPIError`                 | Wrapped Chat API error base                    | 0.1.2    |
| `ChatAlreadyExistsError`       | Wrapped 409/already-exists error               | 0.1.3    |
| `ChatInvalidArgumentError`     | Wrapped 400-class error                        | 0.1.2    |
| `ChatPermissionDeniedError`    | Wrapped 403-class error                        | 0.1.2    |
| `ChatNotFoundError`            | Wrapped 404-class error                        | 0.1.2    |
| `ChatRateLimitError`           | Wrapped 429-class error                        | 0.1.2    |
| `ChatServiceUnavailableError`  | Wrapped 503-class error                        | 0.1.2    |
| `ChatUnauthenticatedError`     | Wrapped 401-class error                        | 0.1.2    |
| `wrap_api_error`               | Error mapping helper (SDK error → hierarchy)   | 0.1.2    |
| `CredentialsProvider`          | Credential protocol — compatibility re-export    | 0.1.2    |
| `Bot(..., asset_publisher=)` | Configure local Card image publication for send/update | 0.1.2    |
| `bot.user.attachments.upload()` | USER-auth media upload (`InputFile` → `UploadedAttachment`) | 0.3.0    |
| `bot.app.attachments.download()` / `bot.user.attachments.download()` | Media download (bytes or Path) | 0.3.0    |
| `bot.app.attachments.get_metadata()` | Attachment metadata (APP auth + chat.bot) | 0.3.0    |
| `bot.user.messages.create(..., attachments=)` | Create with uploaded/local attachments — USER identity end to end (sender = HUMAN) | 0.3.0    |
| `bot.app.attachments` / `bot.user.attachments` | Media resource namespace: `upload` / `download` / `get_metadata` | 0.3.0    |


## Additional namespaces and members

| Entry point | Purpose | Since |
| --- | --- | --- |
| `chattice.capabilities.Operation`                   | Declarative outbound operation name (registry source of truth) | 0.2.0    |
| `chattice.capabilities.OperationRegistry` / `chattice.capabilities.REGISTRY` | Lookup + local preflight over operation specs           | 0.2.0    |
| `chattice.capabilities.OperationSpec` / `chattice.capabilities.AuthPath`  | Identity + scope + variant rules for one operation     | 0.2.0    |
| `chattice.capabilities.ExecutionVariant`            | NORMAL / ADMIN / IMPORT execution variants              | 0.2.0    |
| `bot.app` / `bot.user`        | Identity-bound resource roots (`spaces` / `messages` / `memberships`) | 0.2.0    |
| `bot.raw.app()` / `bot.raw.user()` | Async raw SDK access split by identity             | 0.2.0    |
| `bot.app.spaces.find_direct_message()` | Find 1:1 DM space (explicit identity, `timeout=`) | 0.2.0    |
| `bot.user.spaces.get_or_setup_direct_message()` | Find or set up DM on 404 (USER-only)   | 0.2.0    |
| `bot.user.reactions`         | USER-only reactions: create / list (Pager) / delete | 0.2.0    |
| `bot.user.users.*`            | USER-only per-user state: `read_state`, `thread_read_state`, `notification_setting` | 0.2.0    |
| `chattice.transports.http.RequestConfigResponse`       | Typed REQUEST_CONFIG HTTP response (`auth_url`)    | 0.2.0    |
| `chattice.client.RawClients` (`bot.raw`)       | Async raw SDK access split by identity            | 0.2.0    |
| `chattice.client.resources.Users` (`bot.user.users`)      | Per-user state namespace: `read_state`, `thread_read_state`, `notification_setting` | 0.2.0    |
| `chattice.client.resources.Reactions` (`bot.user.reactions`) | USER-only reactions: create / list (Pager) / delete | 0.2.0    |
| `chattice.capabilities.scopes(...)`                  | Fully-qualified OAuth scope helper                | 0.2.0    |
| `bot.user.message_pins` (`chattice.client.resources.MessagePins`) | USER-only message pins: create / list (Pager) / delete | 0.4.0    |
| `bot.app.messages.replace_cards()` | Replace app-owned cards without a user interaction (APP-only) | 0.4.0    |
| `messages.create(..., citations=, cited_sources=)` | Inline citations and footer sources (Markdown markup) | 0.4.0    |
| `messages.update(..., markup_syntax=)` | Markup syntax for the updated text | 0.4.0    |
| `bot.user.messages.search()` | Search messages across the user's spaces (Pager, USER-only) | 0.4.0    |
| `bot.user.spaces.search()` / `.find_group_chats()` | Search joined spaces; find group chats by members (Pager, USER-only) | 0.4.0    |
| `spaces.create()` / `.update()` / `.delete()` | Space management with an explicit identity | 0.4.0    |
| `memberships.update(name, role=)` | Change a membership role | 0.4.0    |
| `bot.user.users.availability` (`chattice.client.resources.Availability`) | Own presence state and custom status (USER-only) | 0.4.0    |
| `bot.user.users.sections` (`chattice.client.resources.Sections`) | Sidebar sections and their items (USER-only) | 0.4.0    |
| `bot.user.custom_emojis` (`chattice.client.resources.CustomEmojis`) | Organization custom emojis: create / get / list (Pager) / delete (USER-only) | 0.4.0    |
| `router.system_command` | Observer for `SystemCommandEvent` (needs `PreviewFeature.MESSAGE_STREAMING`) | 0.4.0    |
| `EventFactory.system_command()` | Test builder for `SystemCommandEvent` | 0.4.0    |
| `chattice.experimental.streaming` | Stream messages over `spaces.streamMessages` (experimental, Developer Preview) | 0.4.0    |
| `chattice.experimental.sessions` | Thread sessions in 1:1 app DMs (experimental, Developer Preview) | 0.4.0    |
| `chattice.events.WireFormat` / `Event.wire_format` | Payload family an interaction arrived in: `CHAT_API` or `ADDON` | 0.4.0    |
| `chattice.transports.http.AddOnTokenVerifier` | Request verifier for Chat apps built as Workspace add-ons | 0.4.0    |
| `chattice.transports.http.serialize_response()` | Handler result to wire JSON in the event's payload family | 0.4.0    |
| `create_chat_router(..., addon_action_url=)` / `Bot(..., addon_action_url=)` | Bind card actions to an HTTP add-on endpoint | 0.4.0    |
| `chattice.cards.addon.bind_addon_actions()` / `ADDON_FUNCTION_PARAMETER` | Explicit add-on action binding and its reserved parameter | 0.4.0    |
| `RequestConfigResponse(..., resource=)` | Service display name for the add-on authorization prompt | 0.4.0    |
| `spaces.get/search/update/delete(..., admin_access=)`, `memberships.*(..., admin_access=)` | Workspace administrator access on the USER identity (`ADMIN` variant) | 0.4.0    |
| `Bot(..., preview_features=)` / `bot.preview_capabilities` | Per-feature Developer Preview enrollment shared with `Dispatcher(bot=bot)` | 0.4.0    |
| `chattice.capabilities.DEVELOPER_PREVIEW_FEATURES` / `PreviewCapabilities.all()` | The features in Developer Preview today | 0.4.0    |
| `chattice.exceptions.UnhandledInteractionError`    | Strict-interactions routing error                  | 0.2.0    |
| `bot.warmup()`                | Resolve credentials / build clients before first event   | 0.2.0    |
| `chattice.client.paging.Pager`                       | Explicit async paging (`collect(limit=...)`)            | 0.2.0    |
| `chattice.client.config.RequestConfig`               | Per-call GAPIC config: `timeout=`, `retry=`, `metadata=` (frozen) | 0.2.0    |
| `Bot(..., enable_preview=)`   | Explicit opt-in for registry-marked preview operations  | 0.2.0    |
| `chattice.observability.RuntimeDiagnostics`          | Thresholds: `slow_handler_ms`, `delayed_event_ms`       | 0.2.0    |
| `Dispatcher(strict_interactions=)` | Unmatched interactive events as errors (opt-in)   | 0.2.0    |

## `chattice.cards`

| Symbol              | Purpose                                         | Since |
| ------------------- | ----------------------------------------------- | ----- |
| `Card`              | Cards v2 top-level facade                       | 0.1.2    |
| `CardHeader`        | Card header facade                              | 0.1.2    |
| `Section`           | Card section facade                             | 0.1.2    |
| `TextParagraph`     | Text widget                                     | 0.1.2    |
| `Divider`           | Divider widget                                  | 0.1.2    |
| `ButtonList`        | Button list widget                              | 0.1.2    |
| `Button`            | Button widget                                   | 0.1.2    |
| `Action`            | onClick action facade                           | 0.1.2    |
| `OpenLink`          | openLink action facade                          | 0.1.2    |
| `TextInput`         | Text input widget                               | 0.1.2    |
| `SelectionInput`    | Selection input widget                          | 0.1.2    |
| `DateTimePicker`    | Date/time picker widget                         | 0.1.2    |
| `Dialog`            | Dialog body facade                              | 0.1.2    |
| `ActionStatus`      | actionResponse status facade                    | 0.1.2    |
| `ActionStatusCode`  | Status codes (`OK`, `INVALID_ARGUMENT`)         | 0.1.2    |
| `ButtonInteraction` | `OPEN_DIALOG` interaction constant              | 0.1.2    |
| `Validation`        | Input validation facade (character limit/type)  | 0.1.2    |
| `TextInputType`     | Input type constants                            | 0.1.2    |
| `Image`             | HTTPS or lazily published local PNG/JPEG picture widget | 0.1.2    |
| `Image.from_url()`  | Already published HTTPS Card image              | 0.1.2    |
| `Image.from_path()` | Lazy local path published during Bot send/update | 0.1.2    |
| `Image.from_bytes()`| Immutable byte snapshot published during Bot send/update | 0.1.2    |

## `chattice.media`

| Symbol                    | Purpose                                       | Since |
| ------------------------- | --------------------------------------------- | ----- |
| `InputFile`               | Canonical local file model (`from_path`/`from_bytes`) | 0.1.2    |
| `UploadedAttachment`      | Upload result scoped to one Space             | 0.1.2    |
| `AttachmentRef`           | Typed inbound attachment metadata             | 0.1.2    |
| `AttachmentSource`        | `UPLOADED_CONTENT` / `DRIVE_FILE`             | 0.1.2    |
| `MAX_ATTACHMENT_SIZE_BYTES` | Documented 200 MB upload ceiling            | 0.1.2    |

## `chattice.fsm`

| Symbol             | Purpose                                           | Since |
| ------------------ | ------------------------------------------------- | ----- |
| `State`            | Named FSM state                                   | 0.1.2    |
| `StatesGroup`      | State group container                             | 0.1.2    |
| `FSMContext`       | Per-user/per-space state context                  | 0.1.2    |
| `StorageKey`       | Scoped storage key (user/space/thread)            | 0.1.2    |
| `FSMStrategy`      | Key strategy enum (default `USER_IN_SPACE`)       | 0.1.2    |
| `BaseStorage`      | Storage protocol                                  | 0.1.2    |
| `MemoryStorage`    | In-memory storage                                 | 0.1.2    |
| `RedisStorage`     | Redis storage (lazy import, `chattice[redis]`)  | 0.1.2    |
| `StateFilter`      | Filter matching current state                     | 0.1.2    |
| `FSMError`         | FSM error base                                    | 0.1.2    |

## `chattice.auth`

| Symbol                            | Purpose                                   | Since |
| --------------------------------- | ----------------------------------------- | ----- |
| `CredentialsProvider`             | Credential protocol (canonical home)      | 0.1.2    |
| `ServiceAccountCredentialsProvider`| Lazy service-account credentials         | 0.1.2    |
| `UserCredentialsProvider`         | User credentials with lazy refresh        | 0.1.2    |
| `DelegatedUserCredentialsProvider`| Domain-Wide Delegation user auth (`with_subject`) | 0.1.2    |
| `AuthMode`                        | Auth mode enum (app / user)               | 0.1.2    |
| `CHAT_BOT_SCOPE`                  | Documented `chat.bot` OAuth scope         | 0.1.2    |
| `CHAT_APP_MEMBERSHIPS_SCOPE`      | Admin-approved APP membership scope       | 0.1.2    |

## `chattice.capabilities`

Capabilities are split into three explicit questions: ingress response,
outbound operations, and preview enrollment
([capabilities](architecture/capabilities.md)). Outbound operation
capabilities are covered by `Operation` and the registry
([architecture](architecture/bot-api-client.md)).

| Symbol                  | Purpose                                                    | Since |
| ----------------------- | ---------------------------------------------------------- | ----- |
| `ResponseCapabilities`  | Ingress response channel: transport + concrete event       | 0.1.2    |
| `ResponseCapability`    | SYNC_RESPONSE, DIALOGS, APP_HOME, CARD_UPDATE_*, UPDATE_WIDGET | 0.1.2    |
| `PreviewCapabilities`   | Explicit immutable Developer Preview enrollment            | 0.1.2    |
| `PreviewFeature`        | Developer Preview Google features (stability flags)        | 0.1.2    |
| `can_open_dialog`       | One dialog predicate shared by capabilities + serializer   | 0.1.2    |
| `CapabilityNotSupported`| Runtime guard exception (fail before network)              | 0.1.2    |

## `chattice.workspace_events`

| Symbol                 | Purpose                                           | Since |
| ---------------------- | ------------------------------------------------- | ----- |
| `EventsDispatcher`     | Independent Workspace resource-event feed         | 0.1.2    |
| `EventsRouter`         | Independent Workspace resource-event router tree  | 0.1.2    |
| `WorkspaceEvent`       | Workspace Events domain model                     | 0.1.2    |
| `WorkspaceEventType`   | Documented event type strings                     | 0.1.2    |
| `parse_workspace_event`| CloudEvent → `WorkspaceEvent`                     | 0.1.2    |
| `WorkspaceEventError`  | Envelope/parse error                              | 0.1.2    |

## `chattice.testing`

| Symbol                | Purpose                                        | Since |
| --------------------- | ---------------------------------------------- | ----- |
| `MockBot`             | DI-compatible Bot recorder (no network)        | 0.1.2    |
| `EventFactory`        | Typed event builders (no raw Google JSON)      | 0.1.2    |
| `FakeChatTransport`   | Fake transport for Google Chat client tests       | 0.1.2    |
| `fake_bot`            | Real `Bot` on a `FakeChatTransport` in one call; returns `(bot, transport)` | 0.4.0    |
| `assert_card_has_button` | Card assertion helper                       | 0.1.2    |
| `assert_card_header`  | Card header assertion helper                   | 0.1.2    |
| `set_state_for`       | FSM state seeding helper                       | 0.1.2    |

## `chattice.idempotency`

| Symbol                       | Purpose                                    | Since |
| ---------------------------- | ------------------------------------------ | ----- |
| `IdempotencyStorage`         | Storage protocol                           | 0.1.2    |
| `MemoryIdempotencyStorage`   | In-memory storage                          | 0.1.2    |
| `RedisIdempotencyStorage`    | Redis storage (SET NX EX, single command)  | 0.1.2    |

## `chattice.observability`

| Symbol              | Purpose                                      | Since |
| ------------------- | -------------------------------------------- | ----- |
| `ObservabilityHooks`| Per-event observability hooks (additive, fail-isolated) | 0.1.2    |

## `chattice.experimental`

The marker package has no direct exports; its subpackages (such as
`chattice.experimental.ai`) are explicitly outside the stable core/public
API; they may change
or disappear without notice. Stable core never imports it. Preview flags that
gate stable parser/router behavior remain in `chattice.capabilities`.

---

## Additional public surfaces

| Package | Symbols |
| --- | --- |
| `chattice.actions` | `ActionData`, `ActionDataDecodeError`, `ActionDataFilter` |
| `chattice.forms` | `FormModel`, `FormDecodeError`, `FormFilter` |
| `chattice.cards` | +`AccessoryWidget`, `RawWidget`; `Button.required_widgets` |
| `chattice.fsm` | +`FSMRecord`, `FSMRecordConflict`, `FSMRecordStorage`, `MemoryFSMRecordStorage`, `RedisFSMRecordStorage`, `BaseStorageFromRecord` |
| `chattice.dispatcher` | +`Lifespan`, `LifespanResource` (`Dispatcher.lifespan`) |
| `chattice.transports.http` | +`WidgetAutocomplete`, `RawInteractionResponse` |
| `chattice.transports.pubsub` | +`GooglePubSubVerifier`, `MockPubSubVerifier`, `PubSubPushVerifier` |
| `chattice.client` | `bot.app`/`bot.user` resource namespaces; `async close()` + context manager |
| `chattice.idempotency` | owner-safe `claim/complete/release/renew`, `ClaimResult` |
| `chattice.capabilities` | `ResponseCapabilities`/`PreviewCapabilities`/`PreviewFeature`; `REGISTRY` operation preflight |

## Additional type members

The following members are available on public types:

| Type | Additive member / accepted form | Contract |
| --- | --- | --- |
| `Dispatcher` | `bot=` constructor keyword | Makes one authenticated Bot available to contextual methods and ordinary DI; per-call `feed_update(..., bot=...)` remains supported. |
| `SpaceRef` | `send(...)` | Delegates once to `bot.app.messages.create(space_ref, ...)`; performs no resource lookup. |
| `ThreadRef` | `space`; `send(...)` | Parsed threads retain their known parent. Sends delegate once to `bot.app.messages.create(..., thread=thread_ref)`; a missing parent fails locally. |
| `MessageEvent` | `reply(...)` | Sends to the known space/thread with the SDK's `REPLY_MESSAGE_OR_FAIL` option; missing context fails locally. |
| `MessageEvent` | `attachments`, `annotations`, `mentions`, `quote`, `reaction_summaries`, `is_private`, `is_silent` | Deep immutable, lossless views over the preserved Google message payload; no read or write service call. |
| `ActionData` | `function=` subclass keyword / `.function` | Binds the typed model to Google's existing action function discriminator. |
| `Button` | `action=ActionData(...)` | Encodes the bound function plus flat Google parameters. The existing string `action=` + `parameters=` form is unchanged. |

`chattice.experimental.ai` subpackage contains optional integration
contracts (agent request/response, tool policy, a provider adapter). It
is experimental and outside the stable API; it is not part of the
stable inventory below.

## Compatibility notes

Validated against the full test suite, mypy, ruff, and the strict mkdocs build.

### Additional import paths outside package `__all__`

These live at deep submodule paths. They are imported by tests/examples and
remain importable for compatibility but are **not** part of the recommended
surface:

| Path                                              | Symbols                                        | Note |
| ------------------------------------------------- | ---------------------------------------------- | ---- |
| `chattice.dispatcher.dependency`                | `HandlerPlan`, `HandlerCallback`, `ParameterPlan`, `build_handler_plan` | DI plan contract, asserted in tests |
| `chattice.dispatcher.handler`                   | `HandlerObject`                                | Handler wrapper |
| `chattice.dispatcher.middleware`                | `MiddlewareManager`                            | Middleware chain |
| `chattice.fsm.states`                           | `StatesGroupMeta`                              | Metaclass behind `StatesGroup` |
| `chattice.cards.serialization`                  | `from_dict`, `to_dict`                         | Card JSON round-trip, used by tests |
| `chattice.client.credentials`                   | `CredentialsProvider`                          | Compatibility re-export (canonical home `chattice.auth`) |
| `chattice.testing.fake_transport`               | `FakeChatTransport`                            | Compatibility import path |
| `chattice.adapters.google_chat.exceptions`      | `InvalidInteractionPayload` et al.             | Deep error paths mirror package exports |

### Module imports visible outside `__all__` (not exports)

`chattice.middleware.Event`, `chattice.transports.pubsub.Event` and
`chattice.transports.pubsub.parse_interaction` are ordinary module imports
used inside the module body. They are excluded from `__all__`, so
`from … import *` is controlled; they are not part of the public API and
should not be imported from these paths.

### Lazy imports

`chattice.fsm.RedisStorage` is resolved through a module `__getattr__` so
the `redis` dependency stays optional (`chattice[redis]` extra). The symbol
is in `__all__` and importable; importing it without the extra installed
raises the underlying `ImportError`.

### Namespaces with no exports

- `chattice.experimental` — no direct exports by design; its `ai` subpackage is
  an explicitly unstable integration surface.
- `chattice.adapters`, `chattice.transports`, `chattice.integrations` —
  aggregator namespaces with docstring-only bodies.
