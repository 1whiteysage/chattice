# Google Chat interaction fixture provenance

These compact synthetic JSON examples follow the documented interaction
shapes. They use placeholder resource IDs, display
names, text, function names, and parameter values. Fields not used by the parser
are intentionally omitted; no field name or nesting is invented.

Primary schema sources:

- [Event REST reference](https://developers.google.com/workspace/chat/api/reference/rest/v1/Event)
- [EventType reference](https://developers.google.com/workspace/chat/api/reference/rest/v1/EventType)
- [Receive and respond to interaction events](https://developers.google.com/workspace/chat/receive-respond-interactions)
- [Collect and process information](https://developers.google.com/workspace/chat/read-form-data)
- [App Home guide and official Python sample](https://developers.google.com/workspace/chat/send-app-home-card-message)
- [Dialog guide](https://developers.google.com/workspace/chat/dialogs)
- [DialogEventType reference](https://developers.google.com/workspace/chat/api/reference/rest/v1/DialogEventType)

Per-fixture derivation:

| Fixture | Provenance and transformation |
| --- | --- |
| `message.json` | Minimized direct `Event` schema plus `MESSAGE` conditional fields from EventType, using placeholder identifiers and text. |
| `added_to_space.json` | Minimized direct `Event` using EventType's documented user/space fields and placeholder values. |
| `removed_from_space.json` | Same method for `REMOVED_FROM_SPACE`, using placeholder values. |
| `card_clicked.json` | Direct Event/CommonEventObject and FormAction schemas; primary and fallback action values intentionally match. |
| `card_clicked_form.json` | The HTTP `CARD_CLICKED` snippet in “Collect and process information” is minimized exactly for string/date inputs; multiselect, date-time, and time variants are added from the `Inputs`, `DateTimeInput`, and `TimeInput` JSON schemas on the Event reference. |
| `card_clicked_request_dialog.json` | Minimized Event schema with `isDialogEvent`/`REQUEST_DIALOG` as documented by DialogEventType. |
| `card_clicked_submit_dialog.json` | Minimized dialog guide's documented `CARD_CLICKED` + `SUBMIT_DIALOG` behavior. |
| `card_clicked_cancel_dialog.json` | Minimized DialogEventType's documented `CARD_CLICKED` + `CANCEL_DIALOG` behavior. |
| `system_command_cancel_stream.json` | The “Google Chat API” `SYSTEM_COMMAND` payload from [Stream messages](https://developers.google.com/workspace/chat/stream-messages), copied with its placeholder identifiers (Developer Preview). |
| `widget_updated.json` | Minimized Event/EventType `WIDGET_UPDATED` shape with documented associated CommonEventObject action metadata. |
| `app_command.json` | Minimized Event `AppCommandMetadata` JSON schema for a documented **QUICK_COMMAND** (numeric command ID, `QUICK_COMMAND` type). |
| `slash_command.json` | Documented slash-command shape from the [command guide](https://developers.google.com/workspace/chat/commands): `MESSAGE` + `message.slashCommand.commandId` (int64 string) + `argumentText` + `message.sender.type`, using placeholder values. |
| `message_action.json` | Minimized message-action example from the [command guide](https://developers.google.com/workspace/chat/commands): `APP_COMMAND` + `appCommandMetadata.MESSAGE_ACTION` + the target `message`, using placeholder values. |
| `message_matched_url.json` | Documented link-preview shape from the [link preview guide](https://developers.google.com/workspace/chat/preview-links): `MESSAGE` + `message.matchedUrl.url` + `message.sender.type`, using placeholder values. |
| `card_clicked_human_message.json` | Documented `CARD_CLICKED` with `message.sender.type = HUMAN` (sender-aware response rule source), using placeholder values. |
| `app_home.json` | Minimized official Python App Home HTTP envelope (`event['chat']['type']`) plus EventType's documented user/space fields inside the Chat sub-event. |
| `app_home_card_clicked.json` | Minimized App Home guide's wrapped `chat.CARD_CLICKED` interaction plus outer `commonEventObject.invokedFunction`, using placeholder values. |
| `submit_form.json` | Minimized official Python App Home envelope (`chat.type` + outer `commonEventObject`) and form-input schema. |
| `unknown_event.json` | Direct Event forward-compatibility case using only the documented string discriminator position and harmless extra data. The future enum string is intentionally synthetic to exercise unknown handling, not claimed as a Google event. |
| `malformed_*.json` | Negative mutations of the documented schema: removed type, non-string type, naive timestamp, and conflicting direct/wrapped types. They are intentionally invalid and are not presented as Google payloads. |

The official Event schema displays int64 epoch values as JSON strings, while
the official HTTP form example displays `msSinceEpoch` as a JSON number. The
fixtures cover both losslessly and the adapter accepts either representation.
