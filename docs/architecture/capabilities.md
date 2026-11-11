# Capabilities

`chattice.capabilities` answers three DIFFERENT questions with three
mechanisms (the matrix keeps these concerns separate):

- `ResponseCapabilities` — what the ingress response channel can do,
  derived from the transport plus the concrete interaction event
  (dialogs, App Home, matched URL, bot/human sender, widget
  autocomplete).
- `OperationRegistry` — which outbound `Bot` operations a given identity
  (app/user) and any reliably known credential scopes may attempt; every
  resource call runs this local preflight before transport.
- `PreviewCapabilities` — which Developer Preview features the application
  explicitly enrolled in, expressed with `PreviewFeature` stability flags;
  this is not an auth capability.

Verified Google facts are sourced from the official Chat API
references (see [Google API mapping](../reference/google-api-mapping.md)).

## Response channel (ingress)

`ResponseCapabilities.resolve(transport="http", event=event)`:

| Capability | HTTP | Pub/Sub | Google fact (verified) |
| --- | --- | --- | --- |
| SYNC_RESPONSE | yes | no | 30-second synchronous interaction response; HTTP-only |
| DIALOGS | only command / `REQUEST_DIALOG` action events | no | dialogs only in response to interactions, visible only to the opener |
| CARD_UPDATE_BOT | CARD_CLICKED with BOT sender | no | `UPDATE_MESSAGE` is bot-only |
| CARD_UPDATE_USER | CARD_CLICKED with HUMAN sender, or MESSAGE with a matched URL | no | `UPDATE_USER_MESSAGE_CARDS` for human-sent cards |
| APP_HOME | APP_HOME / SUBMIT_FORM events | no | RenderActions pushCard + separately configured App Home URL |
| UPDATE_WIDGET | WIDGET_UPDATED (autocomplete) | no | autocomplete responses |

`DIALOGS` is derived with one shared predicate (`can_open_dialog`):
commands always may open dialogs; actions only when Google delivered
them with `REQUEST_DIALOG` metadata; SUBMIT/CANCEL actions cannot
return a new dialog. The HTTP serializer guards with the SAME
predicate, so capability checks and serialization agree on eligible events.

Pub/Sub push and streaming-pull delivery have no synchronous response channel
— both inject an empty `ResponseCapabilities` value and `require()` fails fast
on any response attempt. Apps that must react asynchronously feed a `Bot`
explicitly. HTTP always injects the event-derived value. Thus every supported
ingress supplies the same typed DI key, even when its set is empty.

## Outbound operations (Bot)

Outbound preflight is a **local registry lookup**, not an authorization
guarantee. Every `Operation` has an `OperationSpec` listing its auth paths:
the allowed identity (APP/USER) and, per identity, the admissible OAuth
scopes. `REGISTRY.require(operation, identity=..., scopes=...)` raises
`CapabilityNotSupported` when the configuration cannot even attempt the call;
`REGISTRY.preflight(...)` returns the same answer as a bool. Scope
information is optional: with `scopes=None` the check falls back to the
identity baseline instead of inventing a denial.

| Operation | APP scope (any of) | USER scope (any of) | Google fact (verified) |
| --- | --- | --- | --- |
| `MESSAGES_CREATE` | `chat.bot` | `chat.messages.create`, `chat.messages`, `chat.import` | Chat API `spaces.messages.create` |
| `MESSAGES_UPDATE` | `chat.bot` | `chat.messages`, `chat.import` | Chat API `spaces.messages.update` |
| `MEDIA_UPLOAD` | — (not supported) | `chat.messages.create`, `chat.messages`, `chat.import` | Chat API `media.upload` (user auth only) |
| `MEDIA_DOWNLOAD` | `chat.bot` | `chat.messages.readonly`, `chat.messages` | Chat API `media.download` |
| `ATTACHMENT_METADATA_GET` | `chat.bot` | — (not supported) | Chat API `spaces.messages.attachments.get` (app auth only) |
| `MEMBERSHIPS_CREATE` | `chat.app.memberships` | — (not supported) | Chat API `spaces.members.create`; administrator approval |
| `MEMBERSHIPS_GET` | `chat.bot`, `chat.app.memberships` | — (not supported) | Chat API `spaces.members.get` |
| `MEMBERSHIPS_LIST` | `chat.bot`, `chat.app.memberships` | — (not supported) | Chat API `spaces.members.list` |
| `MEMBERSHIPS_DELETE` | `chat.app.memberships` | — (not supported) | Chat API `spaces.members.delete`; administrator approval |
| `SPACES_LIST` | `chat.bot` | — (not supported) | Chat API `spaces.list`; caller-member Spaces |

