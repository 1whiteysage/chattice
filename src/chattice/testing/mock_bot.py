# ruff: noqa: ASYNC109 — timeout kwarg mirrors the real Bot (gapic call convention)
"""MockBot: a call-recording stand-in for the outgoing API.

MockBot mirrors a fixed part of the real client: ``messages.create`` /
``update`` / ``replace_cards`` / ``get`` / ``delete`` and ``spaces.get``.
Everything else raises ``AttributeError`` naming the missing resource;
:func:`chattice.testing.fake_bot` covers the whole client surface.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any, NoReturn

from google.apps.chat_v1.types.message import Message
from google.apps.chat_v1.types.space import Space

from chattice.media import AttachmentRef, AttachmentSource, UploadedAttachment

__all__ = ["MockBot"]


class _MockFacade:
    """One level of the mirrored facade (``bot.app``, ``bot.app.messages``).

    Anything the mirror does not model fails loudly instead of looking
    like a typo: the error names the missing resource or method and the
    double that does model it.
    """

    def __init__(self, bot: MockBot, path: str) -> None:
        self._bot = bot
        self._path = path

    if not TYPE_CHECKING:
        # Runtime only: type checkers keep reporting unknown attributes.
        def __getattr__(self, name: str) -> NoReturn:
            if name.startswith("_"):
                raise AttributeError(
                    f"{type(self).__name__!r} object has no attribute {name!r}"
                )
            raise AttributeError(
                f"MockBot does not model '{self._path}.{name}': it mirrors only "
                "messages.create/update/replace_cards/get/delete and "
                "spaces.get. Use chattice.testing.fake_bot() for a real Bot "
                "on FakeChatTransport, which covers the whole client."
            )


class _MockMessages(_MockFacade):
    """Message resource facade over the recording methods.

    ``config`` (per-call timeout, retry, metadata) is accepted and stops
    here: like ``timeout`` it is never recorded, and the recorders keep
    their signatures so subclasses that override them stay valid.
    """

    async def create(
        self,
        space: Any,
        text: str | None = None,
        *,
        thread: Any = None,
        reply_option: Any = None,
        request_id: str | None = None,
        message_id: str | None = None,
        timeout: float | None = None,
        markup_syntax: Any = None,
        accessory_widgets: Any = None,
        card: Any = None,
        notify: Any = None,
        private_to: Any = None,
        attachments: Any = None,
        citations: Any = None,
        cited_sources: Any = None,
    ) -> Message:
        return await self._bot.send_message(
            space,
            text,
            thread=thread,
            reply_option=reply_option,
            request_id=request_id,
            message_id=message_id,
            timeout=timeout,
            markup_syntax=markup_syntax,
            accessory_widgets=accessory_widgets,
            card=card,
            notify=notify,
            private_to=private_to,
            attachments=attachments,
            # Passed only when set: subclasses that override
            # send_message() without these keywords keep working.
            **{
                key: value
                for key, value in (
                    ("citations", citations),
                    ("cited_sources", cited_sources),
                )
                if value
            },
        )

    async def update(
        self,
        name: str,
        text: str | None = None,
        *,
        card: Any = None,
        markup_syntax: Any = None,
        timeout: float | None = None,
        config: Any = None,
    ) -> Message:
        message = await self._bot.update_message(name, text, card=card, timeout=timeout)
        if markup_syntax is not None:
            # Recorded here, not in update_message(): subclasses that
            # override the recording method keep their signature.
            message.markup_syntax = markup_syntax
            if self._bot.calls and self._bot.calls[-1][0] == "update_message":
                self._bot.calls[-1][1]["markup_syntax"] = markup_syntax
        return message

    async def replace_cards(
        self,
        name: str,
        cards: Any,
        *,
        timeout: float | None = None,
        config: Any = None,
    ) -> None:
        return await self._bot.replace_cards(name, cards, timeout=timeout)

    async def get(
        self, name: str, *, timeout: float | None = None, config: Any = None
    ) -> Message:
        return await self._bot.get_message(name, timeout=timeout)

    async def delete(
        self, name: str, *, timeout: float | None = None, config: Any = None
    ) -> None:
        return await self._bot.delete_message(name, timeout=timeout)


class _MockSpaces(_MockFacade):
    """Space resource facade over the recording methods.

    ``config`` is accepted and stops here, as on the message facade.
    """

    async def get(
        self,
        name: str,
        *,
        admin_access: bool = False,
        timeout: float | None = None,
        config: Any = None,
    ) -> Space:
        space = await self._bot.get_space(name, timeout=timeout)
        if admin_access and self._bot.calls and self._bot.calls[-1][0] == "get_space":
            # Recorded here, not in get_space(): subclasses that override
            # the recording method keep their signature.
            self._bot.calls[-1][1]["admin_access"] = True
        return space


class _MockIdentity(_MockFacade):
    """Identity namespace mirroring ``Bot.app`` / ``Bot.user``.

    MockBot does not model auth: both namespaces expose the same recorder.
    """

    @property
    def messages(self) -> _MockMessages:
        return _MockMessages(self._bot, f"{self._path}.messages")

    @property
    def spaces(self) -> _MockSpaces:
        return _MockSpaces(self._bot, f"{self._path}.spaces")


class MockBot:
    """Records outgoing calls and fabricates SDK proto responses.

    No transport, no network. Handlers call the same facade as the real
    client (``bot.app.messages.create(...)``, DI-compatible: handlers
    receive it by name (``feed_update(event, bot=mock_bot)``)). Recorded
    call kinds are the recording layer's names (``send_message``,
    ``update_message``); subclasses may override those recorders.

    Only ``messages.create`` / ``update`` / ``replace_cards`` / ``get`` /
    ``delete`` and ``spaces.get`` are mirrored, and nothing is validated:
    no identity preflight, no local checks, no preview gating. Any other
    resource or method raises ``AttributeError``; use
    :func:`chattice.testing.fake_bot` for those and for behaviour that
    depends on the real client.
    """

    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []

    @property
    def app(self) -> _MockIdentity:
        return _MockIdentity(self, "bot.app")

    @property
    def user(self) -> _MockIdentity:
        return _MockIdentity(self, "bot.user")

    async def send_message(
        self,
        space: Any,
        text: str | None = None,
        *,
        thread: Any = None,
        reply_option: Any = None,
        request_id: str | None = None,
        message_id: str | None = None,
        timeout: float | None = None,
        markup_syntax: Any = None,
        accessory_widgets: Any = None,
        card: Any = None,
        notify: Any = None,
        private_to: Any = None,
        attachments: Any = None,
        citations: Any = None,
        cited_sources: Any = None,
    ) -> Message:
        parent = space if isinstance(space, str) else space.name
        self.calls.append(
            (
                "send_message",
                {
                    "space": parent,
                    "text": text,
                    "card": card.to_dict() if card is not None else None,
                    "notify": notify,
                    "private_to": (
                        private_to.name if hasattr(private_to, "name") else private_to
                    ),
                    "attachments": (
                        [a.filename for a in attachments] if attachments else None
                    ),
                },
            )
        )
        name = f"{parent}/messages/{len(self.calls)}"
        message = Message(name=name, text=text or "")
        if markup_syntax is not None:
            self.calls[-1][1]["markup_syntax"] = markup_syntax
            message.markup_syntax = markup_syntax
        if citations:
            self.calls[-1][1]["citations"] = list(citations)
        if cited_sources:
            self.calls[-1][1]["cited_sources"] = list(cited_sources)
        return message

    async def upload_attachment(
        self, space: Any, file: Any, *, timeout: float | None = None
    ) -> UploadedAttachment:
        parent = space if isinstance(space, str) else space.name
        self.calls.append(
            (
                "upload_attachment",
                {"space": parent, "filename": file.filename},
            )
        )
        return UploadedAttachment(
            space=parent,
            filename=file.filename,
            attachment_data_ref={
                "resourceName": (f"{parent}/attachments/upload/{len(self.calls)}")
            },
        )

    async def download_attachment(
        self,
        attachment: Any,
        *,
        destination: str | Path | None = None,
        timeout: float | None = None,
    ) -> bytes | Path:
        name = (
            attachment.resource_name
            if hasattr(attachment, "resource_name")
            else str(attachment)
        )
        self.calls.append(("download_attachment", {"resource_name": name}))
        if destination is None:
            return b""
        path = Path(destination)
        path.write_bytes(b"")  # noqa: ASYNC240 — test stub, no real I/O guard
        return path

    async def get_attachment(
        self, name: str, *, timeout: float | None = None
    ) -> AttachmentRef:
        self.calls.append(("get_attachment", {"name": name}))
        return AttachmentRef(
            name=name,
            source=AttachmentSource.UPLOADED_CONTENT,
            attachment_data_ref={"resourceName": name},
        )

    async def get_message(self, name: str, *, timeout: float | None = None) -> Message:
        self.calls.append(("get_message", {"name": name}))
        return Message(name=name, text="")

    async def update_message(
        self,
        name: str,
        text: str | None = None,
        *,
        card: Any = None,
        timeout: float | None = None,
    ) -> Message:
        # Mirrors the real messages.update(name, text=None, *, card=...):
        # the card path records the card payload (the mirror must stay
        # in sync with the real client, including card=).
        self.calls.append(
            (
                "update_message",
                {
                    "name": name,
                    "text": text,
                    "card": card.to_dict() if card is not None else None,
                },
            )
        )
        return Message(name=name, text=text or "")

    async def replace_cards(
        self, name: str, cards: Any, *, timeout: float | None = None
    ) -> None:
        self.calls.append(
            (
                "replace_cards",
                {"name": name, "cards": [card.to_dict() for card in cards]},
            )
        )

    async def delete_message(self, name: str, *, timeout: float | None = None) -> None:
        self.calls.append(("delete_message", {"name": name}))

    async def get_space(self, name: str, *, timeout: float | None = None) -> Space:
        self.calls.append(("get_space", {"name": name}))
        return Space(name=name)

    def _sent_texts(self) -> list[str]:
        return [
            args["text"] or "" for kind, args in self.calls if kind == "send_message"
        ]

    def assert_message_sent(self, text: str | None = None, *, count: int = 1) -> None:
        """Assert send_message was called `count` times (optionally with text)."""
        sent = self._sent_texts()
        if len(sent) != count:
            raise AssertionError(
                f"expected {count} sent message(s), got {len(sent)}: {sent!r}"
            )
        if text is not None and sent != [text] * count:
            raise AssertionError(f"expected sent text {text!r} x{count}, got {sent!r}")

    def assert_updated(self, name: str, text: str) -> None:
        """Assert update_message was called with the given name/text."""
        for kind, args in self.calls:
            if (
                kind == "update_message"
                and args.get("name") == name
                and args.get("text") == text
            ):
                return
        raise AssertionError(
            f"expected update_message({name!r}, {text!r}), "
            f"calls: {[(k, a) for k, a in self.calls if k == 'update_message']!r}"
        )

    def assert_no_messages(self) -> None:
        """Assert nothing was sent."""
        sent = self._sent_texts()
        if sent:
            raise AssertionError(f"expected no sent messages, got {sent!r}")
