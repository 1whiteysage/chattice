"""Normalization of documented Google Chat HTTP envelope families.

Google delivers one user interaction in one of two JSON families,
depending on how the Chat app is configured in the Google Cloud console:

- Chat API interaction events: a top-level ``type`` discriminator,
  optionally wrapped under ``chat`` (App Home style);
- Google Workspace add-on event objects: no ``type``; the trigger is the
  ``chat.<trigger>Payload`` key that is present.

Both are reduced to one direct-event mapping so the parser has a single
input shape. The family is kept so the response can be serialized in it.
"""

from __future__ import annotations

from collections.abc import Mapping
from copy import deepcopy
from dataclasses import dataclass

from chattice.cards.addon import ADDON_FUNCTION_PARAMETER
from chattice.events import WireFormat

from .exceptions import (
    ConflictingEnvelopeError,
    InvalidInteractionPayload,
    UnsupportedEnvelopeError,
)

# Trigger payloads of the add-on Chat event object and the interaction
# type each one corresponds to.
# https://developers.google.com/workspace/add-ons/concepts/event-objects#chat-event-object
_ADDON_TRIGGERS: dict[str, str] = {
    "messagePayload": "MESSAGE",
    "addedToSpacePayload": "ADDED_TO_SPACE",
    "removedFromSpacePayload": "REMOVED_FROM_SPACE",
    "buttonClickedPayload": "CARD_CLICKED",
    "widgetUpdatedPayload": "WIDGET_UPDATED",
    "appCommandPayload": "APP_COMMAND",
    # Developer Preview (message streaming).
    "systemCommandPayload": "SYSTEM_COMMAND",
}
# Payload fields that have the same name and meaning in a direct event.
_ADDON_PAYLOAD_FIELDS = (
    "message",
    "space",
    "thread",
    "isDialogEvent",
    "dialogEventType",
    "appCommandMetadata",
    "systemCommandMetadata",
)


@dataclass(frozen=True, slots=True)
class NormalizedEnvelope:
    event: dict[str, object]
    raw: dict[str, object]
    wire_format: WireFormat = WireFormat.CHAT_API


def normalize_envelope(payload: Mapping[str, object]) -> NormalizedEnvelope:
    """Deep-snapshot and normalize one interaction JSON of either family."""
    if not isinstance(payload, Mapping):
        raise InvalidInteractionPayload("Interaction payload must be a mapping")
    if any(not isinstance(key, str) for key in payload):
        raise InvalidInteractionPayload("Interaction payload keys must be strings")

    raw = deepcopy(dict(payload))
    wrapped = raw.get("chat")
    if wrapped is not None and not isinstance(wrapped, Mapping):
        raise UnsupportedEnvelopeError("The wrapped 'chat' value must be a mapping")
    outer_common = raw.get("commonEventObject")
    if outer_common is not None and not isinstance(outer_common, Mapping):
        raise InvalidInteractionPayload("'commonEventObject' must be a mapping")

    if (
        isinstance(wrapped, Mapping)
        and raw.get("type") is None
        and wrapped.get("type") is None
    ):
        return NormalizedEnvelope(
            event=_addon_event(wrapped, outer_common),
            raw=raw,
            wire_format=WireFormat.ADDON,
        )
    return NormalizedEnvelope(
        event=_chat_api_event(raw, wrapped, outer_common), raw=raw
    )


def _chat_api_event(
    raw: dict[str, object],
    wrapped: Mapping[str, object] | None,
    outer_common: Mapping[str, object] | None,
) -> dict[str, object]:
    direct_type = raw.get("type")
    if wrapped is None:
        if direct_type is None:
            raise UnsupportedEnvelopeError(
                "Expected a direct 'type' field or a 'chat' event object"
            )
        event = dict(raw)
        event.pop("commonEventObject", None)
    else:
        event = dict(wrapped)
        wrapped_type = event.get("type")
        if wrapped_type is None:
            # A direct ``type`` next to an add-on shaped ``chat`` object:
            # the two families cannot be mixed.
            raise UnsupportedEnvelopeError("The wrapped 'chat' event requires 'type'")
        if direct_type is not None:
            if direct_type != wrapped_type:
                raise ConflictingEnvelopeError(
                    "Direct and wrapped event types conflict: "
                    f"{direct_type!r} != {wrapped_type!r}"
                )
            for key, value in raw.items():
                if key in {"chat", "commonEventObject", "common", "type"}:
                    continue
                if key in event and event[key] != value:
                    raise ConflictingEnvelopeError(
                        f"Direct and wrapped event field {key!r} conflicts"
                    )
                event.setdefault(key, value)

    inner_common = event.get("common")
    if inner_common is not None and not isinstance(inner_common, Mapping):
        raise InvalidInteractionPayload("'common' must be a mapping")
    if inner_common is not None and outer_common is not None:
        if dict(inner_common) != dict(outer_common):
            raise ConflictingEnvelopeError(
                "'common' and 'commonEventObject' contain conflicting data"
            )
    if outer_common is not None:
        event["common"] = dict(outer_common)
    return event


