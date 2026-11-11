"""A real ``Bot`` on the in-memory fake transport, built in one call."""

from __future__ import annotations

from collections.abc import Iterable
from typing import NoReturn

from google.auth.credentials import AnonymousCredentials

from chattice.assets import AssetPublisher
from chattice.capabilities import PreviewFeature
from chattice.client import Bot

from .fake_transport import FakeChatTransport

__all__ = ["fake_bot"]


class _FakeCredentials(AnonymousCredentials):
    """Credentials that classify an identity and can never authorize a call.

    The GAPIC client never consults credentials when it is handed a
    transport instance, so every operation served by
    :class:`FakeChatTransport` works. Operations that bypass that
    transport (media upload/download, the experimental REST calls) sign
    their HTTP request with the credentials first; ``before_request``
    fails there, so a test never reaches the network.
    """

    def __init__(self) -> None:
        super().__init__()  # type: ignore[no-untyped-call]

    def before_request(
        self, request: object, method: object, url: object, headers: object
    ) -> NoReturn:
        raise RuntimeError(
            "fake_bot() credentials cannot authorize a real request to "
            f"{url!r}: only operations served by FakeChatTransport run "
            "without network. Media upload/download and experimental REST "
            "calls need their own test double."
        )


class _FakeAppCredentials(_FakeCredentials):
    """Service-account stand-in: a signer classifies as the APP identity."""

    def __init__(self) -> None:
        super().__init__()
        self.signer = object()


class _FakeUserCredentials(_FakeCredentials):
    """Authorized-user stand-in: a refresh token classifies as USER."""

    def __init__(self) -> None:
        super().__init__()
        self.refresh_token = "fake"


def fake_bot(
    *,
    user: bool = True,
    enable_preview: bool = False,
    preview_features: Iterable[PreviewFeature] | None = None,
    asset_publisher: AssetPublisher | None = None,
    addon_action_url: str | None = None,
) -> tuple[Bot, FakeChatTransport]:
    """Build a real :class:`~chattice.client.Bot` on one fake transport.

    Returns ``(bot, transport)``. The Bot is the production class, so
    identity preflight, local validation and preview gating run exactly
    as they do against Google; only the GAPIC transport is replaced.
    ``bot.app`` and ``bot.user`` share the returned
    :class:`FakeChatTransport` — seed its state and read its recorded
    requests there.

    ``user=False`` builds a Bot without a USER identity: USER-only
    operations raise ``CapabilityNotSupported``. ``enable_preview``,
    ``preview_features``, ``asset_publisher`` and ``addon_action_url``
    are passed to the Bot unchanged.

    The fake credentials carry no scopes, so preflight checks the
    identity of an operation and leaves scope decisions open, the same
    as production credentials with unknown scopes.
    """
    transport = FakeChatTransport()
    bot = Bot(
        app_credentials_provider=_FakeAppCredentials,
        user_credentials_provider=_FakeUserCredentials if user else None,
        asset_publisher=asset_publisher,
        transport=transport,
        enable_preview=enable_preview,
        preview_features=preview_features,
        addon_action_url=addon_action_url,
    )
    return bot, transport
