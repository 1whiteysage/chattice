# Google Chat interaction adapter

Status: **Implemented**. See
[ADR-009](../adr/ADR-009-google-interaction-normalization.md).

## Boundary

```text
decoded Mapping[str, object]
        -> envelope normalization
        -> permissive Pydantic boundary models
        -> immutable framework domain Event
        -> Dispatcher.feed_update()
```

`parse_interaction()` is pure and has no HTTP, credentials, request
verification, Google client, networking, or response responsibility:

```python
from chattice.adapters.google_chat import parse_interaction

event = parse_interaction(payload)
result = await dispatcher.feed_update(event)
```

`GoogleInteractionAdapter().parse(payload)` is the equivalent object facade.
Pydantic validates only external data inside the adapter; dispatcher, filters,
middleware, handlers, and domain values remain independent frozen dataclasses.

## Supported events

The adapter recognizes the current stable Google Chat interaction types:

- `MESSAGE` -> `MessageEvent`
- `ADDED_TO_SPACE` -> `AddedToSpaceEvent`
- `REMOVED_FROM_SPACE` -> `RemovedFromSpaceEvent`
- `CARD_CLICKED` -> `ActionEvent`
- `WIDGET_UPDATED` -> `WidgetUpdatedEvent`
- `APP_COMMAND` -> `CommandEvent`
- `APP_HOME` -> `AppHomeEvent`
- `SUBMIT_FORM` -> `FormSubmitEvent`

`UNSPECIFIED`/`TYPE_UNSPECIFIED` is malformed. Any other string becomes an
`UnknownEvent` with `original_type`; missing or non-string discriminators are
malformed rather than unknown.

## Envelope normalization

Two documented HTTP families are accepted:

```json
{"type": "MESSAGE", "message": {"text": "ping"}}
```

and the App Home sample family:

```json
{
  "chat": {"type": "SUBMIT_FORM", "user": {}, "space": {}},
  "commonEventObject": {"invokedFunction": "update_home"}
}
```

Outer `commonEventObject` normalizes to the same domain common-data view as a
direct event's `common`, without making the raw fields interchangeable. If a
payload supplies both direct and wrapped types or both common objects and they
disagree, `ConflictingEnvelopeError` is raised.

## Workspace add-on event objects

A Chat app configured as a Google Workspace add-on receives a different
family: no `type`, and the trigger is the `chat.<trigger>Payload` key that is
present ([ADR-014](../adr/ADR-014-workspace-addon-payload-family.md)).

```json
{
  "commonEventObject": {"hostApp": "CHAT", "userLocale": "en"},
  "chat": {
    "user": {"name": "users/123"},
    "messagePayload": {"space": {"name": "spaces/AAA"}, "message": {"text": "ping"}}
  }
}
```

The adapter reduces it to the same domain events and records the family in
`event.wire_format`:

| Trigger payload | Domain event |
| --- | --- |
| `messagePayload` | `MessageEvent` |
| `addedToSpacePayload` / `removedFromSpacePayload` | `AddedToSpaceEvent` / `RemovedFromSpaceEvent` |
| `buttonClickedPayload` | `ActionEvent` |
| `widgetUpdatedPayload` | `WidgetUpdatedEvent` |
| `appCommandPayload` | `CommandEvent` (slash commands included) |
| `systemCommandPayload` | `SystemCommandEvent` (Developer Preview) |
| none | `AppHomeEvent`, or `FormSubmitEvent` for a homepage widget interaction |
| any other `*Payload` | `UnknownEvent` |

Two trigger payloads in one event, or a top-level `type` next to an add-on
shaped `chat` object, are rejected.

## Raw preservation and validation

Every event's `raw` is a `copy.deepcopy()` snapshot of the complete caller
mapping. Mutating the caller after parsing cannot change the snapshot. The raw
snapshot is still an opaque mutable Python value; event freezing does not make
arbitrary nested data recursively immutable.

Boundary models allow unknown harmless Google fields. Malformed present fields
raise `InvalidInteractionPayload` and chain the Pydantic or conversion error.
Envelope topology errors use `UnsupportedEnvelopeError`; contradictions use
`ConflictingEnvelopeError`. All inherit `GoogleInteractionError`.

## Common data and forms

`common.invokedFunction` is the primary action identity. The documented
`action.actionMethodName` form is a fallback; if both differ, parsing fails.
Likewise, `common.parameters` is primary and FormAction parameters are a
fallback. Parameters must be string key/value data, are exposed through an
immutable mapping, and are never JSON-decoded or coerced.

Form inputs remain separate from parameters and use `FormInputs`:

- `StringInput(values=...)` preserves single and multiple selections;
- `DateInput(ms_since_epoch=...)`;
- `DateTimeInput(ms_since_epoch=..., has_date=..., has_time=...)`;
- `TimeInput(hours=..., minutes=...)`;
- `UnknownFormInput(kind=..., raw=...)` preserves future variants.

Epoch values accept either the REST schema's int64 string representation or
the official HTTP example's JSON number and normalize losslessly to Python
`int`. No automatic `datetime` conversion changes their meaning.

## Events and routing

Common handler-facing metadata includes timezone-aware `event_time`, `actor`,
`space`, `thread`, dialog state, locale, and timezone when present. References
contain only basic resource identity/presentation fields.

New router observers are `command`, `added_to_space`, `removed_from_space`,
`widget_updated`, `app_home`, and `form_submit`. Existing `message`, `action`,
`unknown_event`, generic fallback, middleware, propagation, and error semantics
are unchanged.

`CommandEvent` exposes only numeric `command_id`, documented `command_type`,
and message text when present. It never fabricates a configured command name.
Dialog metadata recognizes `REQUEST_DIALOG`, `SUBMIT_DIALOG`, and
`CANCEL_DIALOG`, while preserving future strings. The adapter parses dialog state
only and exposes no response or builder API.

## Interaction events are not Workspace Events

This adapter consumes Chat API interaction callbacks. Workspace Events arrive
as CloudEvents for resource changes and need separate envelope, auth,
idempotency, and response semantics. They are separate runtime concerns.
