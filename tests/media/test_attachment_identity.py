"""Attachment message identity routing.

Verified against the Google Chat API:

- USER media.upload -> APP messages.create returns
  "Caller does not have permission to access requested attachment".
- USER media.upload -> USER messages.create succeeds; sender.type = HUMAN.

Therefore an attachment-bearing message must be sent end-to-end through
the USER identity; the APP client must not be used for the final create.
No real Space IDs, user IDs, emails, message IDs, tokens, or
service-account data are stored in this repository.
"""

from __future__ import annotations

import asyncio
from typing import Any

import pytest
from google.apps.chat_v1 import ChatServiceAsyncClient
from google.apps.chat_v1.types import CreateMessageRequest
from google.auth.credentials import AnonymousCredentials, Credentials

import chattice.media._rest  # noqa: F401 — imported for monkeypatching
from chattice.capabilities import CapabilityNotSupported
from chattice.cards import Card
from chattice.client import Bot
from chattice.events import ThreadRef
from chattice.media import InputFile, UploadedAttachment
from chattice.testing.fake_transport import FakeChatTransport


class _UserCreds(AnonymousCredentials):
    def __init__(self) -> None:
        super().__init__()  # type: ignore[no-untyped-call]
        self.refresh_token = "user-token"
        self.scopes = ("https://www.googleapis.com/auth/chat.messages",)


class _AppCreds(AnonymousCredentials):
    def __init__(self) -> None:
        super().__init__()  # type: ignore[no-untyped-call]
        self.signer = object()
        self.scopes = ("https://www.googleapis.com/auth/chat.bot",)


def _dual_bot(transport: FakeChatTransport | None = None) -> Bot:
    return Bot(
        app_credentials_provider=lambda: _AppCreds(),
        user_credentials_provider=lambda: _UserCreds(),
        transport=transport,
    )


def _user_client(fake: FakeChatTransport) -> ChatServiceAsyncClient:
    """A real GAPIC client over the fake transport (the USER client path)."""
    return ChatServiceAsyncClient(transport=fake)


def _user_client_getter(fake: FakeChatTransport) -> Any:
    """An awaitable stand-in for Bot._get_user_client_async()."""

    async def getter(self: Bot) -> ChatServiceAsyncClient:
        return _user_client(fake)

    return getter


def _app_create_must_not_run() -> Any:
    async def app_client_fake() -> object:
        return _AppCreateGuard()

    return app_client_fake


class _AppCreateGuard:
    async def create_message(self, **kwargs: Any) -> None:
        raise AssertionError("APP client must not be used for attachment create")


def _fake_upload(monkeypatch: pytest.MonkeyPatch) -> list[Credentials]:
    captured: list[Credentials] = []

    def fake_upload(
        credentials: Credentials,
        parent: str,
        filename: str,
        content_type: str | None,
        data: bytes,
        timeout: float | None,
    ) -> dict[str, Any]:
        captured.append(credentials)
        return {"attachmentDataRef": {"resourceName": f"media/{filename}"}}

    monkeypatch.setattr("chattice.media._rest.upload_media", fake_upload)
    return captured


