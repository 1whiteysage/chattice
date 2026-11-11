"""Typed event builders for tests (no raw Google JSON required)."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime

from chattice.events import (
    ActionEvent,
    AddedToSpaceEvent,
    AppHomeEvent,
    DialogMetadata,
    FormInputs,
    FormSubmitEvent,
    MessageEvent,
    RemovedFromSpaceEvent,
    SpaceRef,
    SystemCommandEvent,
    ThreadRef,
    UnknownEvent,
    UserRef,
)
from chattice.workspace_events import WorkspaceEvent

__all__ = ["EventFactory"]

_TEST_USER = UserRef(name="users/test", display_name="Test User")
_TEST_SPACE = SpaceRef(name="spaces/test", display_name="Test Space")


def _user(user: UserRef | str | None) -> UserRef:
    """Coerce a resource name or ref to the default test user."""
    if user is None:
        return _TEST_USER
    if isinstance(user, str):
        return UserRef(name=user)
    return user


def _space(space: SpaceRef | str | None) -> SpaceRef:
    """Coerce a resource name or ref to the default test space."""
    if space is None:
        return _TEST_SPACE
    if isinstance(space, str):
        return SpaceRef(name=space)
    return space


class EventFactory:
    """Static builders producing frozen domain events directly.

    ``user``/``space`` accept either a reference or a Google resource name
    string (e.g. ``"users/user-a"``); ``None`` uses the test defaults.
    """

    @staticmethod
    def message(
        text: str,
        *,
        user: UserRef | str | None = None,
        space: SpaceRef | str | None = None,
        thread: ThreadRef | None = None,
        event_time: datetime | None = None,
    ) -> MessageEvent:
        """Build a chat message event."""
        return MessageEvent(
            text=text,
            event_time=event_time,
            actor=_user(user),
            space=_space(space),
            thread=thread,
        )

    @staticmethod
    def action(
        name: str,
        parameters: Mapping[str, object] | None = None,
        *,
        form_inputs: FormInputs | None = None,
        user: UserRef | str | None = None,
        space: SpaceRef | str | None = None,
        thread: ThreadRef | None = None,
        dialog: DialogMetadata | None = None,
        event_time: datetime | None = None,
    ) -> ActionEvent:
        """Build a named action event."""
        return ActionEvent(
            name=name,
            parameters=parameters if parameters is not None else {},
            form_inputs=form_inputs if form_inputs is not None else FormInputs(),
            event_time=event_time,
            actor=_user(user),
            space=_space(space),
            thread=thread,
            dialog=dialog,
        )

    @staticmethod
    def added_to_space(
        *,
        user: UserRef | str | None = None,
        space: SpaceRef | str | None = None,
        thread: ThreadRef | None = None,
        event_time: datetime | None = None,
    ) -> AddedToSpaceEvent:
        """Build an app-added-to-space event."""
        return AddedToSpaceEvent(
            event_time=event_time,
            actor=_user(user),
            space=_space(space),
            thread=thread,
        )

    @staticmethod
    def removed_from_space(
        *,
        user: UserRef | str | None = None,
        space: SpaceRef | str | None = None,
        thread: ThreadRef | None = None,
        event_time: datetime | None = None,
    ) -> RemovedFromSpaceEvent:
        """Build an app-removed-from-space event."""
        return RemovedFromSpaceEvent(
            event_time=event_time,
            actor=_user(user),
            space=_space(space),
            thread=thread,
        )

    @staticmethod
    def system_command(
        *,
        cancel_stream: str | None = None,
        user: UserRef | str | None = None,
        space: SpaceRef | str | None = None,
        event_time: datetime | None = None,
    ) -> SystemCommandEvent:
        """Build a system command event (stream cancellation)."""
        return SystemCommandEvent(
            cancel_stream=cancel_stream,
            event_time=event_time,
            actor=_user(user),
            space=_space(space),
        )

    @staticmethod
    def app_home(
        *,
        user: UserRef | str | None = None,
        space: SpaceRef | str | None = None,
        thread: ThreadRef | None = None,
        event_time: datetime | None = None,
    ) -> AppHomeEvent:
        """Build an App Home open event."""
        return AppHomeEvent(
            event_time=event_time,
            actor=_user(user),
            space=_space(space),
            thread=thread,
        )

    @staticmethod
    def form_submit(
        function_name: str,
        *,
        parameters: Mapping[str, str] | None = None,
        form_inputs: FormInputs | None = None,
        user: UserRef | str | None = None,
        space: SpaceRef | str | None = None,
        thread: ThreadRef | None = None,
        event_time: datetime | None = None,
    ) -> FormSubmitEvent:
        """Build a form submission event from App Home."""
        return FormSubmitEvent(
            function_name=function_name,
            parameters=parameters if parameters is not None else {},
            form_inputs=form_inputs if form_inputs is not None else FormInputs(),
            event_time=event_time,
            actor=_user(user),
            space=_space(space),
            thread=thread,
        )

    @staticmethod
    def workspace_event(
        cloud_type: str,
        *,
        event_id: str = "evt-test",
        source: str = "//chat.googleapis.com/test",
        subject: str | None = None,
        event_time: datetime | None = None,
        data: Mapping[str, object] | None = None,
    ) -> WorkspaceEvent:
        """Build a Workspace resource-change event."""
        return WorkspaceEvent(
            event_id=event_id,
            source=source,
            subject=subject,
            event_time=event_time,
            data=data if data is not None else {},
            cloud_type=cloud_type,
        )

    @staticmethod
    def unknown_event(
        original_type: str,
        *,
        user: UserRef | str | None = None,
        space: SpaceRef | str | None = None,
        thread: ThreadRef | None = None,
        event_time: datetime | None = None,
    ) -> UnknownEvent:
        """Build an event of an unrecognized external type."""
        return UnknownEvent(
            original_type=original_type,
            event_time=event_time,
            actor=_user(user),
            space=_space(space),
            thread=thread,
        )
