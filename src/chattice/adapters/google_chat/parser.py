"""Pure mapping from validated Google interaction data to domain events."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import TypedDict

from pydantic import ValidationError

from chattice.events import (
    ActionEvent,
    ActionSource,
    AddedToSpaceEvent,
    AppHomeEvent,
    CommandEvent,
    CommandKind,
    DialogEventType,
    DialogMetadata,
    Event,
    FormInputs,
    FormSubmitEvent,
    MessageEvent,
    MessageRef,
    RemovedFromSpaceEvent,
    SpaceRef,
    SystemCommandEvent,
    ThreadRef,
    TimeZone,
    UnknownEvent,
    UserRef,
    WidgetUpdatedEvent,
    WireFormat,
)

from .envelope import normalize_envelope
from .exceptions import ConflictingEnvelopeError, InvalidInteractionPayload
from .inputs import parse_form_inputs
from .models import InteractionModel, SpaceModel, ThreadModel, UserModel


class _EventKwargs(TypedDict):
    raw: object
    event_time: datetime | None
    actor: UserRef | None
    space: SpaceRef | None
    thread: ThreadRef | None
    dialog: DialogMetadata | None
    locale: str | None
    timezone: TimeZone | None
    wire_format: WireFormat


@dataclass(frozen=True, slots=True)
class _Interaction:
    """One validated interaction plus the fields every event shares."""

    model: InteractionModel
    raw: dict[str, object]
    base: _EventKwargs

    @property
    def is_addon(self) -> bool:
        return self.base["wire_format"] is WireFormat.ADDON

    def require_actor_space(self, *, space_required: bool = True) -> None:
        missing_space = space_required and self.base["space"] is None
        if self.base["actor"] is None or missing_space:
            required = "user and space" if space_required else "user"
            raise InvalidInteractionPayload(f"{self.model.type} requires {required}")


def parse_interaction(payload: Mapping[str, object]) -> Event:
    """Parse a documented Google Chat interaction mapping into a domain event."""
    envelope = normalize_envelope(payload)
    try:
        model = InteractionModel.model_validate(envelope.event)
    except ValidationError as error:
        raise InvalidInteractionPayload(
            f"Invalid Google Chat interaction payload: {error}"
        ) from error

    if model.type in {"UNSPECIFIED", "TYPE_UNSPECIFIED"}:
        raise InvalidInteractionPayload("UNSPECIFIED is not an interaction event")

    message = model.message
    space = _space(model.space or (message.space if message else None))
    common = model.common
    base: _EventKwargs = {
        "raw": envelope.raw,
        "event_time": _timestamp(model.event_time),
        "actor": _user(model.user or (message.sender if message else None)),
        "space": space,
        "thread": _thread(
            model.thread or (message.thread if message else None), space=space
        ),
        "dialog": _dialog(model.is_dialog_event, model.dialog_event_type),
        "locale": common.user_locale if common else None,
        "timezone": (
            TimeZone(id=common.time_zone.id, offset_ms=common.time_zone.offset)
            if common and common.time_zone
            else None
        ),
        "wire_format": envelope.wire_format,
    }
    build = _BUILDERS.get(model.type)
    if build is None:
        return UnknownEvent(original_type=model.type, **base)
    return build(_Interaction(model=model, raw=envelope.raw, base=base))


def _message_event(interaction: _Interaction) -> Event:
    message = interaction.model.message
    if message is None:
        raise InvalidInteractionPayload("MESSAGE requires a message object")
    # Slash commands arrive as MESSAGE events with message.slashCommand
    # (documented command guide): route them to the SAME CommandEvent
    # family as APP_COMMAND quick commands.
    if message.slash_command is not None:
        return _slash_command_event(interaction.model, interaction.base)
    if message.text is None:
        raise InvalidInteractionPayload("MESSAGE requires message.text")
    return MessageEvent(
        text=message.text,
        message=MessageRef(name=message.name),
        matched_url=message.matched_url.url if message.matched_url else None,
        sender_type=message.sender.type if message.sender else None,
        argument_text=_argument_text(message.argument_text),
        **interaction.base,
    )


def _added_to_space_event(interaction: _Interaction) -> Event:
    interaction.require_actor_space()
    return AddedToSpaceEvent(**interaction.base)


def _removed_from_space_event(interaction: _Interaction) -> Event:
    interaction.require_actor_space()
    return RemovedFromSpaceEvent(**interaction.base)


def _system_command_event(interaction: _Interaction) -> Event:
    # Developer Preview (message streaming). Metadata this version
    # does not model stays reachable through ``raw``.
    metadata = interaction.model.system_command_metadata
    cancel = metadata.cancel_stream if metadata else None
    return SystemCommandEvent(
        cancel_stream=cancel.stream_message if cancel else None, **interaction.base
    )


def _app_home_event(interaction: _Interaction) -> Event:
    # The add-on App Home trigger carries the user and no space.
    interaction.require_actor_space(space_required=not interaction.is_addon)
    return AppHomeEvent(**interaction.base)


def _card_clicked_event(interaction: _Interaction) -> Event:
    model = interaction.model
    parameters, form_inputs, function_name = _common_action(model)
    # An HTTP add-on action is addressed by endpoint URL; a card that
    # was not bound to a handler name still reaches handlers, which
    # can route on its parameters.
    if not function_name and not interaction.is_addon:
        raise InvalidInteractionPayload(
            "CARD_CLICKED requires common.invokedFunction or action.actionMethodName"
        )
    message = model.message
    return ActionEvent(
        name=function_name,
        parameters=parameters,
        form_inputs=form_inputs,
        sender_type=message.sender.type if message and message.sender else None,
        message=MessageRef(name=message.name) if message and message.name else None,
        source=_action_source(interaction.raw, model, interaction.base["dialog"]),
        **interaction.base,
    )


def _widget_updated_event(interaction: _Interaction) -> Event:
    parameters, form_inputs, function_name = _common_action(interaction.model)
    if not function_name and not interaction.is_addon:
        raise InvalidInteractionPayload(
            "WIDGET_UPDATED requires an associated invoked function"
        )
    return WidgetUpdatedEvent(
        function_name=function_name,
        parameters=parameters,
        form_inputs=form_inputs,
        **interaction.base,
    )


def _app_command_event(interaction: _Interaction) -> Event:
    model = interaction.model
    metadata = model.app_command_metadata
    if (
        metadata is None
        or metadata.app_command_id is None
        or metadata.app_command_type is None
    ):
        raise InvalidInteractionPayload(
            "APP_COMMAND requires appCommandMetadata ID and type"
        )
    kind = _app_command_kind(metadata.app_command_type, is_addon=interaction.is_addon)
    message = model.message
    return CommandEvent(
        command_id=metadata.app_command_id,
        command_type=metadata.app_command_type,
        source_kind=metadata.app_command_type,
        kind=kind,
        message_text=_command_text(model, kind),
        target_message=(
            MessageRef(name=message.name)
            if kind is CommandKind.MESSAGE_ACTION
            and message is not None
            and message.name is not None
            else None
        ),
        **interaction.base,
    )


def _form_submit_event(interaction: _Interaction) -> Event:
    parameters, form_inputs, function_name = _common_action(interaction.model)
    interaction.require_actor_space(space_required=not interaction.is_addon)
    return FormSubmitEvent(
        function_name=function_name,
        parameters=parameters,
        form_inputs=form_inputs,
        **interaction.base,
    )


# Every other type is delivered as an UnknownEvent.
_BUILDERS: dict[str, Callable[[_Interaction], Event]] = {
    "MESSAGE": _message_event,
    "ADDED_TO_SPACE": _added_to_space_event,
    "REMOVED_FROM_SPACE": _removed_from_space_event,
    "CARD_CLICKED": _card_clicked_event,
    "WIDGET_UPDATED": _widget_updated_event,
    "APP_COMMAND": _app_command_event,
    "APP_HOME": _app_home_event,
    "SUBMIT_FORM": _form_submit_event,
    "SYSTEM_COMMAND": _system_command_event,
}


def _timestamp(value: str | None) -> datetime | None:
    if value is None:
        return None
    try:
        normalized = value[:-1] + "+00:00" if value.endswith("Z") else value
        result = datetime.fromisoformat(normalized)
    except ValueError as error:
        raise InvalidInteractionPayload(
            f"Invalid eventTime timestamp: {value!r}"
        ) from error
    if result.tzinfo is None or result.utcoffset() is None:
        raise InvalidInteractionPayload("eventTime must include a timezone offset")
    return result


def _user(value: UserModel | None) -> UserRef | None:
    if value is None:
        return None
    return UserRef(name=value.name, display_name=value.display_name, type=value.type)


def _space(value: SpaceModel | None) -> SpaceRef | None:
    if value is None:
        return None
    return SpaceRef(
        name=value.name,
        display_name=value.display_name,
        type=value.type,
        space_type=value.space_type,
        single_user_bot_dm=value.single_user_bot_dm,
    )


def _thread(
    value: ThreadModel | None, *, space: SpaceRef | None = None
) -> ThreadRef | None:
    if value is None:
        return None
    return ThreadRef(name=value.name, thread_key=value.thread_key, space=space)


def _dialog(is_dialog: bool | None, type_: str | None) -> DialogMetadata | None:
    if type_ is None:
        if is_dialog is True:
            raise InvalidInteractionPayload(
                "isDialogEvent=true requires a dialogEventType"
            )
        return None
    if is_dialog is False:
        # contradictory envelope — a dialog type without the dialog
        # event flag is malformed input, not a normal interaction.
        raise InvalidInteractionPayload(
            "dialogEventType present requires isDialogEvent=true"
        )
    try:
        normalized: DialogEventType | str = DialogEventType(type_)
    except ValueError:
        normalized = type_
    return DialogMetadata(type=normalized, is_dialog_event=True)


def _action_source(
    raw: Mapping[str, object],
    model: InteractionModel,
    dialog: DialogMetadata | None,
) -> ActionSource | None:
    """Derive only source facts the official envelope makes unambiguous."""
    if dialog is not None:
        return ActionSource.DIALOG
    chat = raw.get("chat")
    if isinstance(chat, Mapping) and "type" not in chat:
        # Add-on event object: every interaction is under ``chat``, so
        # the clicked message is what tells a message from the homepage.
        return ActionSource.MESSAGE if model.message is not None else ActionSource.HOME
    if isinstance(chat, Mapping):
        return ActionSource.HOME
    if model.message is not None:
        return ActionSource.MESSAGE
    return None


def _app_command_kind(value: str, *, is_addon: bool = False) -> CommandKind | None:
    # In Chat API interaction events slash commands have a different
    # documented wire family (MESSAGE + message.slashCommand), so
    # APP_COMMAND/SLASH_COMMAND is retained in raw/source_kind but not
    # promoted into typed routing. Add-on event objects deliver slash
    # commands as an app command, so there it is the typed route.
    if value == CommandKind.QUICK_COMMAND:
        return CommandKind.QUICK_COMMAND
    if value == CommandKind.MESSAGE_ACTION:
        return CommandKind.MESSAGE_ACTION
    if is_addon and value == CommandKind.SLASH_COMMAND:
        return CommandKind.SLASH_COMMAND
    return None


def _command_text(model: InteractionModel, kind: CommandKind | None) -> str | None:
    """Slash commands expose the mention-stripped argument text."""
    message = model.message
    if message is None:
        return None
    if kind is CommandKind.SLASH_COMMAND:
        argument_text = _argument_text(message.argument_text)
        if argument_text is not None:
            return argument_text
    return message.text


def _common_action(
    model: InteractionModel,
) -> tuple[dict[str, str], FormInputs, str]:
    common_parameters = dict(model.common.parameters) if model.common else {}
    common_function = model.common.invoked_function if model.common else None
    raw_inputs = model.common.form_inputs if model.common else {}
    form_inputs = parse_form_inputs(raw_inputs)

    fallback_parameters: dict[str, str] = {}
    fallback_function = None
    if model.action:
        fallback_function = model.action.action_method_name
        for item in model.action.parameters:
            if item.key in fallback_parameters:
                raise InvalidInteractionPayload(
                    f"Duplicate action parameter {item.key!r}"
                )
            fallback_parameters[item.key] = item.value
    if (
        common_parameters
        and fallback_parameters
        and common_parameters != fallback_parameters
    ):
        raise ConflictingEnvelopeError(
            "common.parameters conflicts with action.parameters"
        )
    if common_function and fallback_function and common_function != fallback_function:
        raise ConflictingEnvelopeError(
            "common.invokedFunction conflicts with action.actionMethodName"
        )
    return (
        common_parameters or fallback_parameters,
        form_inputs,
        common_function or fallback_function or "",
    )


def _argument_text(value: str | None) -> str | None:
    """Normalize Google's mention-stripped argumentText without parsing text."""
    if value is None:
        return None
    return value.strip()


def _slash_command_event(model: InteractionModel, base: _EventKwargs) -> CommandEvent:
    """A documented slash command: MESSAGE + message.slashCommand.

    The command id travels as an int64 string; argumentText is the
    mention-stripped body (message.text is the raw body).
    """
    message = model.message
    assert message is not None and message.slash_command is not None
    raw_id = message.slash_command.command_id
    if raw_id is None:
        raise InvalidInteractionPayload("MESSAGE slashCommand requires commandId")
    try:
        command_id = int(raw_id)
    except ValueError as error:
        raise InvalidInteractionPayload(
            f"slashCommand commandId is not an int64 string: {raw_id!r}"
        ) from error
    argument_text = _argument_text(message.argument_text)
    return CommandEvent(
        command_id=command_id,
        command_type=None,
        source_kind=CommandKind.SLASH_COMMAND,
        kind=CommandKind.SLASH_COMMAND,
        message_text=argument_text if argument_text is not None else message.text,
        **base,
    )


__all__ = ["parse_interaction"]
