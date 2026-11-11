"""Citations, footer sources, and markup syntax on message writes."""

from __future__ import annotations

import pytest
from google.apps.chat_v1.types.citation import Citation
from google.apps.chat_v1.types.cited_source import CitedSource
from google.apps.chat_v1.types.markup_syntax import MarkupSyntax
from google.auth.credentials import AnonymousCredentials

from chattice.cards import Card
from chattice.client import Bot, ChatAPIError
from chattice.testing import MockBot

from ._fake_transport import FakeChatTransport

MARKDOWN = MarkupSyntax(MarkupSyntax.MARKUP_SYNTAX_MARKDOWN)
CHAT = MarkupSyntax(MarkupSyntax.MARKUP_SYNTAX_CHAT)


def _bot(transport: FakeChatTransport) -> Bot:
    creds = AnonymousCredentials()  # type: ignore[no-untyped-call]
    return Bot(credentials=creds, transport=transport)


def _source(title: str = "Example") -> CitedSource:
    return CitedSource(title=title, uri="https://example.com")


async def test_citations_and_footer_sources_reach_transport() -> None:
    transport = FakeChatTransport()
    await _bot(transport).app.messages.create(
        "spaces/AAA",
        text='A <chat-citation data-id="c1">claim</chat-citation>.',
        markup_syntax=MARKDOWN,
        citations=[Citation(id="c1", cited_sources=[_source("Inline")])],
        cited_sources=[_source("Footer")],
    )
    elements = transport.requests[-1].message.elements
    assert [citation.id for citation in elements.citations] == ["c1"]
    assert elements.citations[0].cited_sources[0].title == "Inline"
    assert [source.title for source in elements.cited_sources] == ["Footer"]


async def test_message_without_sources_sends_no_elements() -> None:
    transport = FakeChatTransport()
    await _bot(transport).app.messages.create("spaces/AAA", text="plain")
    assert "elements" not in transport.requests[-1].message


async def test_sources_defer_to_app_level_default_markup() -> None:
    """No markup_syntax means the console default decides; no local error."""
    transport = FakeChatTransport()
    await _bot(transport).app.messages.create(
        "spaces/AAA", text="text", cited_sources=[_source()]
    )
    assert len(transport.requests[-1].message.elements.cited_sources) == 1


async def test_sources_reject_explicit_chat_markup_locally() -> None:
    transport = FakeChatTransport()
    with pytest.raises(ChatAPIError, match="MARKUP_SYNTAX_MARKDOWN"):
        await _bot(transport).app.messages.create(
            "spaces/AAA",
            text="text",
            markup_syntax=CHAT,
            cited_sources=[_source()],
        )
    assert transport.requests == []


@pytest.mark.parametrize("citation_id", ["", "with-dash", "пример", "a" * 63])
async def test_invalid_citation_id_fails_locally(citation_id: str) -> None:
    transport = FakeChatTransport()
    with pytest.raises(ChatAPIError, match="citation id"):
        await _bot(transport).app.messages.create(
            "spaces/AAA",
            text="text",
            markup_syntax=MARKDOWN,
            citations=[Citation(id=citation_id)],
        )
    assert transport.requests == []


async def test_citation_id_allows_underscore_like_google_examples() -> None:
    transport = FakeChatTransport()
    await _bot(transport).app.messages.create(
        "spaces/AAA",
        text='<chat-citation data-id="cite_1">x</chat-citation>',
        markup_syntax=MARKDOWN,
        citations=[Citation(id="cite_1")],
    )
    assert transport.requests[-1].message.elements.citations[0].id == "cite_1"


async def test_duplicate_citation_id_fails_locally() -> None:
    transport = FakeChatTransport()
    with pytest.raises(ChatAPIError, match="duplicate"):
        await _bot(transport).app.messages.create(
            "spaces/AAA",
            text="text",
            markup_syntax=MARKDOWN,
            citations=[Citation(id="c1"), Citation(id="c1")],
        )
    assert transport.requests == []


async def test_update_sets_markup_syntax_outside_the_mask() -> None:
    transport = FakeChatTransport()
    bot = _bot(transport)
    sent = await bot.app.messages.create("spaces/AAA", text="before")
    await bot.app.messages.update(sent.name, text="**after**", markup_syntax=MARKDOWN)
    request = transport.updates[-1]
    assert request.message.markup_syntax == MARKDOWN
    assert list(request.update_mask.paths) == ["text"]


async def test_update_markup_syntax_requires_text() -> None:
    transport = FakeChatTransport()
    with pytest.raises(ChatAPIError, match="markup_syntax requires text"):
        await _bot(transport).app.messages.update(
            "spaces/AAA/messages/m1", card=Card(), markup_syntax=MARKDOWN
        )
    assert transport.updates == []


async def test_mock_bot_mirrors_sources_and_update_markup() -> None:
    bot = MockBot()
    await bot.app.messages.create(
        "spaces/AAA",
        text="text",
        markup_syntax=MARKDOWN,
        citations=[Citation(id="c1")],
        cited_sources=[_source()],
    )
    assert [citation.id for citation in bot.calls[-1][1]["citations"]] == ["c1"]
    assert len(bot.calls[-1][1]["cited_sources"]) == 1

    updated = await bot.app.messages.update(
        "spaces/AAA/messages/1", text="**x**", markup_syntax=MARKDOWN
    )
    assert updated.markup_syntax == MARKDOWN
    assert bot.calls[-1][1]["markup_syntax"] == MARKDOWN
