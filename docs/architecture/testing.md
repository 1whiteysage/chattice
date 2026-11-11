# Testing

`chattice.testing` is the framework's testing toolkit: mocks, typed event
builders, and assertions that let you exercise a whole application pipeline
without ever touching raw Google JSON or standing up network transports.
The core engine never imports `testing` — the dependency is one-way.

A CI gate (`tests/testing/test_gate.py`) pins the core contract: an
application handler is tested end-to-end with `MockBot` + `EventFactory`,
with **zero Google internals mocked**.

## Package contents

```text
chattice/testing/
├── MockBot           call-recording stand-in for the outgoing API
├── fake_bot          the real Bot on a FakeChatTransport, in one call
├── EventFactory      typed event builders (no raw Google JSON)
├── FakeChatTransport gapic-contract fake transport
├── assert_card_has_button / assert_card_header
└── set_state_for     FSM seeding helper
```

## Choosing a double

There are two stand-ins for the outgoing client. They answer different
questions, so pick by what the test has to prove.

| The test has to prove | Use |
| --- | --- |
| A handler routes correctly and sends this text or card | `MockBot` |
| A call passes or fails identity preflight (APP or USER) | `fake_bot()` |
| Local validation rejects a call before any request | `fake_bot()` |
| A preview operation is gated by `enable_preview` | `fake_bot()` |
| Anything on memberships, reactions, pins, custom emojis, `users.*`, or space and message listing and search | `fake_bot()` |
| The exact request sent to Google, or a response built from seeded state | `fake_bot()` and its transport |
| A `Bot` you construct yourself, with your own credential providers | `FakeChatTransport` passed as `Bot(transport=...)` |

`MockBot` is a recorder: it mirrors message create, update, card
replacement, get and delete plus `spaces.get`, accepts any arguments, and
checks nothing. `fake_bot()` returns the production `Bot`, so everything the
client does before a request runs for real, and only the network is
replaced. Start with `MockBot` for handler logic; switch to `fake_bot()` as
soon as the result depends on what the real client would do.

## The DI pattern: `feed_update(event, bot=mock_bot)`

Handlers receive dependencies by parameter name. Inject the `MockBot` the
same way a real app injects the `Bot` — via `feed_update` context:

```python
from chattice import Dispatcher, Router
from chattice.events import MessageEvent
from chattice.testing import EventFactory, MockBot

bot = MockBot()
router = Router()


@router.message()
async def echo(message: MessageEvent, bot: MockBot) -> str:
    await bot.app.messages.create(message.space, text=message.text)
    return "handled"


dispatcher = Dispatcher()
dispatcher.include_router(router)
result = await dispatcher.feed_update(EventFactory.message("ping"), bot=bot)
assert result == "handled"
bot.assert_message_sent("ping")
```

## MockBot

`MockBot` records every outgoing call (`send_message`, `update_message`,
`replace_cards`, `delete_message`, `get_message`, `get_space`) with its
arguments in `.calls` and fabricates SDK proto responses — no transport, no
network. Preflight is not modelled: both identity namespaces record
identically, and no argument is validated.

The mirrored surface is fixed: `messages.create`, `messages.update`,
`messages.replace_cards`, `messages.get`, `messages.delete` and `spaces.get`
on `bot.app` and `bot.user`. Any other resource or method raises an
`AttributeError` that names it and points to `fake_bot()`:

```text
MockBot does not model 'bot.app.memberships': it mirrors only
messages.create/update/replace_cards/get/delete and spaces.get. Use
chattice.testing.fake_bot() for a real Bot on FakeChatTransport, which
covers the whole client.
```

The mirrored methods accept every parameter of the real ones.
`tests/testing/test_mock_bot_drift.py` compares the signatures with
`chattice.client.resources.Messages` and `Spaces`, so a parameter added to
the real client fails that test until the mirror accepts it.

Assertions (each fails with an actionable message):

- `assert_message_sent(text: str | None = None, *, count: int = 1)` — the
  outgoing calls, optionally with an exact text and call count.
- `assert_no_messages()` — proves a handler sent nothing.
- `calls` — the raw `(kind, args)` list for advanced checks (e.g. asserting
  on `get_message` reads or `update_message` payloads).

`MockBot` mirrors the real `Bot` facade (`bot.app.messages.*`) —
DI supplies it by parameter name. Tests should exercise the operations used
by the application; importing a handler alone does not validate its calls.

## fake_bot

`fake_bot()` builds the real `Bot` on one in-memory `FakeChatTransport` and
returns both. `bot.app` and `bot.user` each pass preflight for their own
identity and share that transport, so a test seeds state and reads recorded
requests in one place. No credentials or network are involved.

```python
import pytest

from chattice import Dispatcher, Router
from chattice.capabilities import CapabilityNotSupported
from chattice.client import Bot, ChatAPIError
from chattice.events import MessageEvent
from chattice.testing import EventFactory, fake_bot


async def test_handler_reply_reaches_the_api() -> None:
    bot, transport = fake_bot()
    router = Router()

    @router.message()
    async def echo(message: MessageEvent, bot: Bot) -> None:
        await bot.app.messages.create(message.space, text=message.text)

    dispatcher = Dispatcher()
    dispatcher.include_router(router)
    await dispatcher.feed_update(EventFactory.message("ping"), bot=bot)

    assert transport.requests[0].parent == "spaces/test"
    assert transport.requests[0].message.text == "ping"


async def test_invalid_notify_never_reaches_the_api() -> None:
    bot, transport = fake_bot()

    with pytest.raises(ChatAPIError):
        await bot.app.messages.create("spaces/AAA", text="x", notify="loud")

    assert transport.calls == []


async def test_pinning_needs_a_user_identity() -> None:
    bot, transport = fake_bot(user=False)

    with pytest.raises(CapabilityNotSupported):
        await bot.user.message_pins.create("spaces/AAA/messages/m1")

    assert transport.message_pins == {}
```

