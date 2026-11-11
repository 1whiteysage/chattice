# ruff: noqa: ASYNC109 — timeout kwarg mirrors the outbound client convention
"""Message streaming over ``spaces.streamMessages`` (Developer Preview).

A stream shows a live progress indicator, incremental text, and
intermediate steps in a thread, then becomes a regular message::

    streams = MessageStreams(bot)
    async with await streams.start(message.message, progress_text="Thinking...") as s:
        await s.append(text("Hello "), progress_text="Writing...")
        await s.append(text("world"))
    # leaving the block commits; an exception discards the stream

Google constraints this module relies on:

- app authentication only (``chat.bot``); the project must be enrolled
  in the Google Workspace Developer Preview Program;
- the referenced message must be in a threaded space (or a 1:1 direct
  message that already contains a message);
- an active stream times out 5 minutes after creation;
- cards, accessory widgets, and footer sources are accepted only by
  ``commit``.

The official Python client has no streaming methods, so requests go to
the REST endpoints directly. Requires ``Bot(enable_preview=True)`` or
``preview_features={PreviewFeature.MESSAGE_STREAMING}``.
"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from types import TracebackType

from google.apps.chat_v1.types.citation import Citation
from google.apps.chat_v1.types.cited_source import CitedSource
from google.apps.chat_v1.types.markup_syntax import MarkupSyntax

from chattice.capabilities import PreviewFeature
from chattice.cards import AccessoryWidget, Card
from chattice.cards._assets import resolve_card_assets, validate_card_assets
from chattice.cards.addon import bind_addon_actions_json
from chattice.client import Bot
from chattice.client.errors import ChatAPIError
from chattice.events import MessageRef
from chattice.experimental._rest import (
    PreviewTransport,
    RestTransport,
    require_app_preview,
)

__all__ = [
    "MessageStream",
    "MessageStreams",
    "StreamChunk",
    "StreamTransport",
    "accessory_widget",
    "card",
    "citation",
    "cited_source",
    "step",
    "text",
]

# Public name of the transport protocol for this module.
StreamTransport = PreviewTransport

_MAX_PROGRESS_TEXT = 250
# Chunk kinds Google accepts only when committing a stream.
_COMMIT_ONLY = frozenset({"card", "accessoryWidget", "citedSource"})
_MESSAGE_NAME = re.compile(r"spaces/[^/]+/messages/[^/]+")
_STREAM_NAME = re.compile(r"spaces/[^/]+/streamMessages/[^/]+")


@dataclass(frozen=True, slots=True)
class StreamChunk:
    """One entry of ``streamContentChunks``: exactly one content kind."""

    kind: str
    value: object

    def to_dict(self) -> dict[str, object]:
        return {self.kind: self.value}


def text(value: str) -> StreamChunk:
    """Incremental text: appended by ``append``, replaced by ``replace``."""
    if not value:
        raise ChatAPIError("a text chunk must be a non-empty string")
    return StreamChunk("text", value)


def step(title: str, description: str | None = None) -> StreamChunk:
    """An intermediate step, such as a reasoning step or a tool call."""
    if not title or not title.strip():
        raise ChatAPIError("a step chunk requires a non-empty title")
    value: dict[str, object] = {"title": title}
    if description:
        value["description"] = description
    return StreamChunk("step", value)


def citation(value: Citation) -> StreamChunk:
    """An inline citation referenced from the text; needs Markdown markup."""
    return StreamChunk("citation", json.loads(Citation.to_json(value)))


def cited_source(value: CitedSource) -> StreamChunk:
    """A footer source link (commit only)."""
    return StreamChunk("citedSource", json.loads(CitedSource.to_json(value)))


def card(value: Card, *, card_id: str = "card") -> StreamChunk:
    """A card attached to the finalized message (commit only)."""
    return StreamChunk("card", _PendingCard(card_id=card_id, card=value))


def accessory_widget(value: AccessoryWidget) -> StreamChunk:
    """An accessory widget below the finalized message (commit only)."""
    return StreamChunk("accessoryWidget", value.to_dict())


@dataclass(frozen=True, slots=True)
class _PendingCard:
    """A card chunk before its local image assets are published."""

    card_id: str
    card: Card


class MessageStreams:
    """Entry point for stream messages sent as the Chat app."""

    def __init__(self, bot: Bot, *, transport: StreamTransport | None = None) -> None:
        self._bot = bot
        self._transport: StreamTransport = transport or RestTransport(bot)

    async def start(
        self,
        message: MessageRef | str,
        *,
        progress_text: str,
        chunks: Sequence[StreamChunk] = (),
        markup_syntax: MarkupSyntax | None = None,
        timeout: float | None = None,
    ) -> MessageStream:
        """Start a stream anchored to ``message`` (usually the user's message).

        ``progress_text`` is the plain-text status shown next to the
        progress indicator. The reply appears in the thread of
        ``message``. Call ``commit()`` or ``discard()`` within 5 minutes.
        """
        referenced = message if isinstance(message, str) else message.name
        if not referenced or _MESSAGE_NAME.fullmatch(referenced) is None:
            raise ChatAPIError(
                "message must be a canonical "
                f"'spaces/{{space}}/messages/{{message}}' name; got {referenced!r}"
            )
        _validate_progress_text(progress_text, required=True)
        _reject_commit_only(chunks, "start")
        await require_app_preview(
            self._bot, PreviewFeature.MESSAGE_STREAMING, "Message streaming"
        )
        body: dict[str, object] = {
            "referencedMessage": referenced,
            "progressText": progress_text,
        }
        if markup_syntax is not None:
            body["markupSyntax"] = MarkupSyntax(markup_syntax).name
        if chunks:
            body["streamContentChunks"] = await _encode(self._bot, chunks)
        parent = referenced.split("/messages/", 1)[0]
        response = await self._transport.request(
            "POST", f"{parent}/streamMessages", body=body, timeout=timeout
        )
        return MessageStream(self._bot, self._transport, response)


class MessageStream:
    """One active stream; tracks the chunk token between requests.

    Requests on one stream must be sequential: every response carries
    the token the next request has to present.
    """

    def __init__(
        self, bot: Bot, transport: StreamTransport, response: Mapping[str, object]
    ) -> None:
        name = response.get("name")
        token = response.get("nextChunkToken")
        if not isinstance(name, str) or _STREAM_NAME.fullmatch(name) is None:
            raise ChatAPIError("Google returned a stream message without a name")
        if not isinstance(token, str) or not token:
            raise ChatAPIError("Google returned a stream message without a token")
        self._bot = bot
        self._transport = transport
        self._name = name
        self._token = token
        self._active = True

    @property
    def name(self) -> str:
        """``spaces/{space}/streamMessages/{stream}`` resource name."""
        return self._name

    @property
    def active(self) -> bool:
        """False once the stream was committed or discarded."""
        return self._active

    async def append(
        self,
        *chunks: StreamChunk,
        progress_text: str | None = None,
        timeout: float | None = None,
    ) -> None:
        """Append chunks: text is concatenated, steps and citations are added."""
        self._require_active()
        if not chunks:
            raise ChatAPIError("append requires at least one chunk")
        _reject_commit_only(chunks, "append")
        _validate_progress_text(progress_text, required=False)
        body: dict[str, object] = {
            "chunkToken": self._token,
            "streamContentChunks": await _encode(self._bot, chunks),
        }
        if progress_text:
            body["progressText"] = progress_text
        response = await self._transport.request(
            "POST",
            f"{self._name}:appendStreamMessageContent",
            body=body,
            timeout=timeout,
        )
        self._advance(response)

    async def replace(
        self,
        *chunks: StreamChunk,
        progress_text: str | None = None,
        timeout: float | None = None,
    ) -> None:
        """Replace the streamed content and/or the progress text in place."""
        self._require_active()
        if not chunks and progress_text is None:
            raise ChatAPIError("replace requires chunks or progress_text")
        _reject_commit_only(chunks, "replace")
        paths: list[str] = []
        body: dict[str, object] = {"nextChunkToken": self._token}
        if progress_text is not None:
            _validate_progress_text(progress_text, required=True)
            body["progressText"] = progress_text
            paths.append("progressText")
        if chunks:
            body["streamContentChunks"] = await _encode(self._bot, chunks)
            paths.append("streamContentChunks")
        response = await self._transport.request(
            "PATCH",
            self._name,
            params={"updateMask": ",".join(paths)},
            body=body,
            timeout=timeout,
        )
        self._advance(response)

    async def commit(
        self, *chunks: StreamChunk, timeout: float | None = None
    ) -> dict[str, object]:
        """Finalize the stream; returns the permanent message as REST JSON.

        ``chunks`` are appended first and may include the commit-only
        kinds: ``card``, ``accessory_widget``, ``cited_source``.
        """
        self._require_active()
        body: dict[str, object] = {"chunkToken": self._token}
        if chunks:
            body["streamContentChunks"] = await _encode(self._bot, chunks)
        response = await self._transport.request(
            "POST", f"{self._name}:commit", body=body, timeout=timeout
        )
        self._active = False
        message = response.get("message")
        return dict(message) if isinstance(message, Mapping) else {}

    async def discard(self, *, timeout: float | None = None) -> None:
        """Delete the active stream; nothing is saved in the space."""
        self._require_active()
        await self._transport.request("DELETE", self._name, timeout=timeout)
        self._active = False

    async def __aenter__(self) -> MessageStream:
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        """Commit on a clean exit, discard when the block raised.

        Nothing happens when the block already committed or discarded.
        A failure to discard never replaces the original exception.
        """
        del exc, traceback
        if not self._active:
            return
        if exc_type is None:
            await self.commit()
            return
        try:
            await self.discard()
        except Exception:
            pass

    def _require_active(self) -> None:
        if not self._active:
            raise ChatAPIError(
                f"stream {self._name} was already committed or discarded"
            )

    def _advance(self, response: Mapping[str, object]) -> None:
        token = response.get("nextChunkToken")
        if not isinstance(token, str) or not token:
            raise ChatAPIError("Google returned a stream update without a token")
        self._token = token


def _validate_progress_text(value: str | None, *, required: bool) -> None:
    if value is None or value == "":
        if required:
            raise ChatAPIError("progress_text must be a non-empty string")
        return
    if len(value) > _MAX_PROGRESS_TEXT:
        raise ChatAPIError(
            f"progress_text is limited to {_MAX_PROGRESS_TEXT} characters; "
            f"got {len(value)}"
        )


def _reject_commit_only(chunks: Sequence[StreamChunk], method: str) -> None:
    for chunk in chunks:
        if chunk.kind in _COMMIT_ONLY:
            raise ChatAPIError(
                f"{chunk.kind} chunks are accepted only by commit(); "
                f"they cannot be sent with {method}()."
            )


async def _encode(bot: Bot, chunks: Sequence[StreamChunk]) -> list[dict[str, object]]:
    """Serialize chunks; cards publish their local image assets first."""
    encoded: list[dict[str, object]] = []
    for chunk in chunks:
        if isinstance(chunk.value, _PendingCard):
            validate_card_assets(chunk.value.card, bot._asset_publisher)
            resolved = await resolve_card_assets(chunk.value.card, bot._asset_publisher)
            encoded.append(
                {"card": {"cardId": chunk.value.card_id, "card": resolved.to_dict()}}
            )
        else:
            encoded.append(chunk.to_dict())
    if bot._addon_action_url is not None:
        # HTTP add-on: card actions call the app's endpoint by URL.
        bound: list[dict[str, object]] = bind_addon_actions_json(
            encoded, bot._addon_action_url
        )
        return bound
    return encoded
