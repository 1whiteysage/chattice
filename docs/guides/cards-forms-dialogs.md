# Cards, Actions, Forms, Dialogs, and App Home

## Build a card and route a button

```python
from chattice import Router
from chattice.cards import Button, ButtonList, Card, Section, TextParagraph
from chattice.events import ActionEvent

card = Card(
    sections=[
        Section(
            widgets=[
                TextParagraph("Deploy production?"),
                ButtonList(
                    buttons=[
                        Button(
                            "Deploy",
                            action="deploy.confirm",
                            parameters={"env": "prod"},
                        )
                    ]
                ),
            ]
        )
    ]
)

router = Router()


@router.action("deploy.confirm")
async def confirm(event: ActionEvent) -> str:
    return f"Deploying {event.parameters['env']}"
```

`Button` maps to a Google Cards v2 button; its function and string parameters
become a normalized `ActionEvent`. For structured parameters, subclass
`ActionData` and register `YourData.filter()` instead of decoding dictionaries
throughout the application.

`@router.action("deploy.confirm")` is shorthand for
`@router.action(F.name == "deploy.confirm")`. The action name is the value
carried by the button's `action=`. Button `parameters` are exposed as
`event.parameters`; they are separate from form values in
`event.form_inputs`:

```python
from chattice import F
from chattice.cards import Button, TextInput

TextInput(name="email", label="Email")
Button(
    "Continue",
    action="deploy.confirm",
    parameters={"email": "person@example.com", "group": "kk"},
)
```

The `email` entered into the `TextInput` is read from
`event.form_inputs["email"]`. The explicit button values are read from
`event.parameters["email"]` and `event.parameters["group"]`.

Returning a `Card` from an action handler sends a new message for ordinary
actions. In the pull Pub/Sub transport, when the action came from a known bot
message, the same returned Card updates that message. Returning a `str`
sends a text message. The handler may construct the Card inline or assign it
to a local variable first; both forms have identical behavior.

## Hosted images

`Image` renders an HTTPS-hosted picture inside a card:

```python
from chattice.cards import Card, Image, Section

card = Card(
    sections=[
        Section(
            widgets=[
                Image(
                    image_url="https://example.com/result.png",
                    alt_text="Result",
                )
            ]
        )
    ]
)
```

Card Images are URL-only: `image_url` must be an absolute HTTPS URL —
local paths, bytes and `data:` URLs are rejected at construction.
`on_click` reuses the existing `Action` / `OpenLink` facades. A **local**
file is not a Card Image — it is an attachment, see
[Files, Images & Media](files-media.md).

## Forms and typed models

Form widgets include `TextInput`, `SelectionInput`, and `DateTimePicker`.
`Validation` configures supported client-side limits/types. Submitted
`common.formInputs` is already normalized into `StringInput`, `DateInput`,
`DateTimeInput`, `TimeInput`, or `UnknownFormInput`.

```python
from dataclasses import dataclass

from chattice.cards import ActionStatus
from chattice.events import ActionEvent, StringInput
from chattice.forms import FormModel


@dataclass
class ContactForm(FormModel):
    email: StringInput


@router.dialog_submit(ContactForm.filter())
async def save_contact(event: ActionEvent, form: ContactForm) -> ActionStatus:
    if not form.email.values:
        return ActionStatus.invalid("Email is required")
    return ActionStatus.ok(f"Saved {form.email.values[0]}")
```

Forms collect one interaction's data. FSM stores workflow state that must
survive messages, callbacks, time, users, or restarts. A form is not an FSM.

## Open a dialog

The button must declare `OPEN_DIALOG`, and the eligible `REQUEST_DIALOG`
action returns a `Dialog` synchronously:

```python
from chattice.cards import ButtonInteraction, Dialog, TextInput

open_button = Button(
    "Contact",
    action="contact.open",
    interaction=ButtonInteraction.OPEN_DIALOG,
)


@router.action("contact.open")
async def open_contact(event: ActionEvent) -> Dialog:
    return Dialog(
        body=Card(sections=[Section(widgets=[TextInput(name="email", label="Email")])])
    )
```

Dialogs are visible only to the user who opened them. They are HTTP-only
synchronous primitives; Pub/Sub has no channel on which to return a dialog.
`DateTimePicker` is rejected inside a dialog because Google does not support it
there.

`@router.dialog_cancel()` handles cancellation. A submit returns
`ActionStatus.ok()` to close or `ActionStatus.invalid()` to keep the dialog
open with a user-facing error.

## App Home

```python
from chattice.events import AppHomeEvent, FormSubmitEvent


@router.app_home()
async def home(event: AppHomeEvent) -> Card:
    return Card(sections=[Section(widgets=[TextParagraph("Welcome")])])


@router.form_submit()
async def update_home(event: FormSubmitEvent) -> Card:
    return Card(sections=[Section(widgets=[TextParagraph("Saved")])])
```

The HTTP serializer maps these to Google's `pushCard` and `updateCard`
navigation actions. App Home is a private surface hosted by the app's direct
message Space; it is not a public Space publishing target.

## Updating and escaping

Returning a `Card` from a card-click HTTP handler selects Google's
sender-sensitive update response. Use `bot.app.messages.update(name, card=...)`
for an authenticated asynchronous update. Unsupported widget kinds can be
carried by `RawWidget`; exact unsupported API methods remain available through
`bot.raw.app()` / `bot.raw.user()`.

Next: [Routing and state](routing-state.md).

## Typed ActionData

Bind typed dataclasses to button parameters without packed callback
strings. The action function name is the discriminator; parameters are
flat strings:

```python
from dataclasses import dataclass

from chattice.actions import ActionData
from chattice.cards import Button


@dataclass
class Deploy(ActionData, function="deploy"):
    environment: str
    version: str


@router.action("deploy", Deploy.filter())
async def deploy(event: ActionEvent, data: Deploy) -> str:
    return f"Deploying {data.version} to {data.environment}"


Button("Deploy", action=Deploy(environment="prod", version="1.2.3"))
```

If the incoming parameters cannot decode into the model, the filter does
not match — enable the `chattice.actions` logger at DEBUG level to see
the reason (see [Troubleshooting](../troubleshooting.md)).

## Cards on user messages and asynchronous updates

A card can be sent with either identity. With the USER identity the person is
the sender and Google attributes the card to the app:

```python
sent = await bot.user.messages.create("spaces/AAA", text="Status", card=card)
await bot.app.messages.replace_cards(sent.name, [updated_card])
```

`replace_cards` needs no user interaction and always runs as the app. It can
replace cards this app attached, add further cards while replacing, and remove
them with an empty list. Google's limits apply:

- the Chat app must be a member of the space, also for the USER-identity send;
- only cards this app attached can be replaced, and a message without cards
  cannot gain one;
- after an empty list removes the cards, they cannot be added back;
- when the person edits the message text, the app-owned cards are removed.

Google mapping: `spaces.messages.create` and `spaces.messages.replaceCards`.
