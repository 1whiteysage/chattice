"""Custom emojis, availability, and sidebar sections: USER-only wrappers."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from google.apps.chat_v1.types.availability import (
    Availability,
    MarkAsActiveRequest,
    MarkAsDoNotDisturbRequest,
    UpdateAvailabilityRequest,
)
from google.apps.chat_v1.types.reaction import CustomEmoji
from google.apps.chat_v1.types.section import (
    ListSectionItemsRequest,
    PositionSectionRequest,
    Section,
    SectionItem,
)
from google.auth.credentials import AnonymousCredentials

from chattice.auth import AuthMode
from chattice.capabilities import REGISTRY, CapabilityNotSupported
from chattice.client import Bot, ChatAPIError, ChatNotFoundError

from ._fake_transport import FakeChatTransport
from .test_identity_clients import _creds as _app_creds

PNG = b"\x89PNG" + b"0" * 64


class _UserCredentials(AnonymousCredentials):
    refresh_token = "test-refresh-token"


def _bot(transport: FakeChatTransport) -> Bot:
    return Bot(
        app_credentials_provider=_app_creds,
        user_credentials_provider=lambda: _UserCredentials(),  # type: ignore[no-untyped-call]
        transport=transport,
    )


def test_new_operations_are_stable_and_user_only() -> None:
    prefixes = ("custom_emojis.", "availability.", "sections.", "section_items.")
    specs = [spec for spec in REGISTRY if spec.operation.value.startswith(prefixes)]
    assert len(specs) == 16
    for spec in specs:
        assert spec.preview is False
        assert {path.identity for path in spec.auth_paths} == {AuthMode.USER}


# --- custom emojis ---------------------------------------------------------


async def test_custom_emoji_round_trip_by_alias() -> None:
    transport = FakeChatTransport()
    emojis = _bot(transport).user.custom_emojis
    created = await emojis.create(":team-launch:", PNG, filename="launch.png")

    payload = transport.custom_emoji_creates[-1].custom_emoji.payload
    assert payload.file_content == PNG
    assert payload.filename == "launch.png"
    assert (await emojis.get(":team-launch:")).name == created.name
    assert (await emojis.get(created.name)).emoji_name == ":team-launch:"

    await emojis.delete(":team-launch:")
    with pytest.raises(ChatNotFoundError):
        await emojis.get(created.name)


@pytest.mark.parametrize(
    "emoji_name",
    ["launch", ":Launch:", ":team--launch:", ":-launch:", ":team launch:", "::"],
)
async def test_custom_emoji_name_is_validated_locally(emoji_name: str) -> None:
    transport = FakeChatTransport()
    with pytest.raises(ChatAPIError, match="emoji_name"):
        await _bot(transport).user.custom_emojis.create(
            emoji_name, PNG, filename="x.png"
        )
    assert transport.custom_emoji_creates == []


@pytest.mark.parametrize(
    ("image", "filename"),
    [(PNG, "x.webp"), (b"", "x.png"), (b"0" * (256 * 1024), "x.png")],
)
async def test_custom_emoji_image_is_validated_locally(
    image: bytes, filename: str
) -> None:
    transport = FakeChatTransport()
    with pytest.raises(ChatAPIError):
        await _bot(transport).user.custom_emojis.create(
            ":ok:", image, filename=filename
        )
    assert transport.custom_emoji_creates == []


@pytest.mark.parametrize(
    ("created_by_me", "expected"),
    [(None, ""), (True, 'creator("users/me")'), (False, 'NOT creator("users/me")')],
)
async def test_custom_emoji_list_builds_the_creator_filter(
    created_by_me: bool | None, expected: str
) -> None:
    transport = FakeChatTransport()
    transport.custom_emojis["customEmojis/1"] = CustomEmoji(name="customEmojis/1")
    pager = await _bot(transport).user.custom_emojis.list(
        created_by_me=created_by_me, page_size=50
    )
    assert [emoji.name for emoji in await pager.collect()] == ["customEmojis/1"]
    assert transport.custom_emoji_lists[-1].filter == expected
    assert transport.custom_emoji_lists[-1].page_size == 50


async def test_custom_emoji_target_is_validated_locally() -> None:
    emojis = _bot(FakeChatTransport()).user.custom_emojis
    for name in ("", "launch", "customEmojis/", "spaces/A"):
        with pytest.raises(ChatAPIError):
            await emojis.get(name)


async def test_custom_emojis_are_user_only() -> None:
    transport = FakeChatTransport()
    with pytest.raises(CapabilityNotSupported):
        await _bot(transport).app.custom_emojis.get(":ok:")


# --- availability ----------------------------------------------------------


async def test_availability_defaults_to_the_calling_user() -> None:
    transport = FakeChatTransport()
    availability = _bot(transport).user.users.availability
    current = await availability.get()
    assert current.name == "users/me/availability"
    assert (await availability.get("123")).name == "users/123/availability"


async def test_set_custom_status_updates_only_the_status() -> None:
    transport = FakeChatTransport()
    updated = await _bot(transport).user.users.availability.set_custom_status(
        "In a workshop", emoji="📚", ttl=timedelta(hours=2)
    )
    assert updated.custom_status.text == "In a workshop"
    request = transport.availability_requests[-1]
    assert isinstance(request, UpdateAvailabilityRequest)
    assert list(request.update_mask.paths) == ["custom_status"]
    assert request.availability.name == "users/me/availability"
    assert request.availability.custom_status.emoji.unicode == "📚"
    assert request.availability.custom_status.ttl == timedelta(hours=2)


@pytest.mark.parametrize(
    ("text", "emoji"),
    [("", "📚"), ("  ", "📚"), ("x" * 65, "📚"), ("Busy", ""), ("Busy", ":busy:")],
)
async def test_custom_status_is_validated_locally(text: str, emoji: str) -> None:
    transport = FakeChatTransport()
    with pytest.raises(ChatAPIError):
        await _bot(transport).user.users.availability.set_custom_status(
            text, emoji=emoji
        )
    assert transport.availability_requests == []


async def test_mark_methods_send_the_expiration() -> None:
    transport = FakeChatTransport()
    availability = _bot(transport).user.users.availability
    until = datetime(2027, 1, 1, tzinfo=UTC)

    assert (await availability.mark_away()).state == Availability.State.AWAY
    dnd = await availability.mark_do_not_disturb(expire_time=until)
    assert dnd.state == Availability.State.DO_NOT_DISTURB
    dnd_request = transport.availability_requests[-1]
    assert isinstance(dnd_request, MarkAsDoNotDisturbRequest)
    assert dnd_request.expire_time == until

    active = await availability.mark_active(ttl=timedelta(minutes=30))
    assert active.state == Availability.State.ACTIVE
    active_request = transport.availability_requests[-1]
    assert isinstance(active_request, MarkAsActiveRequest)
    assert active_request.ttl == timedelta(minutes=30)


async def test_expiration_arguments_are_validated_locally() -> None:
    transport = FakeChatTransport()
    availability = _bot(transport).user.users.availability
    with pytest.raises(ChatAPIError, match="either ttl or expire_time"):
        await availability.mark_active(
            ttl=timedelta(minutes=1), expire_time=datetime(2027, 1, 1, tzinfo=UTC)
        )
    with pytest.raises(ChatAPIError, match="positive"):
        await availability.mark_do_not_disturb(ttl=timedelta(0))
    assert transport.availability_requests == []


async def test_availability_is_user_only() -> None:
    with pytest.raises(CapabilityNotSupported):
        await _bot(FakeChatTransport()).app.users.availability.get()


# --- sections --------------------------------------------------------------


async def test_section_lifecycle() -> None:
    transport = FakeChatTransport()
    sections = _bot(transport).user.users.sections
    first = await sections.create("Projects")
    second = await sections.create("Clients")

    assert first.name.startswith("users/me/sections/")
    assert first.type_ == Section.SectionType.CUSTOM_SECTION
    pager = await sections.list(page_size=10)
    assert [item.display_name async for item in pager] == ["Projects", "Clients"]

    renamed = await sections.update(first.name, display_name="Active projects")
    assert renamed.display_name == "Active projects"

    await sections.delete(second.name)
    with pytest.raises(ChatNotFoundError):
        await sections.delete(second.name)


async def test_section_position_uses_one_of_the_two_forms() -> None:
    transport = FakeChatTransport()
    sections = _bot(transport).user.users.sections
    section = await sections.create("Projects")

    moved = await sections.position(section.name, sort_order=3)
    assert moved.sort_order == 3
    await sections.position(section.name, relative="end")
    request = transport.section_requests[-1]
    assert isinstance(request, PositionSectionRequest)
    assert request.relative_position == PositionSectionRequest.Position.END

    with pytest.raises(ChatAPIError):
        await sections.position(section.name)
    with pytest.raises(ChatAPIError):
        await sections.position(section.name, sort_order=1, relative="start")
    with pytest.raises(ChatAPIError):
        await sections.position(section.name, sort_order=0)


@pytest.mark.parametrize("display_name", ["", "   ", "x" * 81])
async def test_section_display_name_is_validated_locally(display_name: str) -> None:
    transport = FakeChatTransport()
    with pytest.raises(ChatAPIError):
        await _bot(transport).user.users.sections.create(display_name)
    assert transport.section_requests == []


async def test_section_items_list_filter_and_move() -> None:
    transport = FakeChatTransport()
    source = "users/me/sections/s1"
    target = "users/me/sections/s2"
    for index, space in enumerate(("spaces/A", "spaces/B"), start=1):
        name = f"{source}/items/i{index}"
        transport.section_items[name] = SectionItem(name=name, space=space)
    sections = _bot(transport).user.users.sections

    in_section = await sections.list_items(source)
    assert [item.space async for item in in_section] == ["spaces/A", "spaces/B"]

    found = await sections.list_items(space="B")
    assert [item.name async for item in found] == [f"{source}/items/i2"]
    request = transport.section_requests[-1]
    assert isinstance(request, ListSectionItemsRequest)
    assert request.parent == "users/me/sections/-"
    assert request.filter == "space = spaces/B"

    moved = await sections.move_item(f"{source}/items/i2", target_section=target)
    assert moved.name == f"{target}/items/i2"
    assert moved.space == "spaces/B"


async def test_section_names_are_validated_locally() -> None:
    transport = FakeChatTransport()
    sections = _bot(transport).user.users.sections
    with pytest.raises(ChatAPIError):
        await sections.update("sections/s1", display_name="X")
    with pytest.raises(ChatAPIError):
        await sections.list_items()
    with pytest.raises(ChatAPIError):
        await sections.move_item("users/me/sections/s1", target_section="users/me")
    assert transport.section_requests == []


async def test_sections_are_user_only() -> None:
    with pytest.raises(CapabilityNotSupported):
        await _bot(FakeChatTransport()).app.users.sections.create("Projects")
