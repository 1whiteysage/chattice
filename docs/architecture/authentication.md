# Authentication

Credential providers authorize a Chat app's Chat API calls. Incoming
verification is a separate concern with a
separate interface — see [ADR-005](../adr/ADR-005-authentication-abstraction.md)
and the verified Google auth facts.

## Three separated modes

Authentication has three separate responsibilities:

| Mode | Proves / authorizes | Where it lives |
| --- | --- | --- |
| Incoming verification | A delivery really came from Google Chat (HTTP 401 semantics) | `chattice.transports.http.GoogleTokenVerifier` / `MockVerifier` |
| App credentials | A Chat app acting as itself on the Chat API | `chattice.auth.ServiceAccountCredentialsProvider` |
| User credentials | Acting on behalf of a consenting user | `chattice.auth.UserCredentialsProvider` |

Synchronous interaction responses and App Home render actions need no
outgoing identity at all; no Bot is needed for them. Incoming verification
still runs. The webhook derives response capabilities from the concrete event:
SYNC_RESPONSE plus dialog, card-update, App Home, or autocomplete support when
the event allows it.

## App authentication

`ServiceAccountCredentialsProvider` produces the `google-auth` credentials the
Bot uses for app-authenticated calls. The JSON file (or info mapping) is **not
read at construction** — loading happens only when the provider is first
called, i.e. at lazy client creation:

```python
from chattice.auth import ServiceAccountCredentialsProvider

# File-based; the file is read lazily on the first call.
provider = ServiceAccountCredentialsProvider.from_service_account_file(
    "credentials.json",
)

# In-memory; handy for secret managers or tests. `info` is copied at
# construction, so callers can mutate their mapping afterwards.
provider = ServiceAccountCredentialsProvider.from_service_account_info(
    {"type": "service_account", "client_email": "...", "private_key": "..."}
)

# Or hand over an already-built google-auth credentials object directly.
provider = ServiceAccountCredentialsProvider(credentials=already_built)
```

The default scope is `CHAT_BOT_SCOPE` (`https://www.googleapis.com/auth/chat.bot`).
It needs no admin approval and lets the app act as itself on resources it can
access — the app must be a member of the space to act. Newer `chat.app.*`
scopes (`chat.app.messages`, `chat.app.spaces`, ...) require a **one-time
administrator approval** and are not a drop-in substitute; when you need one,
pass it explicitly:

```python
provider = ServiceAccountCredentialsProvider.from_service_account_file(
    "credentials.json",
    scopes=["https://www.googleapis.com/auth/chat.app.messages"],
)
```

## User authentication

`UserCredentialsProvider` wraps google-auth authorized-user credentials —
either a pre-built `Credentials` object or a token-info mapping. It is the
provider for `AuthMode.USER`:

```python
from chattice.auth import UserCredentialsProvider

# From a token-info mapping (app-owned storage), or pre-built credentials.
provider = UserCredentialsProvider(token_info)
```

The provider refreshes **only when the credentials are expired**; a valid
token is passed through untouched.

### Domain-wide delegation is USER

Domain-wide delegation (a service account with an impersonated `subject=`)
acts as a user and is therefore `AuthMode.USER`. The operation registry
applies the USER auth paths to both OAuth-user credentials and DWD.

`DelegatedUserCredentialsProvider` packages this: it wraps any
`CredentialsProvider` and returns `credentials.with_subject(subject)`:

```python
from chattice.auth import DelegatedUserCredentialsProvider

user_provider = DelegatedUserCredentialsProvider.from_service_account_file(
    "/run/secrets/chat-service-account.json",
    subject="user@example.com",
)
```

One service-account JSON therefore serves both identities of a
dual-identity Bot (see [bot-api-client](bot-api-client.md)): the plain
provider for APP auth, the delegated provider for USER auth. Requires
Workspace admin configuration of the delegation and scopes.

### useAdminAccess

`useAdminAccess` is Google's separate administrator mode with its own
per-method scope requirements. The nine methods that document it accept
`admin_access=True` on the USER identity (`bot.user.spaces.get/search/
update/delete`, `bot.user.memberships.create/get/list/update/delete`). The
registry models it as the `ADMIN` execution variant: preflight then requires a
`chat.admin.*` scope and the request carries `use_admin_access`. Whether the
user really is a Workspace administrator stays with Google.

## Refresh contract

- The Bot resolves each configured identity provider at lazy client creation
  and caches a successful result. Provider failures can be retried; the SDK
  receives the resolved credentials rather than the provider.
- After that, token refreshes are handled **inside the SDK** (google-auth
  refreshes transparently during gRPC calls); the application must not keep
  re-invoking the provider.
- `UserCredentialsProvider` with `refresh_before_call=True` (the default)
  performs one synchronous refresh at that single call when the token has
  expired — so the client is always constructed with valid credentials.

## Token storage is application-owned

The framework stores nothing. Token acquisition (OAuth consent flow, client
ID per platform) and persistence (refresh/revocation) belong entirely to the
application: the provider contract is a plain callable returning valid
credentials, and the application decides where tokens live and how they are
refreshed or revoked. Never put service-account JSON, access/refresh tokens,
or authorization headers in reprs, logs, metrics, or exception messages.
