# ADR-014: Workspace add-on payload family for Chat apps

- Status: Accepted (supersedes the add-on exclusion in ADR-009)
- Owners: maintainers

## Context

ADR-009 limited the interaction adapter to Chat API interaction events and
rejected Workspace add-on `chat.*Payload` objects as a different schema.

Since then Google made the add-on configuration a first-class way to build a
Chat app: App Home for add-ons is generally available, the streaming guide
documents the `SYSTEM_COMMAND` payload for both families, and the app
configuration API lives in the Workspace Add-ons API. A Chat app configured as
an add-on receives **only** the add-on event object and must answer with
add-on actions, so such an app could not use the framework at all.

The two families describe the same interactions with different JSON:

| | Chat API interaction event | Add-on event object |
| --- | --- | --- |
| Trigger | top-level `type` | which `chat.<trigger>Payload` is present |
| Reply with a message | a `Message` | `hostAppDataAction.chatDataAction.createMessageAction` |
| Dialog, homepage | `actionResponse` / `renderActions` | `action.navigations` |
| Card action over HTTP | `function` is a name | `function` is the endpoint URL |
| Request identity | Google Chat service account | the add-on's service account |

## Decision

The adapter accepts both families and produces the **same domain events**.

1. **Detection is structural.** A `chat` object without `type`, next to no
   top-level `type`, is an add-on event object. Mixing the families fails.
   An unknown `*Payload` trigger becomes `UnknownEvent`.
2. **The event records its family** in `Event.wire_format`
   (`WireFormat.CHAT_API` or `WireFormat.ADDON`). Handlers do not branch on
   it; the response serializer does.
3. **One serializer, two shapes.** `serialize_response()` in
   `chattice.transports.http` turns a handler result into the JSON of the
   family the event arrived in. It is framework-neutral; the FastAPI route
   only encodes it. Raw `dict` / `RawInteractionResponse` results are passed
   through in either family.
4. **Card actions keep their names.** An HTTP add-on must put its endpoint URL
   into `Action.function`. Binding (`chattice.cards.addon`) rewrites
   `function` to the configured URL and carries the handler name in the
   reserved parameter `chattice_function`; the adapter moves it back to the
   event's function name. Binding is applied when an action URL is configured:
   `create_chat_router(..., addon_action_url=...)` for synchronous responses
   and `Bot(addon_action_url=...)` for outbound messages. Without the URL
   nothing is rewritten.
5. **Separate request verifier.** `AddOnTokenVerifier` checks the OIDC token
   of the add-on's service account. `GoogleTokenVerifier` keeps accepting only
   the Google Chat service account.

## Consequences

- One router and one set of handlers serve both configurations; migrating an
  app between them is a configuration change.
- Where the add-on family cannot express a Chat API response, the mapping is
  documented rather than hidden: an `ActionStatus` closes the dialog and shows
  its message as a notification (there is no in-dialog error state), and an
  authorization prompt needs a resource display name.
- The reserved parameter name is part of the wire contract of cards already
  sent; it cannot be renamed without breaking their buttons.
- Not verified against a live add-on deployment at the time of writing. Two
  points rest on inference because Google's HTTP documentation does not show
  them: which event a homepage card click produces (both a
  `buttonClickedPayload` without a message and a payload-less event are
  handled), and what `commonEventObject.invokedFunction` holds for an action
  addressed by URL (the reserved parameter makes routing independent of it).

## Alternatives considered

- **Keep rejecting add-on payloads (ADR-009):** leaves every add-on configured
  Chat app unsupported while Google moves new features there.
- **A second adapter and a second event hierarchy:** doubles the handler
  vocabulary for interactions that are semantically identical.
- **Let handlers build add-on JSON themselves:** every handler would branch on
  the configuration; this is what `RawInteractionResponse` remains for.
- **Derive the action URL from the incoming request:** wrong behind proxies and
  unavailable for outbound messages; an explicit URL is required instead.
- **Reuse Google's sample parameter name `actionName`:** it is a sample
  convention, not an API contract, and would collide with application
  parameters silently.

## Sources

[Chat event object](https://developers.google.com/workspace/add-ons/concepts/event-objects#chat-event-object),
[Build Google Chat interfaces](https://developers.google.com/workspace/add-ons/chat/build),
[dialogs](https://developers.google.com/workspace/add-ons/chat/dialogs),
[commands](https://developers.google.com/workspace/add-ons/chat/commands),
[collect information](https://developers.google.com/workspace/add-ons/chat/collect-information),
[link previews](https://developers.google.com/workspace/add-ons/chat/preview-links),
[homepages](https://developers.google.com/workspace/add-ons/concepts/homepages),
[validate requests](https://developers.google.com/workspace/add-ons/guides/alternate-runtimes),
[authorization prompt](https://developers.google.com/workspace/add-ons/guides/connect-third-party-service).
