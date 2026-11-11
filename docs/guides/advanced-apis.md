# Advanced Google Chat APIs

Chattice follows a curated-facade rule (ADR-012): a method enters the stable
high-level API only when Chattice adds real value over the generated SDK —
identity routing, capability preflight, semantic validation, pagination,
error normalization, cards/types integration, or a meaningful helper.
Transparent 1:1 passthrough and niche surface stay on the raw tier, which is
a first-class home, not an apology:

```python
from chattice.client import Bot


async def get_space_raw(bot: Bot) -> object:
    app_client = await bot.raw.app()
    return await app_client.get_space(name="spaces/AAA")


# Or, for operations that need the USER identity:
user_client = await bot.raw.user()
```

`bot.raw.app()` / `bot.raw.user()` are async because credential resolution is
lazy. Method availability, request protos, fields, and behavior follow
`google-apps-chat` and the live Google Chat API rather than the Chattice
stable facade.

## Operation families

| Family | Chattice high-level status | Identity/status note |
| --- | --- | --- |
| Message create/get/update/delete | stable `bot.app.messages` / `bot.user.messages` | explicit identity; app/user support varies by scope |
| Card replacement | stable `bot.app.messages.replace_cards` | APP only; the app must be a space member and own the cards |
| Space get | stable `bot.app.spaces.get` | app must normally have access/membership |
| Space list | stable `bot.app.spaces.list` | APP + `chat.bot`; caller-member Spaces, not organization-wide search |
| Space create/update/delete | stable `bot.app.spaces` / `bot.user.spaces` | APP needs administrator approval; `admin_access=True` on the USER identity; import mode stays raw |
| Space search, group chat lookup | stable `bot.user.spaces.search` / `.find_group_chats` | USER only; `admin_access=True` searches the organization |
| Human user memberships | stable `bot.app.memberships` (create/get/list/delete) | APP, or USER with `admin_access=True`; APP create/delete require admin-approved `chat.app.memberships` |
| Membership role | stable `memberships.update` on either identity | APP only in spaces the app created, with administrator approval |
| Group, external-user, or Chat-app memberships | raw official client where Google supports the case | auth and role constraints vary |
| Message get/list/delete | curated `bot.app.messages` / `bot.user.messages` | explicit identity; list returns a `Pager` |
| Message search | stable `bot.user.messages.search` | USER only; relevance ordering is a Developer Preview |
| Reactions | curated `bot.user.reactions` (create/list/delete) | USER only; reaction-specific scopes |
| Attachments | curated `bot.app.attachments` / `bot.user.attachments` + lossless `MessageEvent.attachments` | upload is USER-only; metadata get is APP-only; download accepts either |
| Pins | stable `bot.user.message_pins` (create/list/delete) | USER only; `chat.spaces.pins*` or `chat.spaces*` |
| Stream messages, thread sessions | `chattice.experimental` | Developer Preview; APP only; see below |
| Read state / thread read state / notification settings | curated `bot.user.users.*` | USER only; `chat.users.readstate*` / `chat.users.spacesettings` |
| Availability | curated `bot.user.users.availability` | USER only; the caller's own presence and custom status |
| Sidebar sections | curated `bot.user.users.sections` | USER only; custom sections and their space items |
| Custom emoji | curated `bot.user.custom_emojis` | USER only; Workspace organizations with custom emojis turned on |
| Import mode | raw official client | admin/domain-wide setup and `chat.import` semantics apply |

