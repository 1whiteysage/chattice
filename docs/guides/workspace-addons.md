# Chat apps built as Google Workspace add-ons

Google offers two ways to connect an HTTP Chat app. They carry the same
interactions in different JSON, and the Google Cloud console setting decides
which one your endpoint receives:

| Configuration | Google sends | Your app answers with |
| --- | --- | --- |
| Chat API interaction events | `{"type": "MESSAGE", ...}` | a `Message`, optionally with `actionResponse` |
| Google Workspace add-on | `{"chat": {"messagePayload": {...}}, ...}` | an action: `hostAppDataAction`, `action.navigations`, ... |

Chattice accepts both on the same route and gives handlers the same events.
Handlers return the same values; the response is written in the family the
event arrived in.

!!! warning "Not yet verified against a live add-on deployment"
    This support was written from Google's published add-on documentation
    and is covered by fixtures built from it. It has not been exercised
    against a real add-on configured Chat app. Two details are inferred
    because the HTTP documentation does not show them: the event a homepage
    card click produces, and the content of `invokedFunction` for an action
    addressed by URL. See
    [ADR-014](../adr/ADR-014-workspace-addon-payload-family.md).

## Setup

An add-on differs from a Chat API app in three places: who signs the request,
how a card button finds your endpoint, and the response JSON. The first two
need configuration; the third is automatic.

```python
from fastapi import FastAPI

from chattice import Dispatcher, Router
from chattice.client import Bot
from chattice.integrations.fastapi import create_chat_router
from chattice.transports.http import AddOnTokenVerifier

ENDPOINT = "https://bot.example.com/chat"

bot = Bot(credentials=credentials, addon_action_url=ENDPOINT)
router = Router()
dispatcher = Dispatcher(bot=bot)
dispatcher.include_router(router)

app = FastAPI()
app.include_router(
    create_chat_router(
        dispatcher,
        AddOnTokenVerifier(
            audience=ENDPOINT,
            service_account_email=(
                "service-123@gcp-sa-gsuiteaddons.iam.gserviceaccount.com"
            ),
        ),
        path="/chat",
        addon_action_url=ENDPOINT,
    )
)
```

- **`AddOnTokenVerifier`** — Google signs add-on requests with the add-on's
  own service account, not the Google Chat service account that
  `GoogleTokenVerifier` expects. Copy the email from the Google Cloud console
  (Google Workspace Marketplace SDK → HTTP Deployments → Service Account
  Email). `audience` is the HTTPS URL configured for the app.
- **`addon_action_url`** — the public HTTPS URL of the route. Pass it to the
  route (for cards returned from handlers) and to the `Bot` (for cards sent
  with `bot.app.messages.create/update/replace_cards`).

## Card actions

In an HTTP add-on a button does not name a function: its `function` must be the
URL Google calls. Chattice keeps `@router.action("name")` working by *binding*
the card when it is sent:

```python
from chattice.cards import Button, ButtonList, Card, Section
from chattice.events import ActionEvent, MessageEvent


@router.message()
async def show(message: MessageEvent) -> Card:
    return Card(
        sections=[
            Section(
                widgets=[
                    ButtonList(
                        buttons=[
                            Button(
                                "Assign",
                                action="case.assign",
                                parameters={"case_id": "42"},
                            )
                        ]
                    )
                ]
            )
        ]
    )


@router.action("case.assign")
async def assign(event: ActionEvent) -> str:
    return f"Assigned case {event.parameters['case_id']}"
```

On the wire the button becomes `function: "https://bot.example.com/chat"` with
an extra parameter `chattice_function: "case.assign"`. When the click arrives,
the handler name is restored and the reserved parameter is removed, so
`event.parameters` holds only `case_id`.

- Binding happens only when `addon_action_url` is configured and only for
  typed results (`Card`, `Dialog`, accessory widgets). A `dict` or
  `RawInteractionResponse` is sent as written.
- An action whose `function` is already a URL is left alone.
- `chattice_function` is reserved; using it as your own parameter raises
  `ValueError`.
- To bind a card yourself, for example before storing it:
  `chattice.cards.addon.bind_addon_actions(card, ENDPOINT)`.
- A click on a card that was not bound still reaches handlers as an
  `ActionEvent` with an empty `name`; route it with a filter on
  `event.parameters`.

## What a handler result becomes

| Handler returns | For event | Add-on response |
| --- | --- | --- |
| `str` | any | `createMessageAction` with the text |
| `Card` | message, command, added to space | `createMessageAction` with the card |
| `Card` | message with a matched URL | `updateInlinePreviewAction` |
| `Card` | click on an app message | `updateMessageAction` |
| `Card` | click on a link preview of a user's message | `updateInlinePreviewAction` |
| `Card` | App Home opened | `action.navigations: pushCard` |
| `Card` | homepage card interaction | `action.navigations: updateCard` |
| `Dialog` | command, or click with `REQUEST_DIALOG` | `action.navigations: pushCard` |
| `ActionStatus` | click with `SUBMIT_DIALOG` | closes the dialog; the message becomes a notification |
| `WidgetAutocomplete` | widget updated | `action.modifyOperations` with suggestions |
| `RequestConfigResponse` | any | `basic_authorization_prompt` |

Differences from the Chat API family that affect behavior:

- **`ActionStatus`** — the add-on family has no in-dialog error state. Both
  `ActionStatus.ok()` and `ActionStatus.invalid("...")` close the dialog; the
  message is shown as a notification. To keep a dialog open with an error,
  return a `dict` with the navigation you need.
- **`RequestConfigResponse`** needs `resource=`, the display name of the
  service the user connects:
  `RequestConfigResponse(auth_url=url, resource="Example Account")`.
- **`WidgetAutocomplete`** — each suggestion's text is also its submitted
  value, and `widget_id` is not sent.

## Events

| Add-on trigger | Handler |
| --- | --- |
| `messagePayload` | `@router.message()` |
| `appCommandPayload` (slash and quick commands) | `@router.command()`, `@router.slash_command()`, `@router.quick_command()` |
| `buttonClickedPayload` | `@router.action("name")` |
| `widgetUpdatedPayload` | `@router.widget_updated()` |
| `addedToSpacePayload` / `removedFromSpacePayload` | `@router.added_to_space()` / `@router.removed_from_space()` |
| App Home (no payload) | `@router.app_home()`; `event.space` is `None` |
| `systemCommandPayload` (Developer Preview) | `@router.system_command()` |

`event.wire_format` is `WireFormat.ADDON` for these events, and `event.raw`
holds the original event object, including `authorizationEventObject`. Treat
`raw` as sensitive: it can contain the user's OAuth and ID tokens.

## Testing

`EventFactory` builds Chat API family events. To test an add-on response, mark
the event and serialize the handler result:

```python
from dataclasses import replace

from chattice.events import WireFormat
from chattice.testing import EventFactory
from chattice.transports.http import serialize_response

event = replace(EventFactory.message("ping"), wire_format=WireFormat.ADDON)
body = serialize_response("pong", event=event)
assert body == {
    "hostAppDataAction": {
        "chatDataAction": {"createMessageAction": {"message": {"text": "pong"}}}
    }
}
```
