"""Message pin resource client: USER-only, generally available."""

from __future__ import annotations

import pytest
from google.auth.credentials import AnonymousCredentials

from chattice.auth import AuthMode
from chattice.capabilities import REGISTRY, CapabilityNotSupported, Operation
from chattice.client import Bot, ChatAPIError, ChatNotFoundError
from chattice.events import SpaceRef

from ._fake_transport import FakeChatTransport
from .test_identity_clients import _creds as _app_creds


class _UserCredentials(AnonymousCredentials):
    refresh_token = "test-refresh-token"


def _creds() -> AnonymousCredentials:
    return AnonymousCredentials()  # type: ignore[no-untyped-call]


def _bot(transport: FakeChatTransport) -> Bot:
    return Bot(
        app_credentials_provider=_creds,
        user_credentials_provider=lambda: _UserCredentials(),  # type: ignore[no-untyped-call]
        transport=transport,
    )


def test_pin_operations_are_stable_and_user_only() -> None:
    for operation in (
        Operation.MESSAGE_PINS_CREATE,
        Operation.MESSAGE_PINS_LIST,
        Operation.MESSAGE_PINS_DELETE,
    ):
        spec = REGISTRY.spec(operation)
        assert spec.preview is False
        assert {path.identity for path in spec.auth_paths} == {AuthMode.USER}


async def test_create_pins_message_in_its_space() -> None:
    transport = FakeChatTransport()
    pin = await _bot(transport).user.message_pins.create("spaces/AAA/messages/m1.t1")
    assert pin.name == "spaces/AAA/messagePins/m1.t1"
    assert pin.message == "spaces/AAA/messages/m1.t1"


@pytest.mark.parametrize("name", ["", "m1", "spaces/AAA", "spaces/AAA/threads/t1"])
async def test_create_rejects_malformed_message_name_locally(name: str) -> None:
    transport = FakeChatTransport()
    with pytest.raises(ChatAPIError):
        await _bot(transport).user.message_pins.create(name)
    assert transport.message_pins == {}


async def test_list_pages_the_pins_of_one_space() -> None:
    transport = FakeChatTransport()
    transport.list_page_size = 2
    bot = _bot(transport)
    for index in range(3):
        await bot.user.message_pins.create(f"spaces/AAA/messages/m{index}")
    await bot.user.message_pins.create("spaces/BBB/messages/other")

    pager = await bot.user.message_pins.list(SpaceRef(name="spaces/AAA"), page_size=2)
    names = [pin.name async for pin in pager]

    assert names == [f"spaces/AAA/messagePins/m{index}" for index in range(3)]
    assert transport.message_pin_lists[0].parent == "spaces/AAA"
    assert transport.message_pin_lists[0].page_size == 2


@pytest.mark.parametrize(
    "name", ["spaces/AAA/messagePins/m1", "spaces/AAA/messages/m1"]
)
async def test_delete_accepts_pin_name_or_message_name(name: str) -> None:
    transport = FakeChatTransport()
    bot = _bot(transport)
    await bot.user.message_pins.create("spaces/AAA/messages/m1")
    await bot.user.message_pins.delete(name)
    assert transport.message_pins == {}


async def test_delete_missing_pin_raises_not_found() -> None:
    with pytest.raises(ChatNotFoundError):
        await _bot(FakeChatTransport()).user.message_pins.delete(
            "spaces/AAA/messagePins/nope"
        )


async def test_delete_rejects_malformed_name_locally() -> None:
    with pytest.raises(ChatAPIError):
        await _bot(FakeChatTransport()).user.message_pins.delete("spaces/AAA")


async def test_app_identity_fails_at_preflight() -> None:
    transport = FakeChatTransport()
    bot = Bot(credentials=_app_creds(), transport=transport)
    with pytest.raises(CapabilityNotSupported):
        await bot.app.message_pins.create("spaces/AAA/messages/m1")
    assert transport.message_pins == {}
