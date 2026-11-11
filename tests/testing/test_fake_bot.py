"""fake_bot(): the real Bot on FakeChatTransport, built in one call."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import cast

import pytest

from chattice.auth import AuthMode
from chattice.capabilities import CapabilityNotSupported
from chattice.cards import Card, Image, Section
from chattice.client import Bot, ChatAPIError
from chattice.exceptions import AssetPublisherNotConfigured
from chattice.testing import FakeChatTransport, fake_bot


@dataclass
class _RecordingPublisher:
    url: str = "https://assets.example.com/report.png"
    filenames: list[str] = field(default_factory=list)

    async def publish(
        self,
        data: bytes,
        *,
        filename: str,
        content_type: str,
        namespace: str | None = None,
    ) -> str:
        self.filenames.append(filename)
        return self.url


def _local_image_card() -> Card:
    image = Image.from_bytes(b"png", filename="report.png")
    return Card(sections=[Section(widgets=[image])])


def test_returns_a_real_bot_and_its_transport() -> None:
    bot, transport = fake_bot()
    assert type(bot) is Bot
    assert type(transport) is FakeChatTransport
    assert bot.auth_mode is AuthMode.APP


async def test_app_message_is_visible_on_the_transport() -> None:
    bot, transport = fake_bot()

    sent = await bot.app.messages.create("spaces/AAA", text="hello")

    assert transport.requests[0].parent == "spaces/AAA"
    assert transport.requests[0].message.text == "hello"
    assert transport.messages[sent.name].text == "hello"


async def test_seeded_transport_state_is_served_to_the_bot() -> None:
    bot, transport = fake_bot()
    sent = await bot.app.messages.create("spaces/AAA", text="seed")

    assert (await bot.user.messages.get(sent.name)).text == "seed"
    assert (await bot.raw.app()).transport is transport
    assert (await bot.raw.user()).transport is transport


async def test_user_only_operation_succeeds_as_user() -> None:
    bot, transport = fake_bot()

    pin = await bot.user.message_pins.create("spaces/AAA/messages/m1")

    assert pin.name == "spaces/AAA/messagePins/m1"
    assert list(transport.message_pins) == ["spaces/AAA/messagePins/m1"]


async def test_user_only_operation_is_rejected_for_the_app_identity() -> None:
    bot, transport = fake_bot()

    # Passing here would mean the APP credentials were not classified.
    with pytest.raises(CapabilityNotSupported, match="MESSAGE_PINS_CREATE"):
        await bot.app.message_pins.create("spaces/AAA/messages/m1")

    assert transport.message_pins == {}


async def test_user_only_operation_is_rejected_without_user_identity() -> None:
    bot, transport = fake_bot(user=False)

    with pytest.raises(CapabilityNotSupported, match="USER identity"):
        await bot.user.message_pins.create("spaces/AAA/messages/m1")

    assert transport.message_pins == {}
    # The APP identity of the same Bot still works.
    await bot.app.messages.create("spaces/AAA", text="still app")
    assert len(transport.requests) == 1


async def test_local_validation_fails_before_the_transport() -> None:
    bot, transport = fake_bot()

    with pytest.raises(ChatAPIError, match="notify must be"):
        await bot.app.messages.create("spaces/AAA", text="x", notify="loud")

    assert transport.calls == []
    assert transport.requests == []


async def test_preview_operation_is_gated_by_default() -> None:
    bot, transport = fake_bot()

    with pytest.raises(CapabilityNotSupported, match="enable_preview"):
        await bot.user.messages.search("report", order_by="relevance desc")

    assert transport.message_searches == []


async def test_preview_operation_runs_with_enable_preview() -> None:
    bot, transport = fake_bot(enable_preview=True)

    pager = await bot.user.messages.search("report", order_by="relevance desc")
    await pager.collect()

    assert transport.message_searches[0].order_by == "relevance desc"


async def test_asset_publisher_resolves_local_card_images() -> None:
    publisher = _RecordingPublisher()
    bot, transport = fake_bot(asset_publisher=publisher)

    await bot.app.messages.create("spaces/AAA", card=_local_image_card())

    assert publisher.filenames == ["report.png"]
    widget = transport.requests[0].message.cards_v2[0].card.sections[0].widgets[0]
    assert widget.image.image_url == publisher.url


async def test_local_card_image_needs_an_asset_publisher() -> None:
    bot, transport = fake_bot()

    with pytest.raises(AssetPublisherNotConfigured):
        await bot.app.messages.create("spaces/AAA", card=_local_image_card())

    assert transport.calls == []


async def test_bot_closes_cleanly_after_use() -> None:
    bot, transport = fake_bot()

    # Both clients are built, so close() reaches the shared transport.
    async with bot:
        await bot.app.messages.create("spaces/AAA", text="bye")
        await bot.user.messages.get("spaces/AAA/messages/fake-1")

    await bot.close()  # idempotent
    assert len(transport.requests) == 1


@pytest.mark.parametrize("identity", [AuthMode.APP, AuthMode.USER])
async def test_fake_credentials_never_authorize_a_real_request(
    identity: AuthMode,
) -> None:
    bot, _transport = fake_bot()
    credentials = (
        await bot._resolve_credentials_async()
        if identity is AuthMode.APP
        else await bot._resolve_user_credentials_async()
    )
    assert credentials is not None

    with pytest.raises(RuntimeError, match="cannot authorize a real request"):
        credentials.before_request(  # type: ignore[no-untyped-call]
            object(), "POST", "https://chat.googleapis.com/upload", {}
        )


async def test_documented_fake_bot_example_runs() -> None:
    path = Path("docs/architecture/testing.md")
    source = await asyncio.to_thread(path.read_text, encoding="utf-8")
    section = source.split("## fake_bot", 1)[1]
    block = section.split("```python", 1)[1].split("```", 1)[0]
    namespace: dict[str, object] = {}
    exec(compile(block, str(path), "exec"), namespace)

    documented = [name for name in namespace if name.startswith("test_")]
    assert len(documented) == 3
    for name in documented:
        await cast(Callable[[], Awaitable[None]], namespace[name])()
