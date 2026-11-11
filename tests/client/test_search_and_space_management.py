"""Search, group-chat lookup, space management, and membership roles."""

from __future__ import annotations

import pytest
from google.apps.chat_v1.types import Space
from google.apps.chat_v1.types.membership import Membership
from google.apps.chat_v1.types.message import Message
from google.auth.credentials import AnonymousCredentials

from chattice.capabilities import REGISTRY, CapabilityNotSupported, Operation
from chattice.client import Bot, ChatAPIError, ChatNotFoundError
from chattice.events import SpaceRef, UserRef

from ._fake_transport import FakeChatTransport
from .test_identity_clients import _creds as _app_creds


class _UserCredentials(AnonymousCredentials):
    refresh_token = "test-refresh-token"


def _bot(transport: FakeChatTransport, *, enable_preview: bool = False) -> Bot:
    return Bot(
        app_credentials_provider=_app_creds,
        user_credentials_provider=lambda: _UserCredentials(),  # type: ignore[no-untyped-call]
        transport=transport,
        enable_preview=enable_preview,
    )


MANAGER = Membership.MembershipRole(Membership.MembershipRole.ROLE_MANAGER)
UNSPECIFIED = Membership.MembershipRole(
    Membership.MembershipRole.MEMBERSHIP_ROLE_UNSPECIFIED
)


def test_every_operation_has_a_registry_spec() -> None:
    assert {spec.operation for spec in REGISTRY} == set(Operation)


async def test_message_search_targets_all_spaces() -> None:
    transport = FakeChatTransport()
    transport.messages["spaces/A/messages/1"] = Message(
        name="spaces/A/messages/1", text="quarterly report"
    )
    transport.messages["spaces/B/messages/2"] = Message(
        name="spaces/B/messages/2", text="lunch"
    )
    pager = await _bot(transport).user.messages.search(" report ", page_size=10)
    results = await pager.collect()

    assert [result.message.name for result in results] == ["spaces/A/messages/1"]
    request = transport.message_searches[-1]
    assert request.parent == "spaces/-"
    assert request.filter == "report"
    assert request.page_size == 10


async def test_message_search_rejects_empty_query_locally() -> None:
    transport = FakeChatTransport()
    with pytest.raises(ChatAPIError):
        await _bot(transport).user.messages.search("   ")
    assert transport.message_searches == []


async def test_message_search_relevance_ordering_needs_preview() -> None:
    transport = FakeChatTransport()
    with pytest.raises(CapabilityNotSupported, match="enable_preview"):
        await _bot(transport).user.messages.search("x", order_by="relevance desc")

    pager = await _bot(transport, enable_preview=True).user.messages.search(
        "x", order_by="relevance desc"
    )
    await pager.collect()
    assert transport.message_searches[-1].order_by == "relevance desc"


async def test_message_search_is_user_only() -> None:
    transport = FakeChatTransport()
    pager = await _bot(transport).app.messages.search("x")
    with pytest.raises(CapabilityNotSupported):
        await pager.collect()
    assert transport.message_searches == []


async def test_space_search_pages_results() -> None:
    transport = FakeChatTransport()
    transport.list_page_size = 1
    for name in ("spaces/A", "spaces/B"):
        transport.spaces[name] = Space(name=name)
    pager = await _bot(transport).user.spaces.search(
        'display_name:"Team"', order_by="create_time desc"
    )
    assert [space.name async for space in pager] == ["spaces/A", "spaces/B"]
    assert transport.space_searches[0].query == 'display_name:"Team"'
    assert transport.space_searches[0].order_by == "create_time desc"
    assert transport.space_searches[0].use_admin_access is False


async def test_space_search_rejects_empty_query_locally() -> None:
    with pytest.raises(ChatAPIError):
        await _bot(FakeChatTransport()).user.spaces.search("")


