# ruff: noqa: ASYNC109 — timeout kwarg mirrors the outbound client convention
"""REST access to Developer Preview methods the official client lacks.

``google-apps-chat`` is generated from the generally available API, so
Developer Preview resources (stream messages, thread sessions) have no
GAPIC methods. Everything in ``chattice.experimental`` that needs them
goes through :class:`PreviewTransport`; the default implementation uses
google-auth's ``AuthorizedSession`` in a worker thread.
"""

from __future__ import annotations

import asyncio
from collections.abc import Mapping
from typing import Any, Protocol, cast

from google.api_core import exceptions as api_core_exceptions
from google.auth import credentials as auth_credentials

from chattice.auth import AuthMode
from chattice.capabilities import CapabilityNotSupported, PreviewFeature
from chattice.client import Bot
from chattice.client.errors import wrap_api_error

__all__ = ["PreviewTransport", "RestTransport", "require_app_preview"]

_BASE_URL = "https://chat.googleapis.com/v1/"
_SCOPE = "https://www.googleapis.com/auth/chat.bot"
_DEFAULT_TIMEOUT = 60.0


class PreviewTransport(Protocol):
    """Sends one authenticated Chat REST request and returns the JSON body."""

    async def request(
        self,
        method: str,
        path: str,
        *,
        params: Mapping[str, str] | None = None,
        body: Mapping[str, object] | None = None,
        timeout: float | None = None,
    ) -> dict[str, object]: ...


async def require_app_preview(bot: Bot, feature: PreviewFeature, what: str) -> None:
    """Fail closed unless ``feature`` is enrolled and the identity is the app."""
    bot.preview_capabilities.require(feature, what=what)
    mode = await bot._auth_mode_async()
    if mode is AuthMode.USER or mode is AuthMode.NONE:
        raise CapabilityNotSupported(
            f"{what} requires app authentication (chat.bot); "
            "user authentication is not supported by Google."
        )


class RestTransport:
    """Default transport: the Bot's APP credentials over ``AuthorizedSession``."""

    def __init__(self, bot: Bot) -> None:
        self._bot = bot

    async def request(
        self,
        method: str,
        path: str,
        *,
        params: Mapping[str, str] | None = None,
        body: Mapping[str, object] | None = None,
        timeout: float | None = None,
    ) -> dict[str, object]:
        credentials = await self._bot._resolve_credentials_async()
        if credentials is None:
            raise CapabilityNotSupported(
                "The APP identity has no credentials; pass google.auth "
                "credentials or a credentials_provider to Bot(...)"
            )
        scoped = auth_credentials.with_scopes_if_required(  # type: ignore[no-untyped-call]
            credentials, [_SCOPE]
        )
        return await asyncio.to_thread(
            self._send, scoped, method, path, params, body, timeout
        )

    @staticmethod
    def _send(
        credentials: Any,
        method: str,
        path: str,
        params: Mapping[str, str] | None,
        body: Mapping[str, object] | None,
        timeout: float | None,
    ) -> dict[str, object]:
        from google.auth.transport.requests import AuthorizedSession

        session = AuthorizedSession(credentials)  # type: ignore[no-untyped-call]
        try:
            response = session.request(  # type: ignore[no-untyped-call]
                method,
                _BASE_URL + path,
                params=params,
                json=body,
                timeout=timeout if timeout is not None else _DEFAULT_TIMEOUT,
            )
            if response.status_code >= 400:
                error = api_core_exceptions.from_http_response(response)  # type: ignore[no-untyped-call]
                raise wrap_api_error(error) from error
            return cast(dict[str, object], response.json()) if response.content else {}
        finally:
            session.close()  # type: ignore[no-untyped-call]
