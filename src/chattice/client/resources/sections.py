# ruff: noqa: ASYNC109 — timeout kwarg mirrors the gapic client call convention
"""Section resource client: the calling user's sidebar sections (ADR-012).

USER-only. Sections group the conversations in a person's Chat
navigation panel; only custom sections can be created, renamed, or
deleted, and only spaces can be section items.
"""

from __future__ import annotations

import re
from typing import Literal

from google.apps.chat_v1 import ChatServiceAsyncClient
from google.apps.chat_v1.types.section import (
    CreateSectionRequest,
    ListSectionItemsRequest,
    ListSectionsRequest,
    MoveSectionItemRequest,
    PositionSectionRequest,
    Section,
    SectionItem,
)
from google.protobuf import field_mask_pb2  # type: ignore[import-untyped]

from chattice.capabilities.operations import Operation
from chattice.client._names import _canonical_space, _canonical_user
from chattice.client.config import RequestConfig
from chattice.client.errors import ChatAPIError
from chattice.client.paging import Pager
from chattice.client.resources.base import ResourceClient, _effective_config
from chattice.events import SpaceRef, UserRef

__all__ = ["Sections"]

_SECTION_NAME = re.compile(r"users/[^/]+/sections/[^/]+")
_ITEM_NAME = re.compile(r"users/[^/]+/sections/[^/]+/items/[^/]+")
_MAX_DISPLAY_NAME = 80


def _section_name(name: str) -> str:
    value = name.strip() if isinstance(name, str) else ""
    if _SECTION_NAME.fullmatch(value) is None:
        raise ChatAPIError(
            "section must be a canonical "
            f"'users/{{user}}/sections/{{section}}' resource name; got {name!r}"
        )
    return value


def _display_name(value: str) -> str:
    if not value or not value.strip():
        raise ChatAPIError("display_name must be a non-empty string")
    if len(value) > _MAX_DISPLAY_NAME:
        raise ChatAPIError(
            f"display_name is limited to {_MAX_DISPLAY_NAME} characters; "
            f"got {len(value)}"
        )
    return value


class Sections(ResourceClient):
    """Sidebar sections and their items for the calling user."""

    async def create(
        self,
        display_name: str,
        *,
        user: UserRef | str = "me",
        timeout: float | None = None,
        config: RequestConfig | None = None,
    ) -> Section:
        """Create a custom section named ``display_name``."""
        request = CreateSectionRequest(
            parent=_canonical_user(user, parameter="user"),
            section=Section(
                display_name=_display_name(display_name),
                type_=Section.SectionType.CUSTOM_SECTION,
            ),
        )
        effective = _effective_config(config, timeout)
        return await self._rpc(Operation.SECTIONS_CREATE, effective)(
            ChatServiceAsyncClient.create_section, request=request
        )

    async def list(
        self,
        *,
        user: UserRef | str = "me",
        page_size: int | None = None,
        timeout: float | None = None,
        config: RequestConfig | None = None,
    ) -> Pager[Section]:
        """List the user's system and custom sections, one page at a time."""
        effective = _effective_config(config, timeout)
        request = ListSectionsRequest(parent=_canonical_user(user, parameter="user"))
        if page_size is not None:
            request.page_size = page_size

        async def fetch() -> object:
            return await self._rpc(Operation.SECTIONS_LIST, effective)(
                ChatServiceAsyncClient.list_sections, request=request
            )

        return Pager(fetch=fetch)

    async def update(
        self,
        name: str,
        *,
        display_name: str,
        timeout: float | None = None,
        config: RequestConfig | None = None,
    ) -> Section:
        """Rename a custom section; the name is its only updatable field."""
        section = Section(
            name=_section_name(name), display_name=_display_name(display_name)
        )
        mask = field_mask_pb2.FieldMask(paths=["display_name"])
        effective = _effective_config(config, timeout)
        return await self._rpc(Operation.SECTIONS_UPDATE, effective)(
            ChatServiceAsyncClient.update_section, section=section, update_mask=mask
        )

    async def delete(
        self,
        name: str,
        *,
        timeout: float | None = None,
        config: RequestConfig | None = None,
    ) -> None:
        """Delete a custom section; its items move to the default sections."""
        target = _section_name(name)
        effective = _effective_config(config, timeout)
        await self._rpc(Operation.SECTIONS_DELETE, effective)(
            ChatServiceAsyncClient.delete_section, name=target
        )

    async def position(
        self,
        name: str,
        *,
        sort_order: int | None = None,
        relative: Literal["start", "end"] | None = None,
        timeout: float | None = None,
        config: RequestConfig | None = None,
    ) -> Section:
        """Move a section to an absolute ``sort_order`` or to one end."""
        target = _section_name(name)
        if (sort_order is None) == (relative is None):
            raise ChatAPIError("pass exactly one of sort_order or relative")
        request = PositionSectionRequest(name=target)
        if sort_order is not None:
            if sort_order < 1:
                raise ChatAPIError("sort_order must be greater than 0")
            request.sort_order = sort_order
        else:
            if relative not in ("start", "end"):
                raise ChatAPIError(
                    f"relative must be 'start' or 'end'; got {relative!r}"
                )
            position = PositionSectionRequest.Position
            request.relative_position = position(
                position.START if relative == "start" else position.END
            )
        effective = _effective_config(config, timeout)
        response = await self._rpc(Operation.SECTIONS_POSITION, effective)(
            ChatServiceAsyncClient.position_section, request=request
        )
        return response.section

    async def list_items(
        self,
        section: str | None = None,
        *,
        space: SpaceRef | str | None = None,
        user: UserRef | str = "me",
        page_size: int | None = None,
        timeout: float | None = None,
        config: RequestConfig | None = None,
    ) -> Pager[SectionItem]:
        """List the items of ``section``, or find ``space`` across all sections.

        Without ``section`` Google's all-sections wildcard is used, which
        requires a ``space`` to look for.
        """
        if section is None:
            if space is None:
                raise ChatAPIError("list_items requires a section or a space")
            parent = f"{_canonical_user(user, parameter='user')}/sections/-"
        else:
            parent = _section_name(section)
        effective = _effective_config(config, timeout)
        request = ListSectionItemsRequest(parent=parent)
        if space is not None:
            request.filter = f"space = {_canonical_space(space)}"
        if page_size is not None:
            request.page_size = page_size

        async def fetch() -> object:
            return await self._rpc(Operation.SECTION_ITEMS_LIST, effective)(
                ChatServiceAsyncClient.list_section_items, request=request
            )

        return Pager(fetch=fetch)

    async def move_item(
        self,
        item: str,
        *,
        target_section: str,
        timeout: float | None = None,
        config: RequestConfig | None = None,
    ) -> SectionItem:
        """Move one section item (a space) into ``target_section``."""
        value = item.strip() if isinstance(item, str) else ""
        if _ITEM_NAME.fullmatch(value) is None:
            raise ChatAPIError(
                "item must be a canonical "
                "'users/{user}/sections/{section}/items/{item}' resource name; "
                f"got {item!r}"
            )
        request = MoveSectionItemRequest(
            name=value, target_section=_section_name(target_section)
        )
        effective = _effective_config(config, timeout)
        response = await self._rpc(Operation.SECTION_ITEMS_MOVE, effective)(
            ChatServiceAsyncClient.move_section_item, request=request
        )
        return response.section_item