Never infer authorization from method presence in the SDK. Check the current
[Google authentication matrix](https://developers.google.com/workspace/chat/authenticate-authorize),
request the narrowest scope, and expect Google to enforce resource permission
after local preflight.

## Presence, sections, and custom emoji

These act for one person, so they live on the USER identity and default to the
caller (`users/me`):

```python
from datetime import timedelta

availability = bot.user.users.availability
await availability.set_custom_status(
    "In a workshop", emoji="📚", ttl=timedelta(hours=2)
)
await availability.mark_do_not_disturb(ttl=timedelta(hours=1))

sections = bot.user.users.sections
section = await sections.create("Projects")
found = await sections.list_items(space="spaces/AAA")
async for item in found:
    await sections.move_item(item.name, target_section=section.name)

image = open("launch.png", "rb").read()
await bot.user.custom_emojis.create(":team-launch:", image, filename="launch.png")
```

- Availability: Google lets a caller read and change only their own state. The
  custom status is at most 64 characters with a Unicode emoji; `ttl` and
  `expire_time` are mutually exclusive.
- Sections: only custom sections can be created, renamed, or deleted, and only
  spaces can be items. `list_items(space=...)` without a section searches all
  sections.
- Custom emoji: the name is `:lowercase-words:`, the image a square PNG, JPG,
  or GIF under 256 KB. `get` and `delete` accept the `:name:` alias.

Google mapping: `users.availability.*`, `users.sections.*`,
`users.sections.items.*`, and `customEmojis.*`.

## Opening a direct chat from a card

Cards render clickable links via the HTML subset (`<a href="...">` in
text widgets), but user mentions (`<users/...>`) exist only in the
message TEXT — they never render inside card widgets. Two supported
ways to point a user at a direct chat:

1. Mention next to the card (the chip opens the direct chat):
   `bot.app.messages.create(space, text="<users/123> See the card", card=card)`.
2. Use the OFFICIAL space URI: a direct-message `Space` returned by
   `find_direct_message` / `get_or_setup_direct_message` carries
   `space_uri` — the URI users can use to access the space. Wrap it in
   a card link or button:

```python
space = await bot.user.spaces.get_or_setup_direct_message("hr@example.com")
card = Card(
    sections=[
        Section(
            widgets=[
                Button(
                    text="Open chat",
                    open_link=space.space_uri,
                ),
                # Or as clickable inline text: card text fields support
                # the HTML subset, including <a href>.
                TextParagraph(
                    text=f'Open the chat: <a href="{space.space_uri}">link</a>'
                ),
            ]
        )
    ]
)
```

`space_uri` is a Google-provided field; no unofficial deep-link formats
are used.

## Incoming webhooks

An incoming webhook is an outbound-only URL for posting into one configured
Space. It cannot receive interactions and does not need Chattice. Use it for a
simple one-way integration; use a full Chat app when you need interactions,
multiple Spaces, app/user identity, cards with actions, dialogs, or Workspace
Events.

## Raw payload discipline

Keep raw calls in a small adapter module, pin the `google-apps-chat` range,
record the required auth/Preview status, and add a fixture or mock-transport
test. When exact unknown field round-trip matters, preserve `event.raw` rather
than assuming the curated event exposes it.

## Per-call request configuration

Every curated resource method accepts an optional
`config=RequestConfig(timeout=..., retry=..., metadata=...)`. `timeout=`
remains as a shorthand; `config=` wins when both are given. A default
`RequestConfig` reproduces raw GAPIC defaults exactly (absent values are
omitted from the GAPIC call):

```python
from chattice.client.config import RequestConfig

space = await bot.user.spaces.find_direct_message(
    "hr@example.com",
    config=RequestConfig(timeout=5.0),
)
```

All curated calls flow through ONE execution path:
resource client -> OperationExecutor -> OperationRegistry preflight ->
explicit APP/USER GAPIC client. Google API errors arrive as the curated
`Chat*Error` family; other exceptions pass through untouched.

## Standard Markdown messages

Use the official enum to select standard Markdown for asynchronous messages:

```python
from google.apps.chat_v1.types.markup_syntax import MarkupSyntax

await bot.app.messages.create(
    "spaces/AAA",
    text="**Deployment complete**",
    markup_syntax=MarkupSyntax.MARKUP_SYNTAX_MARKDOWN,
)
```

Omitting `markup_syntax` uses the app-level default from the Chat API
configuration page. This parameter applies to the message body, not card
widgets or synchronous interaction responses. `messages.update` accepts it
too. Citations and footer sources are covered in
[Messages](messages.md#markdown-citations-and-sources).

## Message streaming (Developer Preview)

A stream shows a progress indicator, incremental text, and intermediate steps
in a thread, then becomes a regular message. The official Python client has no
streaming methods yet, so `chattice.experimental.streaming` calls the REST
endpoints with the Bot's app credentials.

```python
from google.apps.chat_v1.types.markup_syntax import MarkupSyntax

from chattice import Dispatcher, Router
from chattice.client import Bot
from chattice.events import MessageEvent, SystemCommandEvent
from chattice.experimental.streaming import MessageStreams, step, text

router = Router()
bot = Bot(credentials=credentials, enable_preview=True)
streams = MessageStreams(bot)


@router.message()
async def answer(message: MessageEvent) -> None:
    stream = await streams.start(
        message.message,
        progress_text="Thinking...",
        markup_syntax=MarkupSyntax.MARKUP_SYNTAX_MARKDOWN,
    )
    async with stream:
        await stream.append(step("Search", "Found 3 articles."))
        async for token in generate(message.text):
            await stream.append(text(token))


@router.system_command()
async def stopped(event: SystemCommandEvent) -> None:
    if event.cancel_stream is not None:
        await stop_generation(event.cancel_stream)


# The Dispatcher routes preview events by the enrollment of its Bot.
dispatcher = Dispatcher(bot=bot)
dispatcher.include_router(router)
```

- Leaving the `async with` block commits the stream; an exception discards
  it. `commit()` and `discard()` can also be called directly.
- `append` concatenates text and adds steps and citations. `replace` swaps
  the streamed content or the progress text in place.
- `commit` also accepts the commit-only chunks: `card(...)`,
  `accessory_widget(...)`, `cited_source(...)`. It returns the final message
  as REST JSON.
- Requests on one stream must be sequential: every response carries the token
  for the next request.
- When the person presses Stop, Google sends `SYSTEM_COMMAND`. It reaches
  `router.system_command` only after the `MESSAGE_STREAMING` opt-in;
  `event.cancel_stream` is the stream's resource name. Commit the partial
  output or discard the stream, then return nothing.

Google's limits: app authentication only; the referenced message must be in a
threaded space or a 1:1 direct message that already contains a message; an
active stream times out 5 minutes after creation; streaming is visible only in
Chat on the web for now.

## Thread sessions (Developer Preview)

With "Enable Agentic features" turned on in the Chat API configuration,
Google organizes a 1:1 direct message with the app into separate thread-based
sessions. `chattice.experimental.sessions` reads them and sets their title and
icon:

```python
from chattice.experimental.sessions import ThreadSessions

sessions = ThreadSessions(bot)
await sessions.update(message.thread, title="Quarterly report", icon="bar_chart")
async for session in await sessions.list(message.space):
    print(session.name, session.title)
```

App authentication only, 1:1 app direct messages only. Both experimental
modules require preview enrollment on the Bot (`enable_preview=True`, or
`preview_features={PreviewFeature.MESSAGE_STREAMING, PreviewFeature.THREAD_SESSIONS}`)
and a Google Cloud project enrolled in the Developer Preview Program, and can
change before 1.0. They are checked against Google only by the live tests in
`tests/integration/live`.
