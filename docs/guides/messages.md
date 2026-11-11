# Messages and Threads

## Receive and reply

```python
from chattice import Dispatcher, Router
from chattice.events import MessageEvent

router = Router()


@router.message()
async def echo(message: MessageEvent) -> str:
    return f"You said: {message.text}"


dispatcher = Dispatcher()
dispatcher.include_router(router)
```

A returned string is an immediate interaction response. Use
`message.argument_text` when routing Space mentions: Google provides the
mention-stripped body, and Chattice removes its surrounding whitespace. The
raw `message.text` remains unchanged; `None` and an explicitly empty
`argumentText` remain distinct.

```python
@router.message(F.argument_text.regexp(r"^[Rr]eport$"))
async def report(message: MessageEvent) -> str:
    return "Generating report"
```

## Contextual Chat API sends

Bind an authenticated Bot once:

```python
dispatcher = Dispatcher(bot=bot)


@router.message()
async def send_variants(message: MessageEvent) -> str:
    await message.reply("reply or fail if the incoming thread is gone")
    assert message.thread is not None
    await message.thread.send("continue the known thread")
    assert message.space is not None
    await message.space.send("start at the Space top level")
    return "sent"
```

`message.reply()` defaults to the GAPIC
`REPLY_MESSAGE_OR_FAIL` reply option. Generic
`thread.send()` / `space.send()` default to Google's fallback-to-new-thread
behavior unless you pass another GAPIC reply option.

## Imperative send

```python
from google.apps.chat_v1.types import CreateMessageRequest

from chattice.client import Bot
from chattice.events import ThreadRef

await bot.app.messages.create("spaces/AAA", text="top-level")
await bot.app.messages.create(
    "spaces/AAA",
    text="threaded",
    thread=ThreadRef(name="spaces/AAA/threads/T1"),
    reply_option=(CreateMessageRequest.MessageReplyOption.REPLY_MESSAGE_OR_FAIL),
)
```

Use the imperative form in background jobs, Workspace Event handlers, or when
the destination is not the current interaction Space.

## Private message

The canonical private happy path is `bot.app.messages.create(..., private_to=...)`:

```python
await bot.app.messages.create(
    "spaces/AAA",
    text="Only User A and the app can see this",
    private_to="users/user-a",
)
```

Private messages require app authentication. Chattice fails closed when the
viewer is empty or malformed and rejects incompatible accessory widgets before
network I/O. There is no `private_reply` helper.

## Cards, notifications, IDs, and CRUD

`messages.create` also accepts `card=`, `accessory_widgets=`, `notify=`
(`"force"` or `"silent"`), `request_id=`, and `message_id=`. Notification
options and accessory widgets require app auth. Private accessory widgets stay
unsupported because Google's published constraints conflict; use a private
plain-text/card message without accessory widgets.

```python
message = await bot.app.messages.get("spaces/AAA/messages/M1")
await bot.app.messages.update(message.name, text="updated")
await bot.app.messages.delete(message.name)
```

Use request/message IDs for idempotent application workflows; HTTP delivery
can be retried. Read metadata such as `attachments`, `annotations`, `mentions`,
`quote`, reaction summaries, `is_private`, and `is_silent` from
`MessageEvent`. Fields without a curated facade remain available through
`message.raw`.

Google mapping: `spaces.messages.create`, `get`, `update`, and `delete`.

## Markdown, citations, and sources

`markup_syntax` selects how Google reads the message text on `create` and
`update`. Without it Google uses the app-level default from the Chat API
configuration page.

```python
from google.apps.chat_v1.types.citation import Citation
from google.apps.chat_v1.types.cited_source import CitedSource
from google.apps.chat_v1.types.markup_syntax import MarkupSyntax

guide = CitedSource(title="Architecture guide", uri="https://example.com/arch")

await bot.app.messages.create(
    "spaces/AAA",
    text='Deploys are <chat-citation data-id="c1">blue-green</chat-citation>.',
    markup_syntax=MarkupSyntax.MARKUP_SYNTAX_MARKDOWN,
    citations=[Citation(id="c1", cited_sources=[guide])],
    cited_sources=[CitedSource(title="Runbook", uri="https://example.com/runbook")],
)
await bot.app.messages.update(
    "spaces/AAA/messages/M1",
    text="**Deployment complete**",
    markup_syntax=MarkupSyntax.MARKUP_SYNTAX_MARKDOWN,
)
```

`citations` are inline: each one is referenced from the text with a
`<chat-citation data-id="...">` tag and opens a hover card. `cited_sources`
are footer links and need no tag. Both require Markdown markup and an
outbound API call; a synchronous handler return cannot carry them. Chattice
rejects an explicit non-Markdown syntax, a malformed citation id, and
duplicate ids before any network call.

## Pins and search

Pins and message search act for a person, so they live on the USER identity:

```python
pin = await bot.user.message_pins.create("spaces/AAA/messages/M1")
pins = await bot.user.message_pins.list("spaces/AAA")
await bot.user.message_pins.delete("spaces/AAA/messages/M1")  # or pin.name

results = await bot.user.messages.search('report sender.name="users/123"')
async for result in results:
    print(result.message.name)
```

`messages.search` covers every space the user can access. Google leaves out
private messages, messages posted by Chat apps, app direct messages, and muted
spaces; use `messages.list` when you need all messages of one space. Ordering
by `relevance` is a Developer Preview and needs
`Bot(preview_features={PreviewFeature.RELEVANCE_SEARCH_ORDERING})` (or
`enable_preview=True`).

Google mapping: `spaces.messagePins.create`, `list`, `delete`, and
`spaces.messages.search`.

Next: [Native commands](commands.md).

## Privacy model

Four distinct Google surfaces, chosen explicitly by the application:

| Surface | How | Visible to |
| --- | --- | --- |
| Shared Space message | `bot.app.messages.create(space)` | everyone in the Space |
| Thread reply | `bot.app.messages.create(space, thread=...)` or `message.reply()` | everyone with access to the Space; a thread is not a privacy boundary |
| Private message | `bot.app.messages.create(space, private_to=user)` | only `privateMessageViewer` (app auth required; no accessory widgets/attachments) |
| DM | send into the direct-message Space | only you and the app |

Dialogs are a separate synchronous surface: visible only to the opener,
HTTP-only. App Home is the persistent personal surface (HTTP-only).
Nothing is implicitly private and nothing implicitly becomes a Thread —
the application chooses the surface per runtime capabilities.

Local files attach to messages via `attachments=[InputFile(...)]` —
upload requires USER authentication and private messages cannot carry
attachments. See [Files, Images & Media](files-media.md).
