# ruff: noqa: ASYNC109 — timeout kwarg mirrors the StreamTransport protocol
"""Message streaming (Developer Preview): request shapes and local guards."""

from __future__ import annotations

from collections.abc import Mapping

import pytest
from google.apps.chat_v1.types.citation import Citation
from google.apps.chat_v1.types.cited_source import CitedSource
from google.apps.chat_v1.types.markup_syntax import MarkupSyntax
from google.auth.credentials import AnonymousCredentials

from chattice.auth import AuthMode
from chattice.capabilities import CapabilityNotSupported
from chattice.cards import (
    AccessoryWidget,
    Button,
    ButtonList,
    Card,
    CardHeader,
    Section,
    TextParagraph,
)
from chattice.client import Bot, ChatAPIError
from chattice.events import MessageRef
from chattice.experimental.streaming import (
    MessageStream,
    MessageStreams,
    accessory_widget,
    card,
    citation,
    cited_source,
    step,
    text,
)

MESSAGE = "spaces/AAA/messages/m1"
STREAM = "spaces/AAA/streamMessages/s1"
MARKDOWN = MarkupSyntax(MarkupSyntax.MARKUP_SYNTAX_MARKDOWN)

Request = tuple[str, str, Mapping[str, str] | None, Mapping[str, object] | None]


class FakeStreamTransport:
    """Records requests and issues a fresh chunk token per response."""

    def __init__(self) -> None:
        self.requests: list[Request] = []
        self.fail_on: str | None = None

    async def request(
        self,
        method: str,
        path: str,
        *,
        params: Mapping[str, str] | None = None,
        body: Mapping[str, object] | None = None,
        timeout: float | None = None,
    ) -> dict[str, object]:
        self.requests.append((method, path, params, body))
        if self.fail_on is not None and path.endswith(self.fail_on):
            raise ChatAPIError("boom")
        if method == "DELETE":
            return {}
        if path.endswith(":commit"):
            return {"message": {"name": "spaces/AAA/messages/final", "text": "done"}}
        return {"name": STREAM, "nextChunkToken": f"token-{len(self.requests)}"}


def _bot(*, enable_preview: bool = True, auth_mode: AuthMode = AuthMode.APP) -> Bot:
    creds = AnonymousCredentials()  # type: ignore[no-untyped-call]
    return Bot(credentials=creds, auth_mode=auth_mode, enable_preview=enable_preview)


async def _started(transport: FakeStreamTransport) -> MessageStream:
    streams = MessageStreams(_bot(), transport=transport)
    return await streams.start(MESSAGE, progress_text="Thinking...")


async def test_start_posts_stream_message_in_the_message_space() -> None:
    transport = FakeStreamTransport()
    stream = await MessageStreams(_bot(), transport=transport).start(
        MessageRef(name=MESSAGE),
        progress_text="Thinking...",
        markup_syntax=MARKDOWN,
        chunks=[step("Plan")],
    )
    assert stream.name == STREAM
    assert stream.active
    assert transport.requests == [
        (
            "POST",
            "spaces/AAA/streamMessages",
            None,
            {
                "referencedMessage": MESSAGE,
                "progressText": "Thinking...",
                "markupSyntax": "MARKUP_SYNTAX_MARKDOWN",
                "streamContentChunks": [{"step": {"title": "Plan"}}],
            },
        )
    ]


async def test_start_requires_preview_opt_in() -> None:
    transport = FakeStreamTransport()
    streams = MessageStreams(_bot(enable_preview=False), transport=transport)
    with pytest.raises(CapabilityNotSupported, match="enable_preview"):
        await streams.start(MESSAGE, progress_text="Thinking...")
    assert transport.requests == []


async def test_start_rejects_user_authentication() -> None:
    transport = FakeStreamTransport()
    streams = MessageStreams(_bot(auth_mode=AuthMode.USER), transport=transport)
    with pytest.raises(CapabilityNotSupported, match="app authentication"):
        await streams.start(MESSAGE, progress_text="Thinking...")
    assert transport.requests == []


@pytest.mark.parametrize(
    ("message", "progress_text"),
    [("spaces/AAA", "ok"), ("m1", "ok"), (MESSAGE, ""), (MESSAGE, "x" * 251)],
)
async def test_start_validates_locally(message: str, progress_text: str) -> None:
    transport = FakeStreamTransport()
    with pytest.raises(ChatAPIError):
        await MessageStreams(_bot(), transport=transport).start(
            message, progress_text=progress_text
        )
    assert transport.requests == []


