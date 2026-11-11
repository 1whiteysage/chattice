"""Administrator access: the ADMIN execution variant end to end."""

from __future__ import annotations

import pytest
from google.apps.chat_v1.types import Space
from google.apps.chat_v1.types.membership import Membership
from google.auth.credentials import AnonymousCredentials

from chattice.auth import AuthMode
from chattice.capabilities import (
    REGISTRY,
    CapabilityNotSupported,
    ExecutionVariant,
    Operation,
)
from chattice.client import Bot
from chattice.testing import FakeChatTransport, MockBot, fake_bot

_SCOPE = "https://www.googleapis.com/auth/"

# Every Chat API method that documents ``useAdminAccess``.
ADMIN_OPERATIONS = (
    Operation.SPACES_GET,
    Operation.SPACES_SEARCH,
    Operation.SPACES_UPDATE,
    Operation.SPACES_DELETE,
    Operation.MEMBERSHIPS_CREATE,
    Operation.MEMBERSHIPS_GET,
    Operation.MEMBERSHIPS_LIST,
    Operation.MEMBERSHIPS_UPDATE,
    Operation.MEMBERSHIPS_DELETE,
)


class _UserCredentials(AnonymousCredentials):
    def __init__(self, *scopes: str) -> None:
        super().__init__()  # type: ignore[no-untyped-call]
        self.refresh_token = "fake"
        self.scopes = [_SCOPE + scope for scope in scopes]


class _AppCredentials(AnonymousCredentials):
    def __init__(self) -> None:
        super().__init__()  # type: ignore[no-untyped-call]
        self.signer = object()


def _bot(*user_scopes: str) -> tuple[Bot, FakeChatTransport]:
    transport = FakeChatTransport()
    bot = Bot(
        app_credentials_provider=_AppCredentials,
        user_credentials_provider=lambda: _UserCredentials(*user_scopes),
        transport=transport,
    )
    return bot, transport


@pytest.mark.parametrize("operation", ADMIN_OPERATIONS)
def test_admin_variant_is_a_user_path_with_admin_scopes(operation: Operation) -> None:
    paths = [
        path
        for path in REGISTRY.spec(operation).auth_paths
        if path.variant is ExecutionVariant.ADMIN
    ]

    assert len(paths) == 1
    assert paths[0].identity is AuthMode.USER
    assert paths[0].request_flag == "use_admin_access"
    assert all("/chat.admin." in scope for scope in paths[0].any_scope)


def test_only_documented_operations_have_an_admin_variant() -> None:
    with_admin = {
        spec.operation
        for spec in REGISTRY
        if any(path.variant is ExecutionVariant.ADMIN for path in spec.auth_paths)
    }
    assert with_admin == set(ADMIN_OPERATIONS)


async def test_admin_search_sets_the_request_flag() -> None:
    bot, transport = _bot("chat.admin.spaces.readonly")

    pager = await bot.user.spaces.search(
        'customer = "customers/my_customer" AND space_type = "SPACE"',
        admin_access=True,
    )
    await pager.collect()

    assert transport.space_searches[-1].use_admin_access is True


async def test_admin_space_update_and_delete_set_the_request_flag() -> None:
    bot, transport = _bot("chat.admin.spaces", "chat.admin.delete")
    transport.spaces["spaces/AAA"] = Space(name="spaces/AAA")

    await bot.user.spaces.update(
        Space(name="spaces/AAA", display_name="Renamed"),
        update_mask=["display_name"],
        admin_access=True,
    )
    await bot.user.spaces.delete("spaces/AAA", admin_access=True)

    assert transport.space_updates[-1].use_admin_access is True
    assert transport.space_deletes[-1].use_admin_access is True


async def test_admin_membership_calls_set_the_request_flag() -> None:
    bot, transport = _bot("chat.admin.memberships")
    name = "spaces/AAA/members/123"
    transport.memberships[name] = Membership(name=name)

    await bot.user.memberships.create("spaces/AAA", user="users/456", admin_access=True)
    await bot.user.memberships.get(name, admin_access=True)
    pager = await bot.user.memberships.list(parent="spaces/AAA", admin_access=True)
    await pager.collect()
    await bot.user.memberships.update(
        name,
        role=Membership.MembershipRole(Membership.MembershipRole.ROLE_MANAGER),
        admin_access=True,
    )
    await bot.user.memberships.delete(name, admin_access=True)

    assert transport.membership_creates[-1].use_admin_access is True
    assert transport.membership_gets[-1].use_admin_access is True
    assert transport.membership_lists[-1].use_admin_access is True
    assert transport.membership_updates[-1].use_admin_access is True
    assert transport.membership_deletes[-1].use_admin_access is True


async def test_admin_access_is_rejected_locally_without_an_admin_scope() -> None:
    bot, transport = _bot("chat.spaces.readonly")

    with pytest.raises(CapabilityNotSupported, match=r"chat\.admin\.spaces"):
        pager = await bot.user.spaces.search("customer = x", admin_access=True)
        await pager.collect()

    assert transport.space_searches == []


async def test_admin_access_is_rejected_for_the_app_identity() -> None:
    bot, _ = fake_bot()
    with pytest.raises(CapabilityNotSupported, match="administrator access"):
        await bot.app.spaces.get("spaces/AAA", admin_access=True)


async def test_membership_reads_stay_app_only_without_admin_access() -> None:
    bot, _ = _bot("chat.admin.memberships")
    # The admin scope opens the ADMIN variant only; it does not turn a
    # plain USER call into an allowed one.
    with pytest.raises(CapabilityNotSupported):
        await bot.user.memberships.get("spaces/AAA/members/123")


async def test_normal_calls_do_not_send_the_flag() -> None:
    bot, transport = _bot("chat.spaces.readonly")

    pager = await bot.user.spaces.search("display_name:x")
    await pager.collect()

    assert transport.space_searches[-1].use_admin_access is False


async def test_mock_bot_records_admin_access() -> None:
    mock = MockBot()
    await mock.user.spaces.get("spaces/AAA", admin_access=True)
    await mock.app.spaces.get("spaces/BBB")
    assert mock.calls == [
        ("get_space", {"name": "spaces/AAA", "admin_access": True}),
        ("get_space", {"name": "spaces/BBB"}),
    ]
