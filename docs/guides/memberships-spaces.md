# Memberships and Spaces

`Bot` exposes the Google Chat membership primitives needed to add, inspect,
list, and remove human users. It also lists the Spaces visible to the
Chat app. Business concepts such as departments or groups of Spaces remain in
the application.

## Configure APP authentication

Membership mutation is an APP-auth operation. Configure the service account
with both `chat.bot` and `chat.app.memberships` when the same Bot also sends
messages and lists Spaces:

```python
from chattice.auth import (
    CHAT_APP_MEMBERSHIPS_SCOPE,
    CHAT_BOT_SCOPE,
    ServiceAccountCredentialsProvider,
)
from chattice.client import Bot

provider = ServiceAccountCredentialsProvider.from_service_account_file(
    "/run/secrets/chat-service-account.json",
    scopes=[CHAT_BOT_SCOPE, CHAT_APP_MEMBERSHIPS_SCOPE],
)
bot = Bot(credentials_provider=provider)
```

`chat.app.memberships` requires one-time approval from a Google Workspace
administrator. Google currently marks
[create](https://developers.google.com/workspace/chat/api/reference/rest/v1/spaces.members/create)
and [delete](https://developers.google.com/workspace/chat/api/reference/rest/v1/spaces.members/delete)
with app authentication as Developer Preview. Declaring the scope in code does
not grant approval or enroll an account. Membership operations never select
the Bot's USER identity and do not reuse attachment/OAuth credentials.

App authentication can create or remove memberships for human users.
It cannot use these helpers to add external users, Google Groups, or other Chat
apps. Google can also reject removal of a Space manager unless the Chat app
created the Space.

## Add and inspect a member

Bare Space IDs and canonical resource names are both accepted. A user can be
passed as a canonical `users/...` resource name:

```python
membership = await bot.app.memberships.create(
    "spaces/AAA",
    user="users/123",
)

same_membership = await bot.app.memberships.get(
    "spaces/AAA/members/users/123",
)
```

The returned value is Google's `Membership` proto. Chattice does not hide its
state, role, invitation state, or future SDK fields.

## List memberships

`memberships.list()` returns a `Pager`; iterate it with `async for` (pages
are fetched as you go) or `collect()` for one list. `filter` is
passed to Google unchanged; Chattice does not invent a filtering DSL.

```python
pager = await bot.app.memberships.list(
    parent="spaces/AAA",
    filter='member.type = "HUMAN" AND role = "ROLE_MEMBER"',
)
async for membership in pager:
    ...
```

Membership get/list use APP authentication and accept either `chat.bot` or
`chat.app.memberships`. Create/delete require `chat.app.memberships`.

## Remove directly by user resource name

No preliminary list or get is required:

```python
removed = await bot.app.memberships.delete(
    "spaces/AAA/members/users/123",
)
```

`memberships.delete()` is not silently idempotent. If the membership does not
exist, Chattice raises `ChatNotFoundError` through the normal Chat API error
policy. Application code may choose to treat that as a skip for a bulk job.

## List Spaces and perform a bulk removal

`spaces.list()` uses APP authentication with `chat.bot` and yields (a
`Pager`) the Spaces in which the calling Chat app is a member. It does not use
`spaces.search()`, which also supports searching the calling user's spaces
without administrator privileges. Use the raw SDK for search.

```python
from chattice.client import (
    ChatAlreadyExistsError,
    ChatAPIError,
    ChatNotFoundError,
)

spaces = await bot.app.spaces.list(filter='spaceType = "SPACE"')

failures = []
async for space in spaces:
    try:
        await bot.app.memberships.delete(f"{space.name}/members/users/123")
    except ChatNotFoundError:
        continue
    except ChatAPIError as error:
        failures.append((space.name, error))
```

All membership and Space-list methods wrap Google SDK failures in the
`ChatAPIError` hierarchy. Catch `ChatNotFoundError` when a membership is
absent and `ChatAlreadyExistsError` when an add operation reports HTTP 409;
permission, validation, rate-limit, authentication, and service failures
have their corresponding typed subclasses. Each wrapper preserves the SDK
exception as `error.__cause__` and exposes its `code` and `details` values.

The hierarchy is:

```text
ChatAPIError
├── ChatNotFoundError
├── ChatAlreadyExistsError
├── ChatPermissionDeniedError
├── ChatInvalidArgumentError
├── ChatRateLimitError
├── ChatServiceUnavailableError
└── ChatUnauthenticatedError
```

```python
try:
    await bot.app.memberships.create("spaces/AAA", user="users/123")
except ChatAlreadyExistsError:
    pass  # application policy: the desired membership is already present
except ChatNotFoundError:
    pass  # application policy: the Space was removed or is not visible
```

Google doesn't list empty group chats and direct messages until their first
message. Filtering for `spaceType = "SPACE"` is the intended way to restrict a
bulk operation to named Spaces visible to the app.

Mappings such as `"sales" -> ["spaces/A", "spaces/B"]`, retries, concurrency,
already-member handling, and result summaries belong to application code.

## Search, group chats, and space management

```python
from google.apps.chat_v1.types import Space
from google.apps.chat_v1.types.membership import Membership

spaces = await bot.user.spaces.search('display_name:"Launch"')
chats = await bot.user.spaces.find_group_chats(["users/123", "users/456"])

space = await bot.user.spaces.create(
    Space(space_type=Space.SpaceType.SPACE, display_name="Launch"),
    request_id="launch-space-1",
)
space.display_name = "Launch 2027"
await bot.user.spaces.update(space, update_mask=["display_name"])
await bot.user.memberships.update(
    f"{space.name}/members/123", role=Membership.MembershipRole.ROLE_MANAGER
)
await bot.user.spaces.delete(space.name)
```

- `spaces.search` returns spaces the calling user has joined. With
  `admin_access=True` it searches the whole organization (see
  [Administrator access](#administrator-access)).
- `spaces.find_group_chats` takes the other human members and returns the
  group chats whose members are exactly those users and the caller.
- `spaces.create` and `spaces.update` take the official `Space`. With the APP
  identity, creation needs Workspace administrator approval and
  `space.customer`; Chattice rejects a missing customer locally.
- `spaces.update` sends exactly the field paths in `update_mask`. To change
  who can view the member list, Google requires both
  `access_settings.access_permission_settings.viewSpaceMembershipSetting`
  and `permission_settings.viewSpaceMembership` in one request.
- `spaces.delete` always cascades: the messages and memberships of the space
  are deleted with it.
- `memberships.update` changes the role, the only field Google lets a caller
  update.

Google mapping: `spaces.search`, `spaces.findGroupChats`, `spaces.create`,
`spaces.patch`, `spaces.delete`, and `spaces.members.patch`.

## Administrator access

A Google Workspace administrator can manage spaces they are not a member of.
Pass `admin_access=True` on the USER identity; the credentials need the
matching `chat.admin.*` scope.

```python
found = await bot.user.spaces.search(
    'customer = "customers/my_customer" AND space_type = "SPACE"',
    admin_access=True,
)
async for space in found:
    members = await bot.user.memberships.list(parent=space.name, admin_access=True)
    print(space.display_name, len(await members.collect()))
```

| Method | Scope (any one) |
| --- | --- |
| `spaces.get`, `spaces.search` | `chat.admin.spaces`, `chat.admin.spaces.readonly` |
| `spaces.update` | `chat.admin.spaces` |
| `spaces.delete` | `chat.admin.delete` |
| `memberships.get`, `memberships.list` | `chat.admin.memberships`, `chat.admin.memberships.readonly` |
| `memberships.create`, `memberships.update`, `memberships.delete` | `chat.admin.memberships` |

A call without an admin scope, or on `bot.app`, fails locally with
`CapabilityNotSupported` before any request. Google decides whether the user
holds the administrator privilege, and limits what administrator access can do
(for example, it cannot add a Chat app to a space).
