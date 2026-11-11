"""Permissive Pydantic models for the untrusted Google boundary."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class _BoundaryModel(BaseModel):
    model_config = ConfigDict(extra="allow", strict=True, populate_by_name=True)


class UserModel(_BoundaryModel):
    name: str | None = None
    display_name: str | None = Field(default=None, alias="displayName")
    type: str | None = None


class SpaceModel(_BoundaryModel):
    name: str | None = None
    display_name: str | None = Field(default=None, alias="displayName")
    type: str | None = None
    space_type: str | None = Field(default=None, alias="spaceType")
    single_user_bot_dm: bool | None = Field(default=None, alias="singleUserBotDm")


class ThreadModel(_BoundaryModel):
    name: str | None = None
    thread_key: str | None = Field(default=None, alias="threadKey")


class SlashCommandModel(_BoundaryModel):
    command_id: str | None = Field(default=None, alias="commandId")


class MatchedUrlModel(_BoundaryModel):
    url: str | None = None


class MessageModel(_BoundaryModel):
    name: str | None = None
    text: str | None = None
    sender: UserModel | None = None
    space: SpaceModel | None = None
    thread: ThreadModel | None = None
    create_time: str | None = Field(default=None, alias="createTime")
    argument_text: str | None = Field(default=None, alias="argumentText")
    slash_command: SlashCommandModel | None = Field(default=None, alias="slashCommand")
    matched_url: MatchedUrlModel | None = Field(default=None, alias="matchedUrl")


class ActionParameterModel(_BoundaryModel):
    key: str
    value: str


class FormActionModel(_BoundaryModel):
    action_method_name: str | None = Field(default=None, alias="actionMethodName")
    parameters: list[ActionParameterModel] = Field(default_factory=list)


class TimeZoneModel(_BoundaryModel):
    id: str | None = None
    offset: int | None = None


class CommonEventModel(_BoundaryModel):
    user_locale: str | None = Field(default=None, alias="userLocale")
    time_zone: TimeZoneModel | None = Field(default=None, alias="timeZone")
    form_inputs: dict[str, dict[str, object]] = Field(
        default_factory=dict, alias="formInputs"
    )
    parameters: dict[str, str] = Field(default_factory=dict)
    invoked_function: str | None = Field(default=None, alias="invokedFunction")


class AppCommandMetadataModel(_BoundaryModel):
    app_command_id: int | None = Field(default=None, alias="appCommandId")
    app_command_type: str | None = Field(default=None, alias="appCommandType")


class CancelStreamModel(_BoundaryModel):
    stream_message: str | None = Field(default=None, alias="streamMessage")


class SystemCommandMetadataModel(_BoundaryModel):
    cancel_stream: CancelStreamModel | None = Field(default=None, alias="cancelStream")


class InteractionModel(_BoundaryModel):
    type: str
    event_time: str | None = Field(default=None, alias="eventTime")
    message: MessageModel | None = None
    user: UserModel | None = None
    thread: ThreadModel | None = None
    space: SpaceModel | None = None
    action: FormActionModel | None = None
    is_dialog_event: bool | None = Field(default=None, alias="isDialogEvent")
    dialog_event_type: str | None = Field(default=None, alias="dialogEventType")
    common: CommonEventModel | None = None
    app_command_metadata: AppCommandMetadataModel | None = Field(
        default=None, alias="appCommandMetadata"
    )
    system_command_metadata: SystemCommandMetadataModel | None = Field(
        default=None, alias="systemCommandMetadata"
    )


__all__ = ["InteractionModel"]