async def test_dual_bot_plain_text_uses_app_client(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user_client_calls: list[int] = []

    async def user_client_fake() -> object:
        user_client_calls.append(1)
        raise AssertionError("USER client must not be used for a plain send")

    monkeypatch.setattr(
        "chattice.client.bot.Bot._get_user_client_async", user_client_fake
    )
    transport = FakeChatTransport()
    bot = _dual_bot(transport)
    await bot.app.messages.create("spaces/A", text="hello")
    assert transport.calls == [1]
    assert user_client_calls == []


async def test_dual_identity_attachment_create_uses_user_client(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A user-authenticated upload must be followed by a
    USER create; the APP client must never touch attachment sends."""
    uploaded_creds = _fake_upload(monkeypatch)
    user_transport = FakeChatTransport()
    monkeypatch.setattr(
        "chattice.client.bot.Bot._get_user_client_async",
        _user_client_getter(user_transport),
    )
    monkeypatch.setattr(
        "chattice.client.bot.Bot._get_client_async", _app_create_must_not_run()
    )
    bot = _dual_bot()
    result = await bot.user.messages.create(
        "spaces/A",
        text="report",
        attachments=[InputFile.from_bytes(b"data", filename="report.png")],
    )
    assert result.name == "spaces/A/messages/fake-1"
    assert uploaded_creds and uploaded_creds[0] is bot._resolved_user_credentials
    created = user_transport.requests[-1]
    assert created.message.attachment[0].attachment_data_ref.resource_name == (
        "media/report.png"
    )


async def test_dual_bot_uploaded_attachment_uses_user_create(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    uploaded = _fake_upload(monkeypatch)
    user_transport = FakeChatTransport()
    monkeypatch.setattr(
        "chattice.client.bot.Bot._get_user_client_async",
        _user_client_getter(user_transport),
    )
    monkeypatch.setattr(
        "chattice.client.bot.Bot._get_client_async", _app_create_must_not_run()
    )
    bot = _dual_bot()
    attachment = UploadedAttachment(
        space="spaces/A",
        filename="x.png",
        attachment_data_ref={
            "resourceName": "media/r",
            "attachmentUploadToken": "tok",
        },
    )
    await bot.user.messages.create("spaces/A", attachments=[attachment])
    assert uploaded == []  # no re-upload for an already-uploaded attachment
    entry = user_transport.requests[-1].message.attachment[0]
    assert entry.attachment_data_ref.resource_name == "media/r"
    assert entry.attachment_data_ref.attachment_upload_token == "tok"


async def test_user_only_bot_attachment_flow(monkeypatch: pytest.MonkeyPatch) -> None:
    uploaded = _fake_upload(monkeypatch)
    transport = FakeChatTransport()
    bot = Bot(credentials=_UserCreds(), transport=transport)
    await bot.user.messages.create(
        "spaces/A",
        attachments=[InputFile.from_bytes(b"data", filename="x.png")],
    )
    assert uploaded
    created = transport.requests[-1].message.attachment[0]
    assert created.attachment_data_ref.resource_name == "media/x.png"


async def test_app_only_bot_attachment_send_rejected_locally(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    uploaded = _fake_upload(monkeypatch)
    transport = FakeChatTransport()
    bot = Bot(credentials=_AppCreds(), transport=transport)
    with pytest.raises(CapabilityNotSupported, match="requires USER authentication"):
        await bot.user.messages.create(
            "spaces/A",
            attachments=[InputFile.from_bytes(b"data", filename="x.png")],
        )
    assert uploaded == []  # zero media calls
    assert transport.calls == []  # zero create calls


async def test_attachments_with_notify_rejected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _fake_upload(monkeypatch)
    bot = _dual_bot(FakeChatTransport())
    with pytest.raises(
        CapabilityNotSupported, match="cannot be combined with attachments"
    ):
        await bot.user.messages.create(
            "spaces/A",
            notify="force",
            attachments=[InputFile.from_bytes(b"x", filename="x.png")],
        )


async def test_attachments_with_card_use_user_create(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """User-auth cards are GA: no local rejection, Google decides."""
    _fake_upload(monkeypatch)
    user_transport = FakeChatTransport()
    monkeypatch.setattr(
        "chattice.client.bot.Bot._get_user_client_async",
        _user_client_getter(user_transport),
    )
    monkeypatch.setattr(
        "chattice.client.bot.Bot._get_client_async", _app_create_must_not_run()
    )
    await _dual_bot().user.messages.create(
        "spaces/A",
        card=Card(),
        attachments=[InputFile.from_bytes(b"x", filename="x.png")],
    )
    message = user_transport.requests[-1].message
    assert len(message.cards_v2) == 1
    assert len(message.attachment) == 1


async def test_attachment_thread_reply_uses_user_create(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _fake_upload(monkeypatch)
    user_transport = FakeChatTransport()
    monkeypatch.setattr(
        "chattice.client.bot.Bot._get_user_client_async",
        _user_client_getter(user_transport),
    )
    monkeypatch.setattr(
        "chattice.client.bot.Bot._get_client_async", _app_create_must_not_run()
    )
    bot = _dual_bot()
    await bot.user.messages.create(
        "spaces/A",
        text="in thread",
        thread=ThreadRef(name="spaces/A/threads/T1"),
        attachments=[InputFile.from_bytes(b"x", filename="x.png")],
        reply_option=CreateMessageRequest.MessageReplyOption.REPLY_MESSAGE_OR_FAIL,
    )
    request = user_transport.requests[-1]
    assert request.message.thread.name == "spaces/A/threads/T1"
    assert (
        request.message_reply_option == request.MessageReplyOption.REPLY_MESSAGE_OR_FAIL
    )


async def test_failed_user_credential_resolution_is_retryable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _fake_upload(monkeypatch)
    attempts: list[int] = []

    def flaky_user_provider() -> Credentials:
        attempts.append(1)
        if len(attempts) == 1:
            raise RuntimeError("provider transient failure")
        return _UserCreds()

    bot = Bot(
        app_credentials_provider=lambda: _AppCreds(),
        user_credentials_provider=flaky_user_provider,
    )
    user_transport = FakeChatTransport()
    monkeypatch.setattr(
        "chattice.client.bot.Bot._get_user_client_async",
        _user_client_getter(user_transport),
    )
    with pytest.raises(RuntimeError, match="transient"):
        await bot.user.messages.create(
            "spaces/A",
            attachments=[InputFile.from_bytes(b"x", filename="x.png")],
        )
    await bot.user.messages.create(
        "spaces/A",
        attachments=[InputFile.from_bytes(b"y", filename="y.png")],
    )
    assert len(user_transport.requests) == 1
    assert attempts == [1, 1]


async def test_concurrent_attachment_sends_init_user_client_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _fake_upload(monkeypatch)
    user_provider_calls: list[int] = []

    def user_provider() -> Credentials:
        user_provider_calls.append(1)
        return _UserCreds()

    user_transport = FakeChatTransport()
    init_calls: list[int] = []
    original = Bot._initialize_user_client

    async def counted_init(self: Bot) -> ChatServiceAsyncClient:
        init_calls.append(1)
        await asyncio.sleep(0)
        return await original(self)

    monkeypatch.setattr("chattice.client.bot.Bot._initialize_user_client", counted_init)
    monkeypatch.setattr(
        "chattice.client.bot.Bot._build_user_client",
        lambda self, credentials: _user_client(user_transport),
    )
    bot = Bot(
        app_credentials_provider=lambda: _AppCreds(),
        user_credentials_provider=user_provider,
    )
    await asyncio.gather(
        bot.user.messages.create(
            "spaces/A",
            attachments=[InputFile.from_bytes(b"1", filename="one.png")],
        ),
        bot.user.messages.create(
            "spaces/A",
            attachments=[InputFile.from_bytes(b"2", filename="two.png")],
        ),
    )
    assert len(user_transport.requests) == 2
    assert init_calls == [1]  # one shared USER client construction
    assert user_provider_calls == [1]  # one USER credential resolution


async def test_close_closes_app_and_user_clients_exactly_once() -> None:
    class _Transport:
        def __init__(self) -> None:
            self.closed = 0

        def close(self) -> None:
            self.closed += 1

    class _Client:
        def __init__(self, transport: _Transport) -> None:
            self.transport = transport

    app_transport = _Transport()
    user_transport = _Transport()
    bot = _dual_bot()
    bot._client = _Client(app_transport)  # type: ignore[assignment]
    bot._user_client = _Client(user_transport)  # type: ignore[assignment]
    await bot.close()
    await bot.close()
    assert app_transport.closed == 1
    assert user_transport.closed == 1
