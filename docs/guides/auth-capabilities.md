# Authentication and capabilities

Capabilities are local, typed preflight checks. They improve error messages and
prevent deterministic invalid requests; they do not replace Google's
authorization decision.

## Three capability sets

- `ResponseCapabilities`: what this transport and concrete event can return.
- `OperationRegistry`: which outbound operations this credential identity and
  known scopes may attempt through `Bot`.
- `PreviewCapabilities`: which Developer Preview routes the application has
  explicitly enabled.

## Scope-aware outbound preflight

For message creation, app auth accepts `chat.bot`; user auth accepts **any of**
`chat.messages.create`, `chat.messages`, or `chat.import`. For updates, user
auth accepts either `chat.messages` or `chat.import`.

The three media operations follow the same tri-state model:

| Operation | App auth | User auth | Admissible scopes |
| --- | --- | --- | --- |
| `MEDIA_UPLOAD` (`media.upload`) | no | yes | user: `chat.messages.create` / `chat.messages` / `chat.import` |
| `MEDIA_DOWNLOAD` (`media.download`) | yes | yes | app: `chat.bot`; user: `chat.messages.readonly` / `chat.messages` |
| `ATTACHMENT_METADATA_GET` (`spaces.messages.attachments.get`) | yes | no | app: `chat.bot` |

Memberships and Space listing are deliberately APP-only:

| Operation | App auth | User auth | Admissible scopes |
| --- | --- | --- | --- |
| `MEMBERSHIPS_CREATE` | yes | no | app: `chat.app.memberships` + Workspace administrator approval |
| `MEMBERSHIPS_GET` | yes | no | app: `chat.bot` / `chat.app.memberships` |
| `MEMBERSHIPS_LIST` | yes | no | app: `chat.bot` / `chat.app.memberships` |
| `MEMBERSHIPS_DELETE` | yes | no | app: `chat.app.memberships` + Workspace administrator approval |
| `SPACES_LIST` | yes | no | app: `chat.bot` |

The corresponding registry auth paths never include USER credentials. See
[Memberships and Spaces](memberships-spaces.md).

A dual-identity Bot resolves these against the identity the operation
needs: `bot.user.attachments.upload` runs on the USER identity, and
`attachments=[InputFile(...)]` sends use the USER identity for the
**whole operation** — `media.upload` AND the final `messages.create`
run on the USER client (an APP-authenticated create cannot consume a
USER-uploaded attachment; the cross-identity handoff is rejected by
Google). `bot.app.attachments.get_metadata` uses the APP identity,
`attachments.download` accepts either. See
[Files, Images & Media](files-media.md).

`scopes=None` means **unknown**, not empty. Chattice preserves the identity
baseline and lets the server decide; it performs no hidden discovery or token
introspection call. An explicit empty iterable means reliably known absence and
fails locally.

```python
from chattice.auth import AuthMode
from chattice.capabilities import REGISTRY, CapabilityNotSupported, Operation

try:
    REGISTRY.require(
        Operation.MESSAGES_CREATE,
        identity=AuthMode.USER,
        scopes={"https://www.googleapis.com/auth/chat.messages"},
    )
except CapabilityNotSupported:
    ...  # configuration cannot even attempt the call
```

Passing preflight is not an authorization guarantee. Google can still return
403 because of missing consent/admin approval, Space membership, resource
role, policy, or resource state. Chattice surfaces this as
`ChatPermissionDeniedError`.

## 401 vs 403 vs capability errors

| Error | Meaning | First check |
| --- | --- | --- |
| Incoming HTTP 401 | request verification failed | exact audience, bearer token, Google identity, clock/network |
| `ChatUnauthenticatedError` | outbound credential was rejected | key/token validity and refresh |
| `CapabilityNotSupported` | configuration is deterministically unsupported | auth mode, known scopes, transport/event, Preview opt-in |
| `ChatPermissionDeniedError` | Google authenticated the call but denied it | scope grant, app membership, role, admin approval, feature enrollment |

## User auth: REQUEST_CONFIG response

When a user-auth application receives an interaction without a stored OAuth
token (or with an expired grant it cannot refresh), the documented Google
answer is a synchronous `REQUEST_CONFIG` response carrying an authorization
URL. The OAuth authorization flow itself belongs to the application.

```python
from chattice.transports.http import RequestConfigResponse


@router.message()
async def needs_auth(message: MessageEvent) -> RequestConfigResponse:
    return RequestConfigResponse(
        auth_url="https://accounts.google.com/o/oauth2/v2/auth?..."
    )
```

Google drives the user through `authUrl`; the application then completes the
code exchange, stores the resulting credentials, and returns them through a
`UserCredentialsProvider` (see [Files, Images & Media](files-media.md)).

## Preview opt-in

One enrollment covers both directions: outbound preview calls on the Bot and
typed routing of preview events in the Dispatcher that owns it.

```python
from chattice import Dispatcher
from chattice.capabilities import PreviewFeature
from chattice.client import Bot

bot = Bot(
    credentials=credentials,
    preview_features={
        PreviewFeature.MESSAGE_STREAMING,
        PreviewFeature.THREAD_SESSIONS,
    },
)
dispatcher = Dispatcher(bot=bot)
```

`Bot(enable_preview=True)` enrolls in every feature that is in Developer
Preview. A Dispatcher without a Bot takes the same set directly:
`Dispatcher(preview_features={...})`.

`MESSAGE_ACTION`, `REPLACE_CARDS`, `USER_AUTH_CARDS`, `PINNED_MESSAGES`, and
`CUSTOMER_LEVEL_SUBSCRIPTIONS` are generally available at Google and need no
enrollment; the enum values remain accepted for compatibility.

Enrollment in Chattice is only an explicit application decision. The Google
account must separately be eligible/enrolled and have the required identity,
scopes, and resource permissions.

Next: [Recipes](../cookbook/recipes.md).

## Preview gating

Operations marked `preview=True` in the operation registry require an
explicit per-Bot opt-in:

```python
bot = Bot(..., enable_preview=True)
```

Without it the executor rejects the call with `CapabilityNotSupported`
naming the operation. Stable operations are always available.
