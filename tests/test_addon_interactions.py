"""Chat apps built as Google Workspace add-ons: inbound events and responses."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, cast

import httpx
import pytest
from fastapi import FastAPI

from chattice import Dispatcher, F, Router
from chattice.adapters.google_chat import (
    ConflictingEnvelopeError,
    InvalidInteractionPayload,
    UnsupportedEnvelopeError,
    parse_interaction,
)
from chattice.capabilities import (
    PreviewFeature,
    ResponseCapabilities,
    ResponseCapability,
)
from chattice.cards import (
    ActionStatus,
    Button,
    ButtonList,
    Card,
    CardHeader,
    Dialog,
    Section,
    TextParagraph,
)
from chattice.cards.addon import (
    ADDON_FUNCTION_PARAMETER,
    bind_addon_actions,
    bind_addon_actions_json,
)
from chattice.events import (
    ActionEvent,
    ActionSource,
    AddedToSpaceEvent,
    AppHomeEvent,
    CommandEvent,
    CommandKind,
    DialogEventType,
    Event,
    FormSubmitEvent,
    MessageEvent,
    RemovedFromSpaceEvent,
    StringInput,
    SystemCommandEvent,
    UnknownEvent,
    WidgetUpdatedEvent,
    WireFormat,
)
from chattice.integrations.fastapi import create_chat_router
from chattice.transports.http import (
    MockVerifier,
    RawInteractionResponse,
    RequestConfigResponse,
    WidgetAutocomplete,
    serialize_response,
)

FIXTURES = Path(__file__).parent / "fixtures/google_chat/addon"
ACTION_URL = "https://bot.example.com/chat"


def load(name: str) -> dict[str, object]:
    return cast(dict[str, object], json.loads((FIXTURES / name).read_text()))


def _card(*, function: str = "case.assign") -> Card:
    return Card(
        header=CardHeader(title="Case 42"),
        sections=[
            Section(
                widgets=[
                    TextParagraph(text="Open"),
                    ButtonList(
                        buttons=[
                            Button(
                                text="Assign",
                                action=function,
                                parameters={"case_id": "42"},
                            )
                        ]
                    ),
                ]
            )
        ],
    )


# --- inbound: one event family, the same domain events ---------------------


def test_message_event() -> None:
    event = parse_interaction(load("message.json"))

    assert isinstance(event, MessageEvent)
    assert event.wire_format is WireFormat.ADDON
    assert event.text == "ping"
    assert event.actor and event.actor.name == "users/123"
    assert event.space and event.space.name == "spaces/AAA"
    assert event.thread and event.thread.name == "spaces/AAA/threads/THR"
    assert event.message and event.message.name == "spaces/AAA/messages/MSG"
    assert event.locale == "en"
    assert event.timezone and event.timezone.id == "Europe/Kyiv"
    # The original event object stays reachable, including fields the
    # parser does not model.
    assert "authorizationEventObject" in cast(dict[str, object], event.raw)


def test_chat_api_events_keep_their_family() -> None:
    event = parse_interaction(
        {
            "type": "MESSAGE",
            "message": {"text": "ping"},
            "user": {"name": "users/123"},
            "space": {"name": "spaces/AAA"},
        }
    )
    assert event.wire_format is WireFormat.CHAT_API


def test_link_preview_message() -> None:
    event = parse_interaction(load("message_matched_url.json"))
    assert isinstance(event, MessageEvent)
    assert event.matched_url == "https://support.example.com/cases/1"


def test_space_membership_events() -> None:
    added = parse_interaction(load("added_to_space.json"))
    removed = parse_interaction(load("removed_from_space.json"))
    assert isinstance(added, AddedToSpaceEvent)
    assert isinstance(removed, RemovedFromSpaceEvent)
    assert added.space and added.space.name == "spaces/AAA"
    assert removed.actor and removed.actor.name == "users/123"


def test_bound_button_click_restores_the_handler_name() -> None:
    event = parse_interaction(load("button_clicked.json"))

    assert isinstance(event, ActionEvent)
    assert event.name == "case.assign"
    # The reserved routing parameter is not an application parameter.
    assert dict(event.parameters) == {"case_id": "42"}
    assert event.source is ActionSource.MESSAGE
    assert event.sender_type == "BOT"
    assert event.message and event.message.name == "spaces/AAA/messages/BOT"


def test_unbound_button_click_is_still_delivered() -> None:
    event = parse_interaction(load("button_clicked_unbound.json"))

    assert isinstance(event, ActionEvent)
    assert event.name == ""
    assert dict(event.parameters) == {"actionName": "assign"}


def test_dialog_button_clicks() -> None:
    request = parse_interaction(load("button_clicked_request_dialog.json"))
    submit = parse_interaction(load("button_clicked_submit_dialog.json"))

    assert isinstance(request, ActionEvent) and request.dialog
    assert request.dialog.type == DialogEventType.REQUEST_DIALOG
    assert request.source is ActionSource.DIALOG
    assert isinstance(submit, ActionEvent) and submit.dialog
    assert submit.dialog.type == DialogEventType.SUBMIT_DIALOG
    assert submit.form_inputs["contactName"] == StringInput(values=("Ada",))


def test_homepage_card_interactions() -> None:
    click = parse_interaction(load("button_clicked_home.json"))
    widget = parse_interaction(load("app_home_widget.json"))

    assert isinstance(click, ActionEvent)
    assert click.source is ActionSource.HOME
    assert click.name == "home.refresh"
    assert isinstance(widget, FormSubmitEvent)
    assert widget.function_name == "home.save"
    assert widget.form_inputs["theme"] == StringInput(values=("dark",))


def test_app_home_trigger_has_a_user_and_no_space() -> None:
    event = parse_interaction(load("app_home.json"))
    assert isinstance(event, AppHomeEvent)
    assert event.actor and event.actor.name == "users/123"
    assert event.space is None


def test_endpoint_url_is_not_a_homepage_handler_name() -> None:
    payload = load("app_home.json")
    cast(dict[str, object], payload["commonEventObject"])["invokedFunction"] = (
        ACTION_URL
    )
    assert isinstance(parse_interaction(payload), AppHomeEvent)


def test_widget_updated() -> None:
    event = parse_interaction(load("widget_updated.json"))
    assert isinstance(event, WidgetUpdatedEvent)
    assert event.function_name == "contacts.search"
    assert dict(event.parameters) == {"autocomplete_widget_query": "ad"}


def test_slash_command_arrives_as_an_app_command() -> None:
    event = parse_interaction(load("app_command_slash.json"))

    assert isinstance(event, CommandEvent)
    assert event.kind is CommandKind.SLASH_COMMAND
    # The documented int64 string becomes the numeric command id.
    assert event.command_id == 1
    assert event.message_text == "chattice"
    assert event.thread and event.thread.name == "spaces/AAA/threads/THR"


def test_quick_command_that_opens_a_dialog() -> None:
    event = parse_interaction(load("app_command_quick.json"))
    assert isinstance(event, CommandEvent)
    assert event.kind is CommandKind.QUICK_COMMAND
    assert event.command_id == 2
    assert event.dialog and event.dialog.type == DialogEventType.REQUEST_DIALOG


def test_system_command_cancel_stream() -> None:
    event = parse_interaction(load("system_command_cancel_stream.json"))
    assert isinstance(event, SystemCommandEvent)
    assert event.cancel_stream == "spaces/SPACE_ID/streamMessages/STREAM_ID"
    assert event.wire_format is WireFormat.ADDON


def test_unknown_trigger_becomes_an_unknown_event() -> None:
    event = parse_interaction(load("unknown_trigger.json"))
    assert isinstance(event, UnknownEvent)
    assert event.original_type == "futureTriggerPayload"
    assert event.actor and event.actor.name == "users/123"


def test_two_trigger_payloads_conflict() -> None:
    payload = load("message.json")
    chat = cast(dict[str, object], payload["chat"])
    chat["removedFromSpacePayload"] = {"space": {"name": "spaces/AAA"}}
    with pytest.raises(ConflictingEnvelopeError):
        parse_interaction(payload)


def test_families_cannot_be_mixed() -> None:
    payload = load("message.json")
    payload["type"] = "MESSAGE"
    with pytest.raises(UnsupportedEnvelopeError):
        parse_interaction(payload)


def test_malformed_event_objects_are_rejected() -> None:
    not_a_mapping: Any = load("message.json")
    not_a_mapping["chat"]["messagePayload"] = "not a mapping"
    bad_command_id: Any = load("app_command_slash.json")
    bad_command_id["chat"]["appCommandPayload"]["appCommandMetadata"][
        "appCommandId"
    ] = "one"
    empty_function: Any = load("button_clicked.json")
    empty_function["commonEventObject"]["parameters"][ADDON_FUNCTION_PARAMETER] = ""
    home_without_user: Any = load("app_home.json")
    del home_without_user["chat"]["user"]

    for payload in (not_a_mapping, bad_command_id, empty_function, home_without_user):
        with pytest.raises(InvalidInteractionPayload):
            parse_interaction(payload)


# --- action binding --------------------------------------------------------


def test_binding_puts_the_endpoint_in_function_and_the_name_in_a_parameter() -> None:
    bound = bind_addon_actions(_card(), ACTION_URL)

    button = bound.to_dict()["sections"][0]["widgets"][1]["buttonList"]["buttons"][0]
    action = button["onClick"]["action"]
    assert action["function"] == ACTION_URL
    assert {"key": "case_id", "value": "42"} in action["parameters"]
    assert {
        "key": ADDON_FUNCTION_PARAMETER,
        "value": "case.assign",
    } in action["parameters"]


def test_binding_is_idempotent_and_leaves_the_source_untouched() -> None:
    card = _card()
    once = bind_addon_actions(card, ACTION_URL)
    twice = bind_addon_actions(once, ACTION_URL)

    assert once.to_dict() == twice.to_dict()
    assert ACTION_URL not in json.dumps(card.to_dict())


def test_binding_rejects_the_reserved_parameter_and_a_non_https_url() -> None:
    reserved = {
        "function": "x",
        "parameters": [{"key": ADDON_FUNCTION_PARAMETER, "value": "y"}],
    }
    with pytest.raises(ValueError, match="reserved"):
        bind_addon_actions_json(reserved, ACTION_URL)
    with pytest.raises(ValueError, match="HTTPS"):
        bind_addon_actions(_card(), "http://bot.example.com/chat")


def test_a_bound_click_round_trips_to_the_same_handler_name() -> None:
    bound = bind_addon_actions(_card(), ACTION_URL).to_dict()
    action = bound["sections"][0]["widgets"][1]["buttonList"]["buttons"][0]["onClick"][
        "action"
    ]
    payload = load("button_clicked.json")
    payload["commonEventObject"] = {
        "invokedFunction": action["function"],
        "parameters": {item["key"]: item["value"] for item in action["parameters"]},
    }

    event = parse_interaction(payload)

    assert isinstance(event, ActionEvent)
    assert event.name == "case.assign"
    assert dict(event.parameters) == {"case_id": "42"}


# --- outbound: the add-on response family ----------------------------------


def _event(name: str) -> Event:
    return parse_interaction(load(name))


def test_text_reply_creates_a_message() -> None:
    assert serialize_response("pong", event=_event("message.json")) == {
        "hostAppDataAction": {
            "chatDataAction": {"createMessageAction": {"message": {"text": "pong"}}}
        }
    }


def test_card_reply_creates_a_message_with_bound_actions() -> None:
    body = cast(
        Any,
        serialize_response(
            _card(), event=_event("message.json"), addon_action_url=ACTION_URL
        ),
    )

    message = body["hostAppDataAction"]["chatDataAction"]["createMessageAction"][
        "message"
    ]
    card = message["cardsV2"][0]
    assert card["cardId"] == "card"
    assert ACTION_URL in json.dumps(card)
    assert ADDON_FUNCTION_PARAMETER in json.dumps(card)


def test_card_reply_without_an_action_url_is_left_as_authored() -> None:
    body = serialize_response(_card(), event=_event("message.json"))
    assert ADDON_FUNCTION_PARAMETER not in json.dumps(body)


def test_link_preview_card_updates_the_inline_preview() -> None:
    body = cast(
        Any, serialize_response(_card(), event=_event("message_matched_url.json"))
    )
    action = body["hostAppDataAction"]["chatDataAction"]
    assert list(action) == ["updateInlinePreviewAction"]
    assert action["updateInlinePreviewAction"]["cardsV2"][0]["cardId"] == "card"


def test_card_reply_to_a_click_follows_the_message_sender() -> None:
    bot = cast(Any, serialize_response(_card(), event=_event("button_clicked.json")))
    human = cast(
        Any,
        serialize_response(_card(), event=_event("button_clicked_human_message.json")),
    )

    assert (
        "cardsV2"
        in (
            bot["hostAppDataAction"]["chatDataAction"]["updateMessageAction"]["message"]
        )
    )
    assert (
        "cardsV2"
        in (human["hostAppDataAction"]["chatDataAction"]["updateInlinePreviewAction"])
    )


def test_card_reply_to_a_click_requires_the_sender_type() -> None:
    payload = load("button_clicked.json")
    chat = cast(Any, payload["chat"])
    del chat["buttonClickedPayload"]["message"]["sender"]
    with pytest.raises(TypeError, match="sender type"):
        serialize_response(_card(), event=parse_interaction(payload))


def test_dialog_is_pushed_as_a_card() -> None:
    dialog = Dialog(body=_card(function="contact.submit"))

    body = cast(
        Any,
        serialize_response(
            dialog,
            event=_event("button_clicked_request_dialog.json"),
            addon_action_url=ACTION_URL,
        ),
    )

    pushed = body["action"]["navigations"][0]["pushCard"]
    assert pushed["header"]["title"] == "Case 42"
    assert ACTION_URL in json.dumps(pushed)


def test_dialog_requires_an_event_that_can_open_one() -> None:
    with pytest.raises(TypeError, match="REQUEST_DIALOG"):
        serialize_response(Dialog(body=_card()), event=_event("message.json"))


def test_action_status_closes_the_dialog_with_a_notification() -> None:
    event = _event("button_clicked_submit_dialog.json")

    assert serialize_response(ActionStatus.ok(), event=event) == {
        "action": {"navigations": [{"endNavigation": {"action": "CLOSE_DIALOG"}}]}
    }
    assert serialize_response(ActionStatus.invalid("Name is missing"), event=event) == {
        "action": {
            "navigations": [{"endNavigation": {"action": "CLOSE_DIALOG"}}],
            "notification": {"text": "Name is missing"},
        }
    }
    with pytest.raises(TypeError, match="SUBMIT_DIALOG"):
        serialize_response(ActionStatus.ok(), event=_event("button_clicked.json"))


def test_homepage_card_is_pushed_then_updated() -> None:
    card = _card()

    opened = cast(Any, serialize_response(card, event=_event("app_home.json")))
    widget = cast(Any, serialize_response(card, event=_event("app_home_widget.json")))
    click = cast(
        Any, serialize_response(card, event=_event("button_clicked_home.json"))
    )

    assert list(opened["action"]["navigations"][0]) == ["pushCard"]
    assert list(widget["action"]["navigations"][0]) == ["updateCard"]
    assert list(click["action"]["navigations"][0]) == ["updateCard"]


def test_widget_suggestions() -> None:
    body = serialize_response(
        WidgetAutocomplete(widget_id="contacts", suggestions=("Ada", "Alan")),
        event=_event("widget_updated.json"),
    )
    assert body == {
        "action": {
            "modifyOperations": [
                {
                    "updateWidget": {
                        "selectionInputWidgetSuggestions": {
                            "suggestions": [
                                {"text": "Ada", "value": "Ada"},
                                {"text": "Alan", "value": "Alan"},
                            ]
                        }
                    }
                }
            ]
        }
    }
    with pytest.raises(TypeError, match="WIDGET_UPDATED"):
        serialize_response(
            WidgetAutocomplete(widget_id="contacts"), event=_event("message.json")
        )


def test_authorization_prompt_requires_the_resource_name() -> None:
    event = _event("message.json")
    url = "https://auth.example.com/start"

    assert serialize_response(
        RequestConfigResponse(auth_url=url, resource="Example Account"), event=event
    ) == {
        "basic_authorization_prompt": {
            "authorization_url": url,
            "resource": "Example Account",
        }
    }
    with pytest.raises(TypeError, match="resource"):
        serialize_response(RequestConfigResponse(auth_url=url), event=event)


def test_raw_and_dict_payloads_pass_through_unbound() -> None:
    event = _event("message.json")
    raw = {"action": {"navigations": [{"pushCard": _card().to_dict()}]}}

    assert serialize_response(raw, event=event, addon_action_url=ACTION_URL) is raw
    assert (
        serialize_response(
            RawInteractionResponse(raw), event=event, addon_action_url=ACTION_URL
        )
        is raw
    )


def test_removed_from_space_cannot_be_answered() -> None:
    with pytest.raises(TypeError, match="REMOVED_FROM_SPACE"):
        serialize_response("bye", event=_event("removed_from_space.json"))
    assert serialize_response(None, event=_event("removed_from_space.json")) is None


def test_unsupported_payload_type() -> None:
    with pytest.raises(TypeError, match="Unsupported"):
        serialize_response(object(), event=_event("message.json"))


def test_homepage_click_gets_the_app_home_capability() -> None:
    capabilities = ResponseCapabilities.resolve(
        transport="http", event=_event("button_clicked_home.json")
    )
    assert ResponseCapability.APP_HOME in capabilities
    assert ResponseCapability.CARD_UPDATE_BOT not in capabilities


# --- end to end through the HTTP route -------------------------------------


def _app(*, addon_action_url: str | None = ACTION_URL) -> FastAPI:
    router = Router()

    @router.message()
    async def on_message(message: MessageEvent) -> Card:
        return _card()

    @router.action("case.assign")
    async def assign(event: ActionEvent) -> str:
        return f"assigned {event.parameters['case_id']}"

    @router.command(F.command_id == 1)
    async def about(command: CommandEvent) -> str:
        return f"about {command.message_text}"

    @router.app_home()
    async def home(event: AppHomeEvent) -> Card:
        return _card(function="home.refresh")

    @router.system_command()
    async def stopped(event: SystemCommandEvent) -> None:
        return None

    dispatcher = Dispatcher(preview_features={PreviewFeature.MESSAGE_STREAMING})
    dispatcher.include_router(router)
    app = FastAPI()
    app.include_router(
        create_chat_router(
            dispatcher, MockVerifier(), addon_action_url=addon_action_url
        )
    )
    return app


async def _post(app: FastAPI, payload: dict[str, object]) -> httpx.Response:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        return await client.post("/", json=payload)


async def test_route_answers_an_addon_message_with_a_bound_card() -> None:
    result = await _post(_app(), load("message.json"))

    assert result.status_code == 200
    message = result.json()["hostAppDataAction"]["chatDataAction"][
        "createMessageAction"
    ]["message"]
    action = message["cardsV2"][0]["card"]["sections"][0]["widgets"][1]["buttonList"][
        "buttons"
    ][0]["onClick"]["action"]
    assert action["function"] == ACTION_URL


async def test_route_dispatches_a_bound_click_by_handler_name() -> None:
    result = await _post(_app(), load("button_clicked.json"))
    assert result.json() == {
        "hostAppDataAction": {
            "chatDataAction": {
                "createMessageAction": {"message": {"text": "assigned 42"}}
            }
        }
    }


async def test_route_dispatches_an_addon_slash_command() -> None:
    result = await _post(_app(), load("app_command_slash.json"))
    message = result.json()["hostAppDataAction"]["chatDataAction"][
        "createMessageAction"
    ]["message"]
    assert message == {"text": "about chattice"}


async def test_route_renders_the_homepage() -> None:
    result = await _post(_app(), load("app_home.json"))
    assert "pushCard" in result.json()["action"]["navigations"][0]


async def test_route_acknowledges_a_system_command_with_an_empty_200() -> None:
    result = await _post(_app(), load("system_command_cancel_stream.json"))
    assert result.status_code == 200
    assert result.content == b""


async def test_the_same_route_still_answers_chat_api_events() -> None:
    result = await _post(
        _app(),
        {
            "type": "MESSAGE",
            "message": {"text": "ping", "sender": {"type": "HUMAN"}},
            "user": {"name": "users/123"},
            "space": {"name": "spaces/AAA"},
        },
    )
    body = result.json()
    assert "cardsV2" in body
    # Chat API responses are never rewritten for the add-on endpoint.
    assert ACTION_URL not in json.dumps(body)


def test_route_rejects_a_non_https_action_url() -> None:
    with pytest.raises(ValueError, match="HTTPS"):
        create_chat_router(
            Dispatcher(), MockVerifier(), addon_action_url="http://bot.example.com"
        )
