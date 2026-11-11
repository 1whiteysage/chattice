# ruff: noqa: ASYNC109 — timeout kwarg mirrors the gapic client call convention
"""Message pin resource client: USER-only pin operations (ADR-012)."""

from __future__ import annotations

from google.apps.chat_v1 import ChatServiceAsyncClient
from google.apps.chat_v1.types.message_pin import (
    CreateMessagePinRequest,
    ListMessagePinsRequest,
    MessagePin,
)

from chattice.capabilities.operations import Operation
from chattice.client._names import (
    _canonical_message,
    _canonical_message_pin,
    _canonical_space,
)
from chattice.client.config import RequestConfig
from chattice.client.paging import Pager
from chattice.client.resources.base import ResourceClient, _effective_config
from chattice.events import SpaceRef

__all__ = ["MessagePins"]


class MessagePins(ResourceClient):
    """Curated message pin surface bound to one identity (ADR-012).

    USER-only: the registry has no APP auth path for message pins, so
    the APP root fails at preflight.
    """

    async def create(
        self,
        message: str,
        *,
        timeout: float | None = None,
        config: RequestConfig | None = None,
    ) -> MessagePin:
        """Pin ``message`` (canonical name) in its space."""
        target = _canonical_message(message)
        parent = target.rsplit("/messages/", 1)[0]
        request = CreateMessagePinRequest(
            parent=parent, message_pin=MessagePin(message=target)
        )
        effective = _effective_config(config, timeout)
        return await self._rpc(Operation.MESSAGE_PINS_CREATE, effective)(
            ChatServiceAsyncClient.create_message_pin, request=request
        )

    async def list(
        self,
        space: SpaceRef | str,
        *,
        page_size: int | None = None,
        timeout: float | None = None,
        config: RequestConfig | None = None,
    ) -> Pager[MessagePin]:
        """List the message pins of ``space``, one page at a time."""
        effective = _effective_config(config, timeout)
        request = ListMessagePinsRequest(parent=_canonical_space(space))
        if page_size is not None:
            request.page_size = page_size

        async def fetch() -> object:
            return await self._rpc(Operation.MESSAGE_PINS_LIST, effective)(
                ChatServiceAsyncClient.list_message_pins, request=request
            )

        return Pager(fetch=fetch)

    async def delete(
        self,
        name: str,
        *,
        timeout: float | None = None,
        config: RequestConfig | None = None,
    ) -> None:
        """Unpin by pin name or by the pinned message's name."""
        target = _canonical_message_pin(name)
        effective = _effective_config(config, timeout)
        await self._rpc(Operation.MESSAGE_PINS_DELETE, effective)(
            ChatServiceAsyncClient.delete_message_pin, name=target
        )
