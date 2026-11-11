"""Synchronous interaction responses as Google wire JSON.

One handler result has two documented JSON shapes, one per payload
family (see ``chattice.events.WireFormat``):

- Chat API interaction events answer with a Message, optionally
  carrying an ``actionResponse``;
- Google Workspace add-on event objects answer with an action object:
  ``hostAppDataAction.chatDataAction`` for messages, ``action`` render
  actions for dialogs, the homepage and widget suggestions.
  https://developers.google.com/workspace/add-ons/chat/build

The response always uses the family the event arrived in. This module is
framework-neutral: it returns a JSON-ready mapping, never an HTTP
response object.
"""

from __future__ import annotations

from collections.abc import Mapping

from chattice.capabilities import can_open_dialog
from chattice.cards import ActionStatus, Card, Dialog
from chattice.cards.addon import bind_addon_actions_json
from chattice.events import (
    ActionEvent,
    ActionSource,
    AppHomeEvent,
    DialogEventType,
    Event,
    FormSubmitEvent,
    MessageEvent,
    RemovedFromSpaceEvent,
    WidgetUpdatedEvent,
    WireFormat,
)

from .response import RawInteractionResponse, RequestConfigResponse, WidgetAutocomplete

__all__ = ["serialize_response"]


def serialize_response(
    payload: object,
    *,
    event: Event,
    addon_action_url: str | None = None,
) -> Mapping[str, object] | None:
    """Return the JSON body answering ``event``, or None for an empty 200.

    ``addon_action_url`` is the HTTPS endpoint that receives card
    interactions of an HTTP add-on; when set, card actions in typed
    add-on responses are bound to it (``chattice.cards.addon``).

    Raises ``TypeError`` when the payload cannot answer this event.
    """
    if payload is None:
        return None
    if isinstance(event, RemovedFromSpaceEvent):
        # Documented Google rule: after REMOVED_FROM_SPACE the app cannot
        # respond — the user/channel is gone.
        raise TypeError("REMOVED_FROM_SPACE cannot receive a response")
    # Raw shapes are the caller's responsibility in either family.
    if isinstance(payload, RawInteractionResponse):
        return payload.payload
    if isinstance(payload, dict):
        return payload
    if event.wire_format is WireFormat.ADDON:
        body = _addon(payload, event)
        if addon_action_url is not None:
            bound: dict[str, object] = bind_addon_actions_json(body, addon_action_url)
            return bound
        return body
    return _chat_api(payload, event)


def _unsupported(payload: object) -> TypeError:
    return TypeError(
        f"Unsupported synchronous response payload {type(payload).__name__}"
    )


def _is_dialog_submit(event: Event) -> bool:
    return (
        isinstance(event, ActionEvent)
        and event.dialog is not None
        and event.dialog.type == DialogEventType.SUBMIT_DIALOG
    )


def _require_dialog_opener(event: Event) -> None:
    # The serializer guards with the SAME predicate that derives the
    # DIALOGS capability — no second handwritten rule.
    if not can_open_dialog(event):
        raise TypeError("Dialog responses require a command or a REQUEST_DIALOG action")


def _cards_v2(card: Card) -> list[dict[str, object]]:
    return [{"cardId": "card", "card": card.to_dict()}]


# --- Chat API interaction events -------------------------------------------


def _chat_api(payload: object, event: Event) -> dict[str, object]:
    if isinstance(payload, str):
        return {"text": payload}
    if isinstance(payload, Dialog):
        _require_dialog_opener(event)
        return {"actionResponse": {"type": "DIALOG", "dialogAction": payload.to_dict()}}
    if isinstance(payload, ActionStatus):
        if not _is_dialog_submit(event):
            raise TypeError(
                "ActionStatus responses require a SUBMIT_DIALOG ActionEvent"
            )
        return {
            "actionResponse": {
                "type": "DIALOG",
                "dialogAction": {"actionStatus": payload.to_dict()},
            }
        }
    if isinstance(payload, Card):
        return _chat_api_card(payload, event)
    if isinstance(payload, WidgetAutocomplete):
        _require_widget_update(event)
        return payload.to_dict()
    if isinstance(payload, RequestConfigResponse):
        return payload.to_dict()
    raise _unsupported(payload)


