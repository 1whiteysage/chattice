"""messages.replace_cards: APP-only asynchronous card replacement."""

from __future__ import annotations

import pytest
from google.auth.credentials import AnonymousCredentials

from chattice.auth import AuthMode
from chattice.capabilities import REGISTRY, CapabilityNotSupported, Operation
from chattice.cards import Card, CardHeader, Section, TextParagraph
from chattice.client import Bot, ChatAPIError
from chattice.testing import MockBot

from ._fake_transport import FakeChatTransport


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


def _card(title: str) -> Card:
    return Card(
        header=CardHeader(title=title),
        sections=[Section(widgets=[TextParagraph("body")])],
    )


def test_replace_cards_is_stable_and_app_only() -> None:
    spec = REGISTRY.spec(Operation.MESSAGES_REPLACE_CARDS)
    assert spec.preview is False
    assert spec.google_method == "spaces.messages.replaceCards"
    assert {path.identity for path in spec.auth_paths} == {AuthMode.APP}


async def test_replace_cards_sends_cards_with_unique_ids() -> None:
    transport = FakeChatTransport()
    await _bot(transport).app.messages.replace_cards(
        "spaces/AAA/messages/m1", [_card("One"), _card("Two")]
    )
    request = transport.card_replacements[-1]
    assert request.name == "spaces/AAA/messages/m1"
    assert [entry.card_id for entry in request.cards_v2] == ["card", "card-2"]
    assert [entry.card.header.title for entry in request.cards_v2] == ["One", "Two"]


async def test_replace_cards_with_empty_list_clears_cards() -> None:
    transport = FakeChatTransport()
    await _bot(transport).app.messages.replace_cards("spaces/AAA/messages/m1", [])
    assert list(transport.card_replacements[-1].cards_v2) == []


async def test_replace_cards_rejects_malformed_name_locally() -> None:
    transport = FakeChatTransport()
    with pytest.raises(ChatAPIError):
        await _bot(transport).app.messages.replace_cards("m1", [_card("One")])
    assert transport.card_replacements == []


async def test_replace_cards_user_identity_fails_at_preflight() -> None:
    transport = FakeChatTransport()
    with pytest.raises(CapabilityNotSupported):
        await _bot(transport).user.messages.replace_cards(
            "spaces/AAA/messages/m1", [_card("One")]
        )
    assert transport.card_replacements == []


async def test_mock_bot_records_replace_cards() -> None:
    bot = MockBot()
    await bot.app.messages.replace_cards("spaces/AAA/messages/m1", [_card("One")])
    kind, args = bot.calls[-1]
    assert kind == "replace_cards"
    assert args["name"] == "spaces/AAA/messages/m1"
    assert args["cards"][0]["header"]["title"] == "One"