Options, all keyword-only:

- `user=False` builds a Bot with no USER identity; USER-only operations
  raise `CapabilityNotSupported`.
- `enable_preview=True` opts in to Developer Preview operations, as on
  `Bot`.
- `asset_publisher=...` is passed to the Bot for local card images.

The transport keeps resources in plain dictionaries (`messages`, `spaces`,
`memberships`, `message_pins`, ...) and requests in lists (`requests` for
message creates, `updates`, `membership_creates`, ...). Set
`transport.error` to a `google.api_core` exception to make every call fail
with it; the Bot raises the matching `Chat*Error`.

What it does not cover:

- **Scopes.** The fake credentials carry none, so preflight decides on the
  identity of an operation only.
- **Server rules.** The transport stores and returns what it is given;
  membership, permissions and quotas stay Google's decision.
- **Media bytes and `chattice.experimental` REST calls.** These do not go
  through the GAPIC transport. On a fake Bot they fail before any request
  is sent, with an error that says the fake credentials cannot authorize
  it.

## EventFactory

`EventFactory` builds frozen domain events directly from their typed
constructors — unit tests never paste raw Google JSON:

- `message(text, *, user=None, space=None, thread=None, event_time=None)`
- `action(name, parameters=None, *, form_inputs=None, dialog=None, ...)`
- `added_to_space(...)`, `removed_from_space(...)`, `app_home(...)`,
  `form_submit(function_name, ...)`
- `workspace_event(cloud_type, *, event_id="evt-test", ...)`
- `unknown_event(original_type, ...)`

`user`/`space` accept either a typed reference or a Google resource-name
string (`"users/user-a"`); `None` uses test defaults (`users/test`,
`spaces/test`).

## Card assertions

```python
from chattice.cards import Button, ButtonList, Card, CardHeader, Section
from chattice.testing import assert_card_has_button, assert_card_header

card = Card(
    header=CardHeader(title="Pipeline"),
    sections=[
        Section(
            widgets=[ButtonList(buttons=[Button("Deploy", action="deploy.confirm")])]
        )
    ],
)
assert_card_has_button(card, action="deploy.confirm", text="Deploy")
assert_card_header(card, title="Pipeline")
```

`assert_card_has_button(card, *, action=None, text=None)` and
`assert_card_header(card, *, title=None, subtitle=None)` search the card
and raise with the missing match described.

## FSM seeding

Seed a workflow state for a test with `set_state_for(storage, key, state)`,
then route through the dispatcher as usual:

```python
from chattice.fsm import MemoryStorage, StorageKey, State, StatesGroup
from chattice.testing import set_state_for


class Flow(StatesGroup):
    start = State()
    waiting = State()


storage = MemoryStorage()
key = StorageKey(user="users/test", space="spaces/test", thread=None)
await set_state_for(storage, key, Flow.waiting)  # the StateFilter now matches
```

## Live integration suite

`tests/integration/live` exercises real Google Chat infrastructure and is
**skipped by default** — run it only with real credentials:

```bash
export CHATTICE_GOOGLE_CREDENTIALS=/path/to/service-account.json
export CHATTICE_GOOGLE_SPACE="spaces/SPACE"
pytest tests/integration/live -m google_live
```

Without credentials the suite reports 2 skipped (the network calls) — the
honest, expected state; the three contract tests (card round-trip,
command payloads, Workspace Pub/Sub replay) execute without network.
Setup, in short: a GCP project with the Google Chat API enabled, a
service-account JSON key, a Chat app set to **Live** with its membership
in a test space, and the `CHATTICE_GOOGLE_CREDENTIALS` +
`CHATTICE_GOOGLE_SPACE` env vars. The network bodies call the real API
and nothing fakes success — a green live run always means real
credentials were used.

## Runnable pytest example

```python
# tests/test_echo.py
import pytest

from chattice import Dispatcher, Router
from chattice.events import MessageEvent
from chattice.testing import EventFactory, MockBot


@pytest.fixture
def dispatcher() -> Dispatcher:
    router = Router()

    @router.message()
    async def echo(message: MessageEvent) -> str:
        return f"You said: {message.text}"

    dp = Dispatcher()
    dp.include_router(router)
    return dp


@pytest.fixture
def bot() -> MockBot:
    return MockBot()


@pytest.mark.asyncio
async def test_echo(dispatcher: Dispatcher, bot: MockBot) -> None:
    result = await dispatcher.feed_update(EventFactory.message("ping"), bot=bot)
    assert result == "You said: ping"
    bot.assert_no_messages()
```

Add `pytest-asyncio` to the dev dependencies; `asyncio_mode = "auto"`
is already configured in the project, so the `@pytest.mark.asyncio`
decorator is optional there.
