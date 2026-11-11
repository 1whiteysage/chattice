# ruff: noqa: ASYNC109 — timeout kwarg mirrors the gapic client call convention
"""Availability resource client: the calling user's presence (ADR-012).

USER-only, and Google only lets a caller read or change their own
availability, so every method targets ``users/me`` unless ``user``
names the same person by ID or email.
"""

from __future__ import annotations

from datetime import datetime, timedelta

from google.apps.chat_v1 import ChatServiceAsyncClient
from google.apps.chat_v1.types.availability import (
    Availability as AvailabilityProto,
)
from google.apps.chat_v1.types.availability import (
    CustomStatus,
    MarkAsActiveRequest,
    MarkAsDoNotDisturbRequest,
)
from google.apps.chat_v1.types.reaction import Emoji
from google.protobuf import field_mask_pb2  # type: ignore[import-untyped]

from chattice.capabilities.operations import Operation
from chattice.client._names import _canonical_user
from chattice.client.config import RequestConfig
from chattice.client.errors import ChatAPIError
from chattice.client.resources.base import ResourceClient, _effective_config
from chattice.events import UserRef

__all__ = ["Availability"]

_MAX_STATUS_TEXT = 64


def _availability_name(user: UserRef | str) -> str:
    return f"{_canonical_user(user, parameter='user')}/availability"


def _check_expiration(ttl: timedelta | None, expire_time: datetime | None) -> None:
    if ttl is not None and expire_time is not None:
        raise ChatAPIError("pass either ttl or expire_time, not both")
    if ttl is not None and ttl <= timedelta(0):
        raise ChatAPIError("ttl must be a positive duration")


class Availability(ResourceClient):
    """Presence state and custom status of the calling user."""

    async def get(
        self,
        user: UserRef | str = "me",
        *,
        timeout: float | None = None,
        config: RequestConfig | None = None,
    ) -> AvailabilityProto:
        """Get the user's state, Do Not Disturb metadata, and custom status."""
        name = _availability_name(user)
        effective = _effective_config(config, timeout)
        return await self._rpc(Operation.AVAILABILITY_GET, effective)(
            ChatServiceAsyncClient.get_availability, name=name
        )

    async def set_custom_status(
        self,
        text: str,
        *,
        emoji: str,
        ttl: timedelta | None = None,
        expire_time: datetime | None = None,
        user: UserRef | str = "me",
        timeout: float | None = None,
        config: RequestConfig | None = None,
    ) -> AvailabilityProto:
        """Set the custom status: up to 64 characters and a Unicode emoji.

        The status is the only availability field Google lets a caller
        update directly; ``ttl`` or ``expire_time`` bounds its lifetime.
        """
        if not text or not text.strip():
            raise ChatAPIError("custom status text must be a non-empty string")
        if len(text) > _MAX_STATUS_TEXT:
            raise ChatAPIError(
                f"custom status text is limited to {_MAX_STATUS_TEXT} "
                f"characters; got {len(text)}"
            )
        if not emoji or emoji.isascii():
            raise ChatAPIError(
                "custom status emoji must be a Unicode emoji; custom emojis "
                "are not supported by Google here"
            )
        _check_expiration(ttl, expire_time)
        status = CustomStatus(text=text, emoji=Emoji(unicode=emoji))
        if ttl is not None:
            status.ttl = ttl
        if expire_time is not None:
            status.expire_time = expire_time
        availability = AvailabilityProto(
            name=_availability_name(user), custom_status=status
        )
        mask = field_mask_pb2.FieldMask(paths=["custom_status"])
        effective = _effective_config(config, timeout)
        return await self._rpc(Operation.AVAILABILITY_UPDATE, effective)(
            ChatServiceAsyncClient.update_availability,
            availability=availability,
            update_mask=mask,
        )

    async def mark_active(
        self,
        *,
        ttl: timedelta | None = None,
        expire_time: datetime | None = None,
        user: UserRef | str = "me",
        timeout: float | None = None,
        config: RequestConfig | None = None,
    ) -> AvailabilityProto:
        """Mark the user ACTIVE until the expiration, then AWAY."""
        _check_expiration(ttl, expire_time)
        request = MarkAsActiveRequest(name=_availability_name(user))
        if ttl is not None:
            request.ttl = ttl
        if expire_time is not None:
            request.expire_time = expire_time
        effective = _effective_config(config, timeout)
        return await self._rpc(Operation.AVAILABILITY_MARK_ACTIVE, effective)(
            ChatServiceAsyncClient.mark_as_active, request=request
        )

    async def mark_away(
        self,
        *,
        user: UserRef | str = "me",
        timeout: float | None = None,
        config: RequestConfig | None = None,
    ) -> AvailabilityProto:
        """Mark the user AWAY regardless of their activity."""
        name = _availability_name(user)
        effective = _effective_config(config, timeout)
        return await self._rpc(Operation.AVAILABILITY_MARK_AWAY, effective)(
            ChatServiceAsyncClient.mark_as_away, request={"name": name}
        )

    async def mark_do_not_disturb(
        self,
        *,
        ttl: timedelta | None = None,
        expire_time: datetime | None = None,
        user: UserRef | str = "me",
        timeout: float | None = None,
        config: RequestConfig | None = None,
    ) -> AvailabilityProto:
        """Mark the user DO_NOT_DISTURB until the expiration."""
        _check_expiration(ttl, expire_time)
        request = MarkAsDoNotDisturbRequest(name=_availability_name(user))
        if ttl is not None:
            request.ttl = ttl
        if expire_time is not None:
            request.expire_time = expire_time
        effective = _effective_config(config, timeout)
        return await self._rpc(Operation.AVAILABILITY_MARK_DO_NOT_DISTURB, effective)(
            ChatServiceAsyncClient.mark_as_do_not_disturb, request=request
        )
