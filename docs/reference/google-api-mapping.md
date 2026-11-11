# Google API mapping

Chattice wraps platform primitives and technical boilerplate. The typed facade
never prevents access to the official client or raw payload.

| Chattice concept | Google concept / method | Auth/capability notes | Escape hatch |
| --- | --- | --- | --- |
| `MessageEvent` | interaction `Event.message` | inbound request verification | `event.raw` |
| `SpaceRef` | `Space` resource | resource name `spaces/*` | `event.raw` / `bot.raw.app()` |
| `ThreadRef` | `Thread` nested in Message | resource name or `threadKey` | `event.raw` |
| handler `return str/Card` | synchronous interaction response | HTTP, deadline-limited | return mapping / `RawInteractionResponse` |
| `messages.create` | `spaces.messages.create` | app `chat.bot`; user any supported create scope | `bot.raw.app().create_message` |
| `messages.create(attachments=...)` | `media.upload` → `spaces.messages.create` | USER only for the WHOLE send: upload AND create (sender = HUMAN) | `bot.raw.app()` (create), REST media extra |
| `attachments.upload` | `media.upload` | USER only (`chat.messages.create`/`chat.messages`/`chat.import`) | `chattice[media]` REST client |
| `attachments.download` | `media.download` | app `chat.bot`; user `chat.messages.readonly`/`chat.messages` | REST media extra |
| `attachments.get_metadata` | `spaces.messages.attachments.get` | APP only (`chat.bot`) | `bot.raw.app().get_attachment` |
| `memberships.create` | `spaces.members.create` | APP only; `chat.app.memberships` + administrator approval | `bot.raw.app().create_membership` |
| `memberships.get` | `spaces.members.get` | APP; `chat.bot` or `chat.app.memberships` | `bot.raw.app().get_membership` |
| `memberships.list` | `spaces.members.list` | APP; `chat.bot` or `chat.app.memberships`; explicit `Pager` | `bot.raw.app().list_memberships` |
| `memberships.delete` | `spaces.members.delete` | APP only; `chat.app.memberships` + administrator approval | `bot.raw.app().delete_membership` |
| `spaces.list` | `spaces.list` | APP only (`chat.bot`); caller-member Spaces | `bot.raw.app().list_spaces` |
| `MessageEvent.attachment_refs` | `message.attachment[]` (`attachmentDataRef`/`driveDataRef` oneof) | inbound metadata | `event.attachments` (lossless) |
| `chattice.cards.Image` | Cards v2 `Image` widget | HTTPS URL only | `RawWidget` |
| `F.text.regexp(...)` | — (Python `re`, match-from-start) | n/a | custom `Filter` |
| `messages.update` | `spaces.messages.update` | sender/identity/scope constraints | `bot.raw.app().update_message` |
| `messages.create(citations=..., cited_sources=...)` | `Message.elements` | Markdown markup; asynchronous creation only | `bot.raw.app().create_message` |
| `messages.replace_cards` | `spaces.messages.replaceCards` | APP only (`chat.bot`); app-owned cards | `bot.raw.app().replace_message_cards` |
| `messages.search` | `spaces.messages.search` | USER only; parent is always `spaces/-` | `bot.raw.user().search_messages` |
| `message_pins.create` / `list` / `delete` | `spaces.messagePins.*` | USER only (`chat.spaces.pins*`, `chat.spaces*`) | `bot.raw.user()` |
| `spaces.search` | `spaces.search` | USER only; joined spaces, or the organization with `admin_access=True` | `bot.raw.user().search_spaces` |
| `spaces.find_group_chats` | `spaces.findGroupChats` | USER only (`chat.memberships*`) | `bot.raw.user().find_group_chats` |
| `spaces.create` / `update` / `delete` | `spaces.create` / `patch` / `delete` | USER, or APP with administrator approval | `bot.raw.app()` / `bot.raw.user()` |
| `memberships.update` | `spaces.members.patch` | role only; USER, or APP with administrator approval | `bot.raw.app().update_membership` |
| `users.availability.*` | `users.availability.get` / `patch` / `markAs*` | USER only (`chat.users.availability*`); own state only | `bot.raw.user()` |
| `users.sections.*` | `users.sections.*`, `users.sections.items.*` | USER only (`chat.users.sections*`) | `bot.raw.user()` |
| `custom_emojis.*` | `customEmojis.create` / `get` / `list` / `delete` | USER only (`chat.customemojis*`) | `bot.raw.user()` |
| `admin_access=True` on `spaces.get/search/update/delete`, `memberships.*` | `useAdminAccess` | USER only; `chat.admin.*` scope; the user must be a Workspace administrator | `bot.raw.user()` |
| `users.read_state` / `thread_read_state` / `notification_setting` | `users.spaces.getSpaceReadState` / `updateSpaceReadState`, `users.spaces.threads.getThreadReadState`, `users.spaces.spaceNotificationSetting.*` | USER only; a space or thread is expanded to `users/me/...` | `bot.raw.user()` |
| add-on event object (`chat.<trigger>Payload`) | Workspace add-on Chat event object | HTTP; `AddOnTokenVerifier`; same domain events | `event.raw` |
| handler result for an add-on event | `hostAppDataAction.chatDataAction.*`, `action.navigations`, `action.modifyOperations` | chosen by `event.wire_format` | return mapping / `RawInteractionResponse` |
| `SystemCommandEvent` | interaction `SYSTEM_COMMAND` (`cancelStream`) | Developer Preview; `PreviewFeature.MESSAGE_STREAMING` | `event.raw` |
| `experimental.streaming.MessageStreams` | `spaces.streamMessages.*` | Developer Preview; APP only | REST |
| `experimental.sessions.ThreadSessions` | `spaces.threads.get` / `list` / `patch` | Developer Preview; APP only; 1:1 app DMs | REST |
| `Button` / `ActionEvent` | Cards v2 `onClick.action` / `CARD_CLICKED` | parameters are strings | `RawWidget`, `event.raw` |
| `FormInputs` / `FormModel` | `common.formInputs` | surface-specific response | `event.raw` |
| `Dialog` | `actionResponse.type=DIALOG` | eligible HTTP interaction only | raw response mapping |
| `AppHomeEvent` | App Home RenderActions | HTTP-only configured surface | `event.raw` |
| `CommandEvent` | slash `MESSAGE` / `APP_COMMAND` | numeric configured ID; message actions generally available | `event.raw` |
| `WorkspaceEvent` | Google Workspace Events CloudEvent | subscription identity/scopes | `event.data`, envelope parser |

Typed Card facades map to Google Cards v2 protos from `google-apps-card`.
`Card.to_proto()`/`to_dict()` and supported `from_proto()` reconstruction make
the boundary visible. `RawWidget` preserves a documented widget shape that is
not yet curated.

The [API reference](../api.md) renders signatures from current source and the
[public API inventory](../public-api.md) defines the stable import surface.

Official REST reference:
[Google Chat API v1](https://developers.google.com/workspace/chat/api/reference/rest).
