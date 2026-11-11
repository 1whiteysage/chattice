# ruff: noqa: ASYNC109 — timeout kwarg mirrors the gapic client call convention
"""Per-user state clients: USER-only (ADR-012).

Read state, thread read state, and notification settings mirror the
official ``users.spaces.*`` surface and live in this module. The
``Users`` namespace also exposes :class:`Availability` (presence and
custom status) and :class:`Sections` (sidebar sections), which add
``users/me`` defaults, local validation, and paging over the SDK.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from typing import TYPE_CHECKING

from google.apps.chat_v1 import ChatServiceAsyncClient
from google.apps.chat_v1.types.space_notification_setting import (
    SpaceNotificationSetting,
)
from google.apps.chat_v1.types.space_read_state import SpaceReadState
from google.apps.chat_v1.types.thread_read_state import (
    ThreadReadState as ThreadReadStateProto,
)
from google.protobuf import field_mask_pb2  # type: ignore[import-untyped]

from chattice.auth import AuthMode
from chattice.capabilities.operations import Operation
from chattice.client._names import _user_space_state, _user_thread_read_state
from chattice.client.config import RequestConfig
from chattice.client.resources.availability import Availability
from chattice.client.resources.base import ResourceClient, _effective_config
from chattice.client.resources.sections import Sections
from chattice.events import SpaceRef, ThreadRef

if TYPE_CHECKING:
    from chattice.client.bot import Bot

__all__ = ["Users"]


class ReadState(ResourceClient):
    """Space read state for the current user."""

    async def get(
        self,
        name: SpaceRef | str,
        *,
        timeout: float | None = None,
        config: RequestConfig | None = None,
    ) -> SpaceReadState:
        """Get the calling user's read state of a space.

        ``name`` is the space (``spaces/{id}``, a bare id, or a
        ``SpaceRef``) or the full
        ``users/{user}/spaces/{space}/spaceReadState`` resource name.
        """
        effective = _effective_config(config, timeout)
        return await self._rpc(Operation.SPACE_READ_STATE_GET, effective)(
            ChatServiceAsyncClient.get_space_read_state,
            name=_user_space_state(name, "spaceReadState"),
        )

    async def update(
        self,
        name: SpaceRef | str,
        *,
        last_read_time: datetime | None,
        timeout: float | None = None,
        config: RequestConfig | None = None,
    ) -> SpaceReadState:
        """Update the calling user's last-read timestamp of a space.

        ``name`` is the space or the full read-state resource name (see
        ``get``). ``last_read_time=None`` clears the read state (marks
        unread).
        """
        effective = _effective_config(config, timeout)
        # proto-plus converts datetime <-> Timestamp transparently.
        state = SpaceReadState(
            name=_user_space_state(name, "spaceReadState"),
            last_read_time=last_read_time,
        )
        mask = field_mask_pb2.FieldMask(paths=["last_read_time"])
        return await self._rpc(Operation.SPACE_READ_STATE_UPDATE, effective)(
            ChatServiceAsyncClient.update_space_read_state,
            space_read_state=state,
            update_mask=mask,
        )


class ThreadReadState(ResourceClient):
    """Thread read state for the current user."""

    async def get(
        self,
        name: ThreadRef | str,
        *,
        timeout: float | None = None,
        config: RequestConfig | None = None,
    ) -> ThreadReadStateProto:
        """Get the calling user's read state of a thread.

        ``name`` is the thread (``spaces/{space}/threads/{thread}`` or a
        ``ThreadRef``) or the full ``.../threadReadState`` resource name.
        """
        effective = _effective_config(config, timeout)
        return await self._rpc(Operation.THREAD_READ_STATE_GET, effective)(
            ChatServiceAsyncClient.get_thread_read_state,
            name=_user_thread_read_state(name),
        )


class NotificationSetting(ResourceClient):
    """Space notification settings for the current user."""

    async def get(
        self,
        name: SpaceRef | str,
        *,
        timeout: float | None = None,
        config: RequestConfig | None = None,
    ) -> SpaceNotificationSetting:
        """Get the calling user's notification settings of a space.

        ``name`` is the space (``spaces/{id}``, a bare id, or a
        ``SpaceRef``) or the full
        ``users/{user}/spaces/{space}/spaceNotificationSetting`` name.
        """
        effective = _effective_config(config, timeout)
        return await self._rpc(Operation.NOTIFICATION_SETTING_GET, effective)(
            ChatServiceAsyncClient.get_space_notification_setting,
            name=_user_space_state(name, "spaceNotificationSetting"),
        )

    async def update(
        self,
        name: SpaceRef | str,
        *,
        setting: SpaceNotificationSetting,
        update_mask: Sequence[str],
        timeout: float | None = None,
        config: RequestConfig | None = None,
    ) -> SpaceNotificationSetting:
        """Patch the calling user's notification settings of a space.

        ``name`` is the space or the full resource name (see ``get``).
        ``setting`` is not modified.
        """
        effective = _effective_config(config, timeout)
        setting = SpaceNotificationSetting(setting)
        setting.name = _user_space_state(name, "spaceNotificationSetting")
        mask = field_mask_pb2.FieldMask(paths=list(update_mask))
        return await self._rpc(Operation.NOTIFICATION_SETTING_UPDATE, effective)(
            ChatServiceAsyncClient.update_space_notification_setting,
            space_notification_setting=setting,
            update_mask=mask,
        )


class Users:
    """Namespace of USER-only per-user state clients (ADR-012)."""

    def __init__(self, bot: Bot, identity: AuthMode) -> None:
        self._bot = bot
        self._identity = identity

    @property
    def read_state(self) -> ReadState:
        """Space read state operations."""
        return ReadState(self._bot, self._identity)

    @property
    def thread_read_state(self) -> ThreadReadState:
        """Thread read state operations."""
        return ThreadReadState(self._bot, self._identity)

    @property
    def notification_setting(self) -> NotificationSetting:
        """Space notification setting operations."""
        return NotificationSetting(self._bot, self._identity)

    @property
    def availability(self) -> Availability:
        """Presence state and custom status operations."""
        return Availability(self._bot, self._identity)

    @property
    def sections(self) -> Sections:
        """Sidebar section operations."""
        return Sections(self._bot, self._identity)
