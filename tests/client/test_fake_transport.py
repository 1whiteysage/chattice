"""Smoke test for the in-memory fake transport."""

from __future__ import annotations

import inspect

from google.apps.chat_v1 import ChatServiceClient
from google.apps.chat_v1.types.message import CreateMessageRequest, Message
from google.auth.credentials import AnonymousCredentials

from ._fake_transport import FakeChatTransport


async def test_create_round_trip() -> None:
    transport = FakeChatTransport()
    request = CreateMessageRequest(
        parent="spaces/AAA",
        message=Message(text="hello"),
    )
    result = await transport.create_message(request)
    assert result.name.startswith("spaces/AAA/messages/")
    assert result.text == "hello"
    assert transport.requests == [request]
    assert inspect.iscoroutinefunction(transport.create_message)


def test_host_and_wrapped_methods_exist() -> None:
    transport = FakeChatTransport()
    assert transport.host == "fake-chat"
    # The gapic client looks the wrapped method up by the BOUND method object.
    assert transport.create_message in transport._wrapped_methods
    assert transport.delete_message in transport._wrapped_methods


async def test_round_trip_through_real_gapic_client() -> None:
    """Prove the fake satisfies the real gapic transport contract."""
    credentials = AnonymousCredentials()  # type: ignore[no-untyped-call]
    transport = FakeChatTransport(credentials=credentials)
    # With a transport instance the client must NOT receive credentials —
    # the instance carries them ("provide its credentials directly").
    client = ChatServiceClient(transport=transport)
    result = await client.create_message(
        request=CreateMessageRequest(
            parent="spaces/AAA", message=Message(text="via client")
        )
    )
    assert result.text == "via client"
    assert result.name.startswith("spaces/AAA/messages/")
    assert transport.requests[-1].parent == "spaces/AAA"