async def test_find_group_chats_canonicalizes_users() -> None:
    transport = FakeChatTransport()
    transport.spaces["spaces/G"] = Space(
        name="spaces/G", space_type=Space.SpaceType.GROUP_CHAT
    )
    transport.spaces["spaces/S"] = Space(
        name="spaces/S", space_type=Space.SpaceType.SPACE
    )
    pager = await _bot(transport).user.spaces.find_group_chats(
        ["123", UserRef(name="users/456")]
    )
    assert [space.name async for space in pager] == ["spaces/G"]
    assert list(transport.group_chat_searches[-1].users) == ["users/123", "users/456"]


async def test_find_group_chats_requires_users() -> None:
    with pytest.raises(ChatAPIError):
        await _bot(FakeChatTransport()).user.spaces.find_group_chats([])


async def test_user_creates_space_with_request_id() -> None:
    transport = FakeChatTransport()
    created = await _bot(transport).user.spaces.create(
        Space(space_type=Space.SpaceType.SPACE, display_name="Launch"),
        request_id="req-1",
    )
    assert created.display_name == "Launch"
    assert created.name in transport.spaces
    assert transport.space_creates[-1].request_id == "req-1"


async def test_app_space_creation_requires_customer() -> None:
    transport = FakeChatTransport()
    bot = _bot(transport)
    with pytest.raises(ChatAPIError, match="customer"):
        await bot.app.spaces.create(Space(display_name="Launch"))
    assert transport.space_creates == []

    await bot.app.spaces.create(
        Space(display_name="Launch", customer="customers/my_customer")
    )
    assert transport.space_creates[-1].space.customer == "customers/my_customer"


async def test_update_space_sends_mask() -> None:
    transport = FakeChatTransport()
    transport.spaces["spaces/A"] = Space(name="spaces/A", display_name="Old")
    updated = await _bot(transport).user.spaces.update(
        Space(name="spaces/A", display_name="New"), update_mask=["display_name"]
    )
    assert updated.display_name == "New"
    assert list(transport.space_updates[-1].update_mask.paths) == ["display_name"]
    assert transport.space_updates[-1].use_admin_access is False


@pytest.mark.parametrize(
    ("space", "mask"),
    [
        (Space(name="A", display_name="New"), ["display_name"]),
        (Space(name="spaces/A", display_name="New"), []),
        (Space(name="spaces/A", display_name="New"), [" "]),
    ],
)
async def test_update_space_validates_locally(space: Space, mask: list[str]) -> None:
    transport = FakeChatTransport()
    with pytest.raises(ChatAPIError):
        await _bot(transport).user.spaces.update(space, update_mask=mask)
    assert transport.space_updates == []


async def test_delete_space_accepts_ref_and_bare_id() -> None:
    transport = FakeChatTransport()
    transport.spaces["spaces/A"] = Space(name="spaces/A")
    transport.spaces["spaces/B"] = Space(name="spaces/B")
    bot = _bot(transport)
    await bot.user.spaces.delete(SpaceRef(name="spaces/A"))
    await bot.user.spaces.delete("B")
    assert transport.spaces == {}
    with pytest.raises(ChatNotFoundError):
        await bot.user.spaces.delete("spaces/A")


async def test_membership_update_changes_only_role() -> None:
    transport = FakeChatTransport()
    name = "spaces/A/members/123"
    transport.memberships[name] = Membership(name=name)
    updated = await _bot(transport).user.memberships.update(name, role=MANAGER)
    assert updated.role == MANAGER
    request = transport.membership_updates[-1]
    assert list(request.update_mask.paths) == ["role"]
    assert request.use_admin_access is False


async def test_membership_update_validates_locally() -> None:
    transport = FakeChatTransport()
    bot = _bot(transport)
    with pytest.raises(ChatAPIError):
        await bot.user.memberships.update("spaces/A", role=MANAGER)
    with pytest.raises(ChatAPIError):
        await bot.user.memberships.update("spaces/A/members/1", role=UNSPECIFIED)
    assert transport.membership_updates == []
