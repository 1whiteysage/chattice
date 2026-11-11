# Google Workspace add-on event object fixture provenance

These compact synthetic JSON examples follow the documented event object
that Google sends to a Chat app built as a Google Workspace add-on. They
use placeholder resource IDs, names, text, and parameter values. Fields the
parser does not use are omitted; no field name or nesting is invented.

Primary schema sources:

- [Event objects: Chat event object](https://developers.google.com/workspace/add-ons/concepts/event-objects#chat-event-object)
- [Build Google Chat interfaces](https://developers.google.com/workspace/add-ons/chat/build)
- [Open interactive dialogs](https://developers.google.com/workspace/add-ons/chat/dialogs)
- [Respond to commands](https://developers.google.com/workspace/add-ons/chat/commands)
- [Collect information](https://developers.google.com/workspace/add-ons/chat/collect-information)
- [Preview links](https://developers.google.com/workspace/add-ons/chat/preview-links)
- [Homepages: configure a homepage for Chat](https://developers.google.com/workspace/add-ons/concepts/homepages)
- [Stream messages](https://developers.google.com/workspace/chat/stream-messages) (Developer Preview)

| Fixture | Provenance and transformation |
| --- | --- |
| `message.json` | `chat.messagePayload` (`message`, `space`) plus `chat.user`, `chat.eventTime`, and `commonEventObject` locale and time zone. `authorizationEventObject.systemIdToken` is a placeholder string, not a token. |
| `message_matched_url.json` | `messagePayload.message.matchedUrl.url` from the link preview guide. |
| `added_to_space.json` | `chat.addedToSpacePayload` with `space` and `interactionAdd`. |
| `removed_from_space.json` | `chat.removedFromSpacePayload` with `space`. |
| `button_clicked.json` | `chat.buttonClickedPayload` (`message`, `space`). The action was sent with an endpoint URL as `function`, as the HTTP samples do; `commonEventObject.parameters` carries Chattice's reserved `chattice_function` handler name next to an application parameter. `invokedFunction` holding the endpoint URL is an assumption: Google's HTTP add-on samples do not show the field. |
| `button_clicked_unbound.json` | The same click for a card authored the way Google's HTTP samples do it: no handler name, only an application parameter (`actionName`). |
| `button_clicked_human_message.json` | A click on a link preview card attached to a user's message (`message.sender.type = HUMAN`), from the link preview guide. |
| `button_clicked_request_dialog.json` | `buttonClickedPayload.isDialogEvent` and `dialogEventType = REQUEST_DIALOG` from the dialog guide. |
| `button_clicked_submit_dialog.json` | `dialogEventType = SUBMIT_DIALOG` with `commonEventObject.formInputs`. |
| `button_clicked_home.json` | A click on the homepage card. **Assumption:** Google documents the response (`updateCard`) but not the event; this fixture assumes a `buttonClickedPayload` without a `message`. |
| `app_home_widget.json` | The other candidate shape for a homepage card interaction, also an **assumption**: no trigger payload, the handler name in `commonEventObject.parameters`. |
| `widget_updated.json` | `chat.widgetUpdatedPayload` with the documented `autocomplete_widget_query` parameter. |
| `app_command_slash.json` | `chat.appCommandPayload` with `appCommandMetadata` (`appCommandId` as the documented int64 string, `SLASH_COMMAND`), `space`, `thread`, and the `message` carrying the slash command. |
| `app_command_quick.json` | `appCommandPayload` for a `QUICK_COMMAND` configured to open a dialog. |
| `app_home.json` | The App Home trigger: no payload, only `chat.user` and `chat.eventTime`, as the Chat event object reference states. |
| `system_command_cancel_stream.json` | The "Google Workspace add-ons" `systemCommandPayload` example from the streaming guide, copied with its placeholder identifiers (Developer Preview). |
| `unknown_trigger.json` | Forward-compatibility case: a synthetic future `*Payload` key. Not claimed as a Google payload. |