async def test_append_chains_chunk_tokens() -> None:
    transport = FakeStreamTransport()
    stream = await _started(transport)
    await stream.append(
        step("Search", "Found 3 articles."),
        text('See <chat-citation data-id="c1">guide</chat-citation>'),
        citation(
            Citation(
                id="c1",
                cited_sources=[CitedSource(title="Guide", uri="https://example.com")],
            )
        ),
        progress_text="Searching...",
    )
    await stream.append(text(" more"))

    _, path, _, first = transport.requests[1]
    assert path == f"{STREAM}:appendStreamMessageContent"
    assert first == {
        "chunkToken": "token-1",
        "progressText": "Searching...",
        "streamContentChunks": [
            {"step": {"title": "Search", "description": "Found 3 articles."}},
            {"text": 'See <chat-citation data-id="c1">guide</chat-citation>'},
            {
                "citation": {
                    "id": "c1",
                    "citedSources": [{"title": "Guide", "uri": "https://example.com"}],
                }
            },
        ],
    }
    second = transport.requests[2][3]
    assert second == {
        "chunkToken": "token-2",
        "streamContentChunks": [{"text": " more"}],
    }


async def test_replace_patches_only_the_given_fields() -> None:
    transport = FakeStreamTransport()
    stream = await _started(transport)
    await stream.replace(progress_text="Formatting...")
    await stream.replace(text("Updated."))

    assert transport.requests[1] == (
        "PATCH",
        STREAM,
        {"updateMask": "progressText"},
        {"nextChunkToken": "token-1", "progressText": "Formatting..."},
    )
    assert transport.requests[2] == (
        "PATCH",
        STREAM,
        {"updateMask": "streamContentChunks"},
        {
            "nextChunkToken": "token-2",
            "streamContentChunks": [{"text": "Updated."}],
        },
    )


async def test_commit_accepts_commit_only_chunks_and_closes_stream() -> None:
    transport = FakeStreamTransport()
    stream = await _started(transport)
    widget = AccessoryWidget(
        button_list=ButtonList(buttons=[Button("Good", action="feedback.good")])
    )
    message = await stream.commit(
        text("All checks passed."),
        cited_source(CitedSource(title="Runbook", uri="https://example.com/r")),
        card(
            Card(
                header=CardHeader(title="Build"),
                sections=[Section(widgets=[TextParagraph("42 checks")])],
            ),
            card_id="details",
        ),
        accessory_widget(widget),
    )

    assert message == {"name": "spaces/AAA/messages/final", "text": "done"}
    assert not stream.active
    method, path, _, body = transport.requests[-1]
    assert (method, path) == ("POST", f"{STREAM}:commit")
    assert body is not None
    assert body["chunkToken"] == "token-1"
    chunks = body["streamContentChunks"]
    assert isinstance(chunks, list)
    assert chunks[0] == {"text": "All checks passed."}
    assert chunks[1] == {
        "citedSource": {"title": "Runbook", "uri": "https://example.com/r"}
    }
    assert chunks[2]["card"]["cardId"] == "details"
    assert chunks[2]["card"]["card"]["header"] == {"title": "Build"}
    assert chunks[3] == {"accessoryWidget": widget.to_dict()}


@pytest.mark.parametrize("method", ["append", "replace"])
async def test_commit_only_chunks_are_rejected_before_commit(method: str) -> None:
    transport = FakeStreamTransport()
    stream = await _started(transport)
    source = cited_source(CitedSource(title="t", uri="https://example.com"))
    with pytest.raises(ChatAPIError, match="only by commit"):
        await getattr(stream, method)(source)
    assert len(transport.requests) == 1


async def test_discard_deletes_the_stream() -> None:
    transport = FakeStreamTransport()
    stream = await _started(transport)
    await stream.discard()
    assert transport.requests[-1] == ("DELETE", STREAM, None, None)
    assert not stream.active
    with pytest.raises(ChatAPIError, match="already committed or discarded"):
        await stream.append(text("late"))


async def test_context_manager_commits_on_clean_exit() -> None:
    transport = FakeStreamTransport()
    async with await _started(transport) as stream:
        await stream.append(text("Hello"))
    assert transport.requests[-1][1] == f"{STREAM}:commit"
    assert transport.requests[-1][3] == {"chunkToken": "token-2"}


async def test_context_manager_discards_when_the_block_raises() -> None:
    transport = FakeStreamTransport()
    with pytest.raises(RuntimeError, match="model failed"):
        async with await _started(transport):
            raise RuntimeError("model failed")
    assert transport.requests[-1][0] == "DELETE"


async def test_context_manager_keeps_the_original_error_if_discard_fails() -> None:
    transport = FakeStreamTransport()
    stream = await _started(transport)
    transport.fail_on = STREAM
    with pytest.raises(RuntimeError, match="model failed"):
        async with stream:
            raise RuntimeError("model failed")


async def test_context_manager_does_nothing_after_explicit_discard() -> None:
    transport = FakeStreamTransport()
    async with await _started(transport) as stream:
        await stream.discard()
    assert [request[0] for request in transport.requests] == ["POST", "DELETE"]


def test_chunk_builders_validate_input() -> None:
    with pytest.raises(ChatAPIError):
        text("")
    with pytest.raises(ChatAPIError):
        step("  ")
