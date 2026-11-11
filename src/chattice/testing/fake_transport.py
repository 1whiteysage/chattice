# ruff: noqa: ASYNC109 — timeout kwarg mirrors the gapic client call convention
"""In-memory fake Chat API transport for tests (no network, no credentials).

Ships in :mod:`chattice.testing` as a framework testing toolkit.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable

from google.apps.chat_v1.services.chat_service import transports
from google.apps.chat_v1.types.attachment import (
    Attachment,
    GetAttachmentRequest,
)
from google.apps.chat_v1.types.availability import (
    Availability,
    GetAvailabilityRequest,
    MarkAsActiveRequest,
    MarkAsAwayRequest,
    MarkAsDoNotDisturbRequest,
    UpdateAvailabilityRequest,
)
from google.apps.chat_v1.types.membership import (
    CreateMembershipRequest,
    DeleteMembershipRequest,
    GetMembershipRequest,
    ListMembershipsRequest,
    ListMembershipsResponse,
    Membership,
    UpdateMembershipRequest,
)
from google.apps.chat_v1.types.message import (
    CreateMessageRequest,
    DeleteMessageRequest,
    GetMessageRequest,
    Message,
    ReplaceMessageCardsRequest,
    ReplaceMessageCardsResponse,
    SearchMessageResult,
    SearchMessagesRequest,
    SearchMessagesResponse,
    UpdateMessageRequest,
)
from google.apps.chat_v1.types.message_pin import (
    CreateMessagePinRequest,
    DeleteMessagePinRequest,
    ListMessagePinsRequest,
    ListMessagePinsResponse,
    MessagePin,
)
from google.apps.chat_v1.types.reaction import (
    CreateCustomEmojiRequest,
    CustomEmoji,
    DeleteCustomEmojiRequest,
    GetCustomEmojiRequest,
    ListCustomEmojisRequest,
    ListCustomEmojisResponse,
)
from google.apps.chat_v1.types.section import (
    CreateSectionRequest,
    DeleteSectionRequest,
    ListSectionItemsRequest,
    ListSectionItemsResponse,
    ListSectionsRequest,
    ListSectionsResponse,
    MoveSectionItemRequest,
    MoveSectionItemResponse,
    PositionSectionRequest,
    PositionSectionResponse,
    Section,
    SectionItem,
    UpdateSectionRequest,
)
from google.apps.chat_v1.types.space import (
    CreateSpaceRequest,
    DeleteSpaceRequest,
    FindGroupChatsRequest,
    FindGroupChatsResponse,
    GetSpaceRequest,
    ListSpacesRequest,
    ListSpacesResponse,
    SearchSpacesRequest,
    SearchSpacesResponse,
    Space,
    UpdateSpaceRequest,
)


class FakeChatTransport(transports.ChatServiceTransport):
    """Subclass of the SDK transport; only the methods Bot uses are real.

    Mirrors the gapic transport contract: the client invokes
    ``self._transport._wrapped_methods[method](request, retry=..., timeout=...,
    metadata=...)`` and reads ``self._transport.host``.
    """

    _matching_host = "chat.googleapis.com"

    def __init__(
        self, error: Exception | None = None, *, credentials: object = None
    ) -> None:
        # The gapic client requires a transport instance to carry credentials
        # itself ("When providing a transport instance, provide its credentials
        # directly") — we accept and store them without using them.
        self.credentials = credentials
        self.error = error
        self.messages: dict[str, Message] = {}
        self.spaces: dict[str, Space] = {}
        self.memberships: dict[str, Membership] = {}
        self.attachments: dict[str, Attachment] = {}
        self.requests: list[CreateMessageRequest] = []
        self.updates: list[UpdateMessageRequest] = []
        self.card_replacements: list[ReplaceMessageCardsRequest] = []
        self.message_pins: dict[str, MessagePin] = {}
        self.message_pin_lists: list[ListMessagePinsRequest] = []
        self.timeouts: list[object] = []
        self.membership_creates: list[CreateMembershipRequest] = []
        self.membership_gets: list[GetMembershipRequest] = []
        self.membership_lists: list[ListMembershipsRequest] = []
        self.membership_deletes: list[DeleteMembershipRequest] = []
        self.space_lists: list[ListSpacesRequest] = []
        self.message_searches: list[SearchMessagesRequest] = []
        self.space_searches: list[SearchSpacesRequest] = []
        self.group_chat_searches: list[FindGroupChatsRequest] = []
        self.space_creates: list[CreateSpaceRequest] = []
        self.space_updates: list[UpdateSpaceRequest] = []
        self.space_deletes: list[DeleteSpaceRequest] = []
        self.membership_updates: list[UpdateMembershipRequest] = []
        self.custom_emojis: dict[str, CustomEmoji] = {}
        self.custom_emoji_creates: list[CreateCustomEmojiRequest] = []
        self.custom_emoji_lists: list[ListCustomEmojisRequest] = []
        self.availabilities: dict[str, Availability] = {}
        self.availability_requests: list[object] = []
        self.sections: dict[str, Section] = {}
        self.section_items: dict[str, SectionItem] = {}
        self.section_requests: list[object] = []
        self.list_page_size = 100
        self.delay: float = 0.0
        self.calls: list[int] = []
        # Keys MUST be bound methods: the client looks up
        # self._transport._wrapped_methods[self._transport.create_message].
        self._wrapped_methods = {
            self.create_message: self._wrap(self.create_message),
            self.get_message: self._wrap(self.get_message),
            self.update_message: self._wrap(self.update_message),
            self.delete_message: self._wrap(self.delete_message),
            self.replace_message_cards: self._wrap(self.replace_message_cards),
            self.create_message_pin: self._wrap(self.create_message_pin),
            self.list_message_pins: self._wrap(self.list_message_pins),
            self.delete_message_pin: self._wrap(self.delete_message_pin),
            self.get_space: self._wrap(self.get_space),
            self.list_spaces: self._wrap(self.list_spaces),
            self.create_membership: self._wrap(self.create_membership),
            self.get_membership: self._wrap(self.get_membership),
            self.list_memberships: self._wrap(self.list_memberships),
            self.delete_membership: self._wrap(self.delete_membership),
            self.get_attachment: self._wrap(self.get_attachment),
            self.search_messages: self._wrap(self.search_messages),
            self.search_spaces: self._wrap(self.search_spaces),
            self.find_group_chats: self._wrap(self.find_group_chats),
            self.create_space: self._wrap(self.create_space),
            self.update_space: self._wrap(self.update_space),
            self.delete_space: self._wrap(self.delete_space),
            self.update_membership: self._wrap(self.update_membership),
            self.create_custom_emoji: self._wrap(self.create_custom_emoji),
            self.get_custom_emoji: self._wrap(self.get_custom_emoji),
            self.list_custom_emojis: self._wrap(self.list_custom_emojis),
            self.delete_custom_emoji: self._wrap(self.delete_custom_emoji),
            self.get_availability: self._wrap(self.get_availability),
            self.update_availability: self._wrap(self.update_availability),
            self.mark_as_active: self._wrap(self.mark_as_active),
            self.mark_as_away: self._wrap(self.mark_as_away),
            self.mark_as_do_not_disturb: self._wrap(self.mark_as_do_not_disturb),
            self.create_section: self._wrap(self.create_section),
            self.list_sections: self._wrap(self.list_sections),
            self.update_section: self._wrap(self.update_section),
            self.delete_section: self._wrap(self.delete_section),
            self.position_section: self._wrap(self.position_section),
            self.list_section_items: self._wrap(self.list_section_items),
            self.move_section_item: self._wrap(self.move_section_item),
        }

    @property
    def host(self) -> str:
        return "fake-chat"

    def _wrap(
        self, method: Callable[..., Awaitable[object]]
    ) -> Callable[..., Awaitable[object]]:
        async def wrapped(
            request: object,
            *,
            retry: object = None,
            timeout: object = None,
            metadata: object = (),
        ) -> object:
            return await method(
                request, retry=retry, timeout=timeout, metadata=metadata
            )

        return wrapped

    def close(self) -> None:
        """Nothing to release: ``Bot.close()`` works on a fake transport."""

    def _check_error(self) -> None:
        if self.error is not None:
            raise self.error

    async def create_message(
        self,
        request: CreateMessageRequest,
        *,
        retry: object = None,
        timeout: object = None,
        metadata: object = (),
    ) -> Message:
        # Record the attempt on entry so a call that fails (error configured)
        # is still counted: the framework made exactly one transport call.
        self.calls.append(1)
        self.timeouts.append(timeout)
        self._check_error()
        if self.delay:
            await asyncio.sleep(self.delay)
        self.requests.append(request)
        if request.message_id:
            name = f"{request.parent}/messages/{request.message_id}"
        else:
            name = f"{request.parent}/messages/fake-{len(self.requests)}"
        message = Message(name=name, text=request.message.text)
        if request.message.thread.name:
            message.thread.name = request.message.thread.name
        self.messages[name] = message
        return message

    async def get_message(
        self,
        request: GetMessageRequest,
        *,
        retry: object = None,
        timeout: object = None,
        metadata: object = (),
    ) -> Message:
        self._check_error()
        message = self.messages.get(request.name)
        if message is None:
            from google.api_core import exceptions

            raise exceptions.NotFound(f"message not found: {request.name}")  # type: ignore[no-untyped-call]
        return message

    async def update_message(
        self,
        request: UpdateMessageRequest,
        *,
        retry: object = None,
        timeout: object = None,
        metadata: object = (),
    ) -> Message:
        self._check_error()
        self.updates.append(request)
        current = self.messages.get(request.message.name)
        if current is None:
            from google.api_core import exceptions

            raise exceptions.NotFound(f"message not found: {request.message.name}")  # type: ignore[no-untyped-call]
        updated = Message(name=current.name, text=request.message.text)
        self.messages[current.name] = updated
        return updated

    async def delete_message(
        self,
        request: DeleteMessageRequest,
        *,
        retry: object = None,
        timeout: object = None,
        metadata: object = (),
    ) -> None:
        self._check_error()
        self.messages.pop(request.name, None)

    async def replace_message_cards(
        self,
        request: ReplaceMessageCardsRequest,
        *,
        retry: object = None,
        timeout: object = None,
        metadata: object = (),
    ) -> ReplaceMessageCardsResponse:
        self._check_error()
        self.card_replacements.append(ReplaceMessageCardsRequest(request))
        return ReplaceMessageCardsResponse()

    async def create_message_pin(
        self,
        request: CreateMessagePinRequest,
        *,
        retry: object = None,
        timeout: object = None,
        metadata: object = (),
    ) -> MessagePin:
        self._check_error()
        message = request.message_pin.message
        pin_id = message.rsplit("/", 1)[-1]
        pin = MessagePin(name=f"{request.parent}/messagePins/{pin_id}", message=message)
        self.message_pins[pin.name] = pin
        return pin

    async def list_message_pins(
        self,
        request: ListMessagePinsRequest,
        *,
        retry: object = None,
        timeout: object = None,
        metadata: object = (),
    ) -> ListMessagePinsResponse:
        self._check_error()
        self.message_pin_lists.append(ListMessagePinsRequest(request))
        prefix = f"{request.parent}/messagePins/"
        values = [
            self.message_pins[name]
            for name in sorted(self.message_pins)
            if name.startswith(prefix)
        ]
        offset = int(request.page_token or "0")
        end = min(offset + self.list_page_size, len(values))
        next_token = str(end) if end < len(values) else ""
        return ListMessagePinsResponse(
            message_pins=values[offset:end],
            next_page_token=next_token,
        )

    async def delete_message_pin(
        self,
        request: DeleteMessagePinRequest,
        *,
        retry: object = None,
        timeout: object = None,
        metadata: object = (),
    ) -> None:
        self._check_error()
        if self.message_pins.pop(request.name, None) is None:
            from google.api_core import exceptions

            raise exceptions.NotFound(f"message pin not found: {request.name}")  # type: ignore[no-untyped-call]

    async def get_space(
        self,
        request: GetSpaceRequest,
        *,
        retry: object = None,
        timeout: object = None,
        metadata: object = (),
    ) -> Space:
        self._check_error()
        space = self.spaces.get(request.name)
        if space is None:
            from google.api_core import exceptions

            raise exceptions.NotFound(f"space not found: {request.name}")  # type: ignore[no-untyped-call]
        return space

    async def list_spaces(
        self,
        request: ListSpacesRequest,
        *,
        retry: object = None,
        timeout: object = None,
        metadata: object = (),
    ) -> ListSpacesResponse:
        self._check_error()
        self.space_lists.append(ListSpacesRequest(request))
        values = [self.spaces[name] for name in sorted(self.spaces)]
        offset = int(request.page_token or "0")
        end = min(offset + self.list_page_size, len(values))
        next_token = str(end) if end < len(values) else ""
        return ListSpacesResponse(
            spaces=values[offset:end],
            next_page_token=next_token,
        )

    async def create_membership(
        self,
        request: CreateMembershipRequest,
        *,
        retry: object = None,
        timeout: object = None,
        metadata: object = (),
    ) -> Membership:
        self._check_error()
        self.membership_creates.append(CreateMembershipRequest(request))
        member_id = request.membership.member.name.removeprefix("users/")
        membership = Membership(request.membership)
        membership.name = f"{request.parent}/members/{member_id}"
        self.memberships[membership.name] = membership
        return membership

    async def get_membership(
        self,
        request: GetMembershipRequest,
        *,
        retry: object = None,
        timeout: object = None,
        metadata: object = (),
    ) -> Membership:
        self._check_error()
        self.membership_gets.append(GetMembershipRequest(request))
        membership = self.memberships.get(request.name)
        if membership is None:
            from google.api_core import exceptions

            raise exceptions.NotFound(f"membership not found: {request.name}")  # type: ignore[no-untyped-call]
        return membership

    async def list_memberships(
        self,
        request: ListMembershipsRequest,
        *,
        retry: object = None,
        timeout: object = None,
        metadata: object = (),
    ) -> ListMembershipsResponse:
        self._check_error()
        self.membership_lists.append(ListMembershipsRequest(request))
        prefix = f"{request.parent}/members/"
        values = [
            self.memberships[name]
            for name in sorted(self.memberships)
            if name.startswith(prefix)
        ]
        offset = int(request.page_token or "0")
        end = min(offset + self.list_page_size, len(values))
        next_token = str(end) if end < len(values) else ""
        return ListMembershipsResponse(
            memberships=values[offset:end],
            next_page_token=next_token,
        )

    async def delete_membership(
        self,
        request: DeleteMembershipRequest,
        *,
        retry: object = None,
        timeout: object = None,
        metadata: object = (),
    ) -> Membership:
        self._check_error()
        self.membership_deletes.append(DeleteMembershipRequest(request))
        membership = self.memberships.pop(request.name, None)
        if membership is None:
            from google.api_core import exceptions

            raise exceptions.NotFound(f"membership not found: {request.name}")  # type: ignore[no-untyped-call]
        return membership

    async def get_attachment(
        self,
        request: GetAttachmentRequest,
        *,
        retry: object = None,
        timeout: object = None,
        metadata: object = (),
    ) -> Attachment:
        self._check_error()
        attachment = self.attachments.get(request.name)
        if attachment is None:
            from google.api_core import exceptions

            raise exceptions.NotFound(f"attachment not found: {request.name}")  # type: ignore[no-untyped-call]
        return attachment

    def _page(self, values: list[Space], page_token: str) -> tuple[list[Space], str]:
        offset = int(page_token or "0")
        end = min(offset + self.list_page_size, len(values))
        return values[offset:end], (str(end) if end < len(values) else "")

    async def search_messages(
        self,
        request: SearchMessagesRequest,
        *,
        retry: object = None,
        timeout: object = None,
        metadata: object = (),
    ) -> SearchMessagesResponse:
        """Return stored messages whose text contains the filter string."""
        self._check_error()
        self.message_searches.append(SearchMessagesRequest(request))
        values = [
            self.messages[name]
            for name in sorted(self.messages)
            if request.filter in self.messages[name].text
        ]
        offset = int(request.page_token or "0")
        end = min(offset + self.list_page_size, len(values))
        return SearchMessagesResponse(
            results=[SearchMessageResult(message=item) for item in values[offset:end]],
            next_page_token=str(end) if end < len(values) else "",
        )

    async def search_spaces(
        self,
        request: SearchSpacesRequest,
        *,
        retry: object = None,
        timeout: object = None,
        metadata: object = (),
    ) -> SearchSpacesResponse:
        """Return every stored space; the query is recorded, not evaluated."""
        self._check_error()
        self.space_searches.append(SearchSpacesRequest(request))
        values = [self.spaces[name] for name in sorted(self.spaces)]
        page, next_token = self._page(values, request.page_token)
        return SearchSpacesResponse(
            spaces=page, next_page_token=next_token, total_size=len(values)
        )

    async def find_group_chats(
        self,
        request: FindGroupChatsRequest,
        *,
        retry: object = None,
        timeout: object = None,
        metadata: object = (),
    ) -> FindGroupChatsResponse:
        """Return stored GROUP_CHAT spaces; the user set is recorded only."""
        self._check_error()
        self.group_chat_searches.append(FindGroupChatsRequest(request))
        values = [
            self.spaces[name]
            for name in sorted(self.spaces)
            if self.spaces[name].space_type == Space.SpaceType.GROUP_CHAT
        ]
        page, next_token = self._page(values, request.page_token)
        return FindGroupChatsResponse(spaces=page, next_page_token=next_token)

    async def create_space(
        self,
        request: CreateSpaceRequest,
        *,
        retry: object = None,
        timeout: object = None,
        metadata: object = (),
    ) -> Space:
        self._check_error()
        self.space_creates.append(CreateSpaceRequest(request))
        space = Space(request.space)
        space.name = f"spaces/fake-{len(self.space_creates)}"
        self.spaces[space.name] = space
        return space

    async def update_space(
        self,
        request: UpdateSpaceRequest,
        *,
        retry: object = None,
        timeout: object = None,
        metadata: object = (),
    ) -> Space:
        self._check_error()
        self.space_updates.append(UpdateSpaceRequest(request))
        if request.space.name not in self.spaces:
            from google.api_core import exceptions

            raise exceptions.NotFound(f"space not found: {request.space.name}")  # type: ignore[no-untyped-call]
        space = Space(request.space)
        self.spaces[space.name] = space
        return space

    async def delete_space(
        self,
        request: DeleteSpaceRequest,
        *,
        retry: object = None,
        timeout: object = None,
        metadata: object = (),
    ) -> None:
        self._check_error()
        self.space_deletes.append(DeleteSpaceRequest(request))
        if self.spaces.pop(request.name, None) is None:
            from google.api_core import exceptions

            raise exceptions.NotFound(f"space not found: {request.name}")  # type: ignore[no-untyped-call]

    async def update_membership(
        self,
        request: UpdateMembershipRequest,
        *,
        retry: object = None,
        timeout: object = None,
        metadata: object = (),
    ) -> Membership:
        self._check_error()
        self.membership_updates.append(UpdateMembershipRequest(request))
        current = self.memberships.get(request.membership.name)
        if current is None:
            from google.api_core import exceptions

            raise exceptions.NotFound(  # type: ignore[no-untyped-call]
                f"membership not found: {request.membership.name}"
            )
        updated = Membership(current)
        updated.role = request.membership.role
        self.memberships[updated.name] = updated
        return updated

    @staticmethod
    def _not_found(what: str, name: str) -> Exception:
        from google.api_core import exceptions

        return exceptions.NotFound(f"{what} not found: {name}")  # type: ignore[no-untyped-call]

    async def create_custom_emoji(
        self,
        request: CreateCustomEmojiRequest,
        *,
        retry: object = None,
        timeout: object = None,
        metadata: object = (),
    ) -> CustomEmoji:
        self._check_error()
        self.custom_emoji_creates.append(CreateCustomEmojiRequest(request))
        emoji = CustomEmoji(
            name=f"customEmojis/fake-{len(self.custom_emoji_creates)}",
            emoji_name=request.custom_emoji.emoji_name,
        )
        self.custom_emojis[emoji.name] = emoji
        return emoji

    def _find_custom_emoji(self, name: str) -> CustomEmoji | None:
        alias = name.removeprefix("customEmojis/")
        for emoji in self.custom_emojis.values():
            if emoji.name == name or emoji.emoji_name == alias:
                return emoji
        return None

    async def get_custom_emoji(
        self,
        request: GetCustomEmojiRequest,
        *,
        retry: object = None,
        timeout: object = None,
        metadata: object = (),
    ) -> CustomEmoji:
        self._check_error()
        emoji = self._find_custom_emoji(request.name)
        if emoji is None:
            raise self._not_found("custom emoji", request.name)
        return emoji

    async def list_custom_emojis(
        self,
        request: ListCustomEmojisRequest,
        *,
        retry: object = None,
        timeout: object = None,
        metadata: object = (),
    ) -> ListCustomEmojisResponse:
        """Return every stored emoji; the filter is recorded, not evaluated."""
        self._check_error()
        self.custom_emoji_lists.append(ListCustomEmojisRequest(request))
        values = [self.custom_emojis[name] for name in sorted(self.custom_emojis)]
        offset = int(request.page_token or "0")
        end = min(offset + self.list_page_size, len(values))
        return ListCustomEmojisResponse(
            custom_emojis=values[offset:end],
            next_page_token=str(end) if end < len(values) else "",
        )

    async def delete_custom_emoji(
        self,
        request: DeleteCustomEmojiRequest,
        *,
        retry: object = None,
        timeout: object = None,
        metadata: object = (),
    ) -> None:
        self._check_error()
        emoji = self._find_custom_emoji(request.name)
        if emoji is None:
            raise self._not_found("custom emoji", request.name)
        del self.custom_emojis[emoji.name]

    def _availability(self, name: str) -> Availability:
        current = self.availabilities.get(name)
        if current is None:
            current = Availability(
                name=name, state=Availability.State(Availability.State.ACTIVE)
            )
            self.availabilities[name] = current
        return current

    async def get_availability(
        self,
        request: GetAvailabilityRequest,
        *,
        retry: object = None,
        timeout: object = None,
        metadata: object = (),
    ) -> Availability:
        self._check_error()
        return self._availability(request.name)

    async def update_availability(
        self,
        request: UpdateAvailabilityRequest,
        *,
        retry: object = None,
        timeout: object = None,
        metadata: object = (),
    ) -> Availability:
        self._check_error()
        self.availability_requests.append(UpdateAvailabilityRequest(request))
        current = self._availability(request.availability.name)
        current.custom_status = request.availability.custom_status
        return current

    async def mark_as_active(
        self,
        request: MarkAsActiveRequest,
        *,
        retry: object = None,
        timeout: object = None,
        metadata: object = (),
    ) -> Availability:
        self._check_error()
        self.availability_requests.append(MarkAsActiveRequest(request))
        current = self._availability(request.name)
        current.state = Availability.State(Availability.State.ACTIVE)
        return current

    async def mark_as_away(
        self,
        request: MarkAsAwayRequest,
        *,
        retry: object = None,
        timeout: object = None,
        metadata: object = (),
    ) -> Availability:
        self._check_error()
        self.availability_requests.append(MarkAsAwayRequest(request))
        current = self._availability(request.name)
        current.state = Availability.State(Availability.State.AWAY)
        return current

    async def mark_as_do_not_disturb(
        self,
        request: MarkAsDoNotDisturbRequest,
        *,
        retry: object = None,
        timeout: object = None,
        metadata: object = (),
    ) -> Availability:
        self._check_error()
        self.availability_requests.append(MarkAsDoNotDisturbRequest(request))
        current = self._availability(request.name)
        current.state = Availability.State(Availability.State.DO_NOT_DISTURB)
        return current

    async def create_section(
        self,
        request: CreateSectionRequest,
        *,
        retry: object = None,
        timeout: object = None,
        metadata: object = (),
    ) -> Section:
        self._check_error()
        self.section_requests.append(CreateSectionRequest(request))
        section = Section(request.section)
        section.name = f"{request.parent}/sections/fake-{len(self.sections) + 1}"
        section.sort_order = len(self.sections) + 1
        self.sections[section.name] = section
        return section

    async def list_sections(
        self,
        request: ListSectionsRequest,
        *,
        retry: object = None,
        timeout: object = None,
        metadata: object = (),
    ) -> ListSectionsResponse:
        self._check_error()
        self.section_requests.append(ListSectionsRequest(request))
        prefix = f"{request.parent}/sections/"
        values = sorted(
            (item for name, item in self.sections.items() if name.startswith(prefix)),
            key=lambda item: item.sort_order,
        )
        offset = int(request.page_token or "0")
        end = min(offset + self.list_page_size, len(values))
        return ListSectionsResponse(
            sections=values[offset:end],
            next_page_token=str(end) if end < len(values) else "",
        )

    async def update_section(
        self,
        request: UpdateSectionRequest,
        *,
        retry: object = None,
        timeout: object = None,
        metadata: object = (),
    ) -> Section:
        self._check_error()
        self.section_requests.append(UpdateSectionRequest(request))
        current = self.sections.get(request.section.name)
        if current is None:
            raise self._not_found("section", request.section.name)
        current.display_name = request.section.display_name
        return current

    async def delete_section(
        self,
        request: DeleteSectionRequest,
        *,
        retry: object = None,
        timeout: object = None,
        metadata: object = (),
    ) -> None:
        self._check_error()
        self.section_requests.append(DeleteSectionRequest(request))
        if self.sections.pop(request.name, None) is None:
            raise self._not_found("section", request.name)

    async def position_section(
        self,
        request: PositionSectionRequest,
        *,
        retry: object = None,
        timeout: object = None,
        metadata: object = (),
    ) -> PositionSectionResponse:
        """Record the request; an absolute sort order is applied as given."""
        self._check_error()
        self.section_requests.append(PositionSectionRequest(request))
        current = self.sections.get(request.name)
        if current is None:
            raise self._not_found("section", request.name)
        if request.sort_order:
            current.sort_order = request.sort_order
        return PositionSectionResponse(section=current)

    async def list_section_items(
        self,
        request: ListSectionItemsRequest,
        *,
        retry: object = None,
        timeout: object = None,
        metadata: object = (),
    ) -> ListSectionItemsResponse:
        """Items of one section, or of all sections for the ``-`` wildcard.

        A ``space = spaces/X`` filter is evaluated.
        """
        self._check_error()
        self.section_requests.append(ListSectionItemsRequest(request))
        prefix = request.parent.removesuffix("-") + (
            "" if request.parent.endswith("/-") else "/items/"
        )
        wanted = request.filter.removeprefix("space = ") if request.filter else ""
        values = [
            self.section_items[name]
            for name in sorted(self.section_items)
            if name.startswith(prefix)
            and (not wanted or self.section_items[name].space == wanted)
        ]
        offset = int(request.page_token or "0")
        end = min(offset + self.list_page_size, len(values))
        return ListSectionItemsResponse(
            section_items=values[offset:end],
            next_page_token=str(end) if end < len(values) else "",
        )

    async def move_section_item(
        self,
        request: MoveSectionItemRequest,
        *,
        retry: object = None,
        timeout: object = None,
        metadata: object = (),
    ) -> MoveSectionItemResponse:
        self._check_error()
        self.section_requests.append(MoveSectionItemRequest(request))
        current = self.section_items.pop(request.name, None)
        if current is None:
            raise self._not_found("section item", request.name)
        item_id = request.name.rsplit("/", 1)[-1]
        moved = SectionItem(
            name=f"{request.target_section}/items/{item_id}", space=current.space
        )
        self.section_items[moved.name] = moved
        return MoveSectionItemResponse(section_item=moved)