When scopes are reliably known, preflight passes when **any** scope in the
identity-specific rule is present. For example, the broader `chat.messages`
user scope supports message creation even when the narrower
`chat.messages.create` scope is absent. A known empty or nonmatching set fails
closed before transport. When scopes are unknown, the identity baseline is
preserved so Chattice does not invent a denial or perform a discovery call.

`Bot` reads scopes locally when credentials are lazily resolved. For user
credentials, available `granted_scopes` takes precedence over the credential's
requested/configured `scopes`; for app credentials, configured explicit/default
scopes are considered. This inspection performs no token-info, Google API, or
other network request.

Configured `chat.app.*` scopes do not prove one-time administrator approval.
Likewise, space membership, resource roles, and resource state remain known
only to Google Chat. A call that passes local preflight can therefore still
receive a server-side 403, surfaced as `ChatPermissionDeniedError`.

Beyond the registry, `Bot` enforces deterministic surface rules before
transport: `private_to` requires APP auth and rejects
accessory-widget combinations, and `notify` is strict-validated and
APP-gated. Cards may be sent with either identity; with the USER identity
Google requires the Chat app to be a member of the space.

## require() guards

Both `ResponseCapabilities` and the operation registry expose `require()`
raising `CapabilityNotSupported` (a `RuntimeError`):

```python
from chattice.auth import AuthMode
from chattice.capabilities import (
    REGISTRY,
    CapabilityNotSupported,
    Operation,
)

try:
    REGISTRY.require(
        Operation.MEDIA_UPLOAD,
        identity=AuthMode.USER,
        scopes={"https://www.googleapis.com/auth/chat.messages"},
    )
except CapabilityNotSupported as error:
    print(error)
```

The message style is operation + actionable hint, so apps can fail with
a useful error instead of a bare permission denial:

```text
MEDIA_UPLOAD is not supported in this configuration. media.upload
requires user authentication.
```

## Pre-transport enforcement contract

Guards run **before Chat API network I/O**. The executor resolves the
(explicit or auto-classified) auth mode and locally available credential
scopes, then runs the registry check before issuing the Chat API request.
No separate authorization or token-introspection request is made. This
contract is pinned by tests that count transport invocations: unsupported
combinations never reach the transport (call counter stays zero),
supported ones do.

## Developer Preview enrollment

Preview capability enrollment is explicit configuration. Message actions,
card replacement, user-authenticated cards, message pins, and customer-level
event subscriptions are generally available and do not require enrollment;
their `PreviewFeature` values remain accepted for compatibility.

Current Developer Preview surfaces:

| `PreviewFeature` | Gates |
| --- | --- |
| `MESSAGE_STREAMING` | `chattice.experimental.streaming` and typed routing of `SYSTEM_COMMAND` to `router.system_command` |
| `THREAD_SESSIONS` | `chattice.experimental.sessions` |
| `RELEVANCE_SEARCH_ORDERING` | `messages.search(order_by="relevance desc")` |

There is one enrollment, `PreviewCapabilities`, configured on the Bot:
`Bot(preview_features={...})` names features, `Bot(enable_preview=True)`
enrolls in all of `DEVELOPER_PREVIEW_FEATURES`. Each gate checks its own
feature and names it in the error. `Dispatcher(bot=bot)` routes preview events
by the same enrollment; `Dispatcher(preview_features={...})` adds to it and
serves a Dispatcher that has no Bot.

Handlers may inject `PreviewCapabilities` to inspect the immutable enrollment.
A caller cannot bypass configuration by passing a replacement value to
`feed_update()`.

## Experimental namespace

Experimental integrations live in `chattice.experimental`; APIs there may
change or disappear without notice. Preview feature flags remain in the stable
capability model because they gate stable parsing/routing boundaries without
making the preview feature itself stable. Stable core never imports the
experimental namespace; a grep-test enforces that dependency direction.

## Define handlers at module level

Handler functions and their annotations must be defined at module level —
importing dependencies inside a handler (or injecting handler-local
classes into annotations) breaks annotation resolution
(`get_type_hints`) and with it the dependency-injection machinery. This
is covered by DI tests: local imports resolve to `None`
types, module-level ones resolve correctly.