def _chat_api_card(card: Card, event: Event) -> dict[str, object]:
    if isinstance(event, AppHomeEvent):
        return {"action": {"navigations": [{"pushCard": card.to_dict()}]}}
    if isinstance(event, FormSubmitEvent):
        # Documented update shape for home-card widget interactions.
        return {
            "renderActions": {
                "action": {"navigations": [{"updateCard": card.to_dict()}]}
            }
        }
    body: dict[str, object] = {"cardsV2": _cards_v2(card)}
    if isinstance(event, MessageEvent):
        # Link previews: a matched URL answer replaces the USER's message
        # cards (ResponseType.UPDATE_USER_MESSAGE_CARDS). Plain messages
        # get a NEW_MESSAGE response (no actionResponse).
        if event.matched_url is not None:
            body["actionResponse"] = {"type": "UPDATE_USER_MESSAGE_CARDS"}
    elif isinstance(event, ActionEvent):
        # Documented sender rule: bot messages update via UPDATE_MESSAGE,
        # human messages via UPDATE_USER_MESSAGE_CARDS. Never guess —
        # require the sender type from the wire payload.
        if event.sender_type == "BOT":
            body["actionResponse"] = {"type": "UPDATE_MESSAGE"}
        elif event.sender_type == "HUMAN":
            body["actionResponse"] = {"type": "UPDATE_USER_MESSAGE_CARDS"}
        else:
            raise _missing_sender_type(event)
    return body


def _missing_sender_type(event: ActionEvent) -> TypeError:
    return TypeError(
        "Card responses to CARD_CLICKED require the original "
        "message sender type (BOT or HUMAN) — "
        f"got {event.sender_type!r}"
    )


def _require_widget_update(event: Event) -> None:
    if not isinstance(event, WidgetUpdatedEvent):
        raise TypeError("WidgetAutocomplete responses require a WIDGET_UPDATED event")


# --- Google Workspace add-on event objects ---------------------------------


def _chat_data_action(action: str, value: Mapping[str, object]) -> dict[str, object]:
    return {"hostAppDataAction": {"chatDataAction": {action: value}}}


def _navigation(navigation: Mapping[str, object]) -> dict[str, object]:
    return {"action": {"navigations": [navigation]}}


def _addon(payload: object, event: Event) -> dict[str, object]:
    if isinstance(payload, str):
        return _chat_data_action("createMessageAction", {"message": {"text": payload}})
    if isinstance(payload, Dialog):
        _require_dialog_opener(event)
        return _navigation({"pushCard": payload.body.to_dict()})
    if isinstance(payload, ActionStatus):
        return _addon_close_dialog(payload, event)
    if isinstance(payload, Card):
        return _addon_card(payload, event)
    if isinstance(payload, WidgetAutocomplete):
        _require_widget_update(event)
        return {
            "action": {
                "modifyOperations": [
                    {
                        "updateWidget": {
                            "selectionInputWidgetSuggestions": {
                                "suggestions": [
                                    {"text": text, "value": text}
                                    for text in payload.suggestions
                                ]
                            }
                        }
                    }
                ]
            }
        }
    if isinstance(payload, RequestConfigResponse):
        if not payload.resource:
            raise TypeError(
                "An add-on authorization prompt requires "
                "RequestConfigResponse(resource=...): the display name of "
                "the service the user is asked to connect"
            )
        return {
            "basic_authorization_prompt": {
                "authorization_url": payload.auth_url,
                "resource": payload.resource,
            }
        }
    raise _unsupported(payload)


def _addon_close_dialog(status: ActionStatus, event: Event) -> dict[str, object]:
    """Close the dialog; the add-on family has no in-dialog status.

    Both outcomes close the dialog, and the message (if any) is shown as
    a notification — the documented add-on pattern for a failed submit.
    """
    if not _is_dialog_submit(event):
        raise TypeError("ActionStatus responses require a SUBMIT_DIALOG ActionEvent")
    action: dict[str, object] = {
        "navigations": [{"endNavigation": {"action": "CLOSE_DIALOG"}}]
    }
    if status.user_facing_message:
        action["notification"] = {"text": status.user_facing_message}
    return {"action": action}


def _addon_card(card: Card, event: Event) -> dict[str, object]:
    if isinstance(event, AppHomeEvent):
        return _navigation({"pushCard": card.to_dict()})
    if isinstance(event, FormSubmitEvent):
        return _navigation({"updateCard": card.to_dict()})
    cards = {"cardsV2": _cards_v2(card)}
    if isinstance(event, MessageEvent) and event.matched_url is not None:
        # Link preview: attach the card to the user's message.
        return _chat_data_action("updateInlinePreviewAction", cards)
    if isinstance(event, ActionEvent):
        if event.source is ActionSource.HOME:
            return _navigation({"updateCard": card.to_dict()})
        if event.sender_type == "BOT":
            return _chat_data_action("updateMessageAction", {"message": cards})
        if event.sender_type == "HUMAN":
            return _chat_data_action("updateInlinePreviewAction", cards)
        raise _missing_sender_type(event)
    return _chat_data_action("createMessageAction", {"message": cards})