def _addon_event(
    chat: Mapping[str, object], outer_common: Mapping[str, object] | None
) -> dict[str, object]:
    """Reduce an add-on Chat event object to the direct-event shape."""
    triggers = [key for key in chat if key.endswith("Payload")]
    if len(triggers) > 1:
        raise ConflictingEnvelopeError(
            "An add-on Chat event carries exactly one trigger payload; got "
            + ", ".join(sorted(triggers))
        )

    event: dict[str, object] = {
        key: chat[key] for key in ("user", "space", "eventTime") if key in chat
    }
    common = _addon_common(outer_common)
    if common is not None:
        event["common"] = common

    if not triggers:
        # The App Home trigger has no payload. A widget interaction on the
        # homepage card is told apart by its invoked function.
        event["type"] = "SUBMIT_FORM" if _has_function(common) else "APP_HOME"
        return event

    trigger = triggers[0]
    payload = chat[trigger]
    if not isinstance(payload, Mapping):
        raise InvalidInteractionPayload(f"'chat.{trigger}' must be a mapping")
    # A trigger this version does not know keeps its key as the type, so
    # it reaches handlers as an UnknownEvent instead of failing.
    event["type"] = _ADDON_TRIGGERS.get(trigger, trigger)
    for field in _ADDON_PAYLOAD_FIELDS:
        if field in payload:
            event[field] = payload[field]
    if event.get("dialogEventType") == "TYPE_UNSPECIFIED":
        del event["dialogEventType"]
    metadata = event.get("appCommandMetadata")
    if isinstance(metadata, Mapping):
        event["appCommandMetadata"] = _int64_command_id(metadata)
    return event


def _addon_common(
    outer_common: Mapping[str, object] | None,
) -> dict[str, object] | None:
    """Copy ``commonEventObject``, restoring a bound action function name.

    HTTP add-ons address a card action by endpoint URL, so the handler
    name travels in a reserved parameter (see ``chattice.cards.addon``).
    It is moved back to ``invokedFunction`` and hidden from handlers.
    """
    if outer_common is None:
        return None
    common = dict(outer_common)
    parameters = common.get("parameters")
    if isinstance(parameters, Mapping) and ADDON_FUNCTION_PARAMETER in parameters:
        function = parameters[ADDON_FUNCTION_PARAMETER]
        if not isinstance(function, str) or not function:
            raise InvalidInteractionPayload(
                f"The {ADDON_FUNCTION_PARAMETER!r} action parameter must be "
                "a non-empty string"
            )
        common["invokedFunction"] = function
        common["parameters"] = {
            key: value
            for key, value in parameters.items()
            if key != ADDON_FUNCTION_PARAMETER
        }
    return common


def _has_function(common: Mapping[str, object] | None) -> bool:
    if common is None:
        return False
    function = common.get("invokedFunction")
    # An endpoint URL is how Google addresses the app, not a handler name.
    return (
        isinstance(function, str)
        and bool(function)
        and not function.startswith(("https://", "http://"))
    )


def _int64_command_id(metadata: Mapping[str, object]) -> dict[str, object]:
    """Add-on events document ``appCommandId`` as an int64 JSON string."""
    result = dict(metadata)
    command_id = result.get("appCommandId")
    if isinstance(command_id, str):
        try:
            result["appCommandId"] = int(command_id)
        except ValueError as error:
            raise InvalidInteractionPayload(
                f"appCommandId is not an int64 string: {command_id!r}"
            ) from error
    return result


__all__ = ["NormalizedEnvelope", "normalize_envelope"]
