"""OperationExecutor: one path for every registered operation."""

from __future__ import annotations

import pytest
from google.api_core import exceptions as api_core_exceptions
from google.auth.credentials import AnonymousCredentials

from chattice.auth import AuthMode
from chattice.capabilities import CapabilityNotSupported, Operation
from chattice.capabilities.registry import OperationRegistry, UnknownOperation
from chattice.client import Bot
from chattice.client.config import RequestConfig
from chattice.client.errors import ChatPermissionDeniedError
from chattice.client.executor import OperationExecutor
from chattice.testing import FakeChatTransport
from tests.client.test_identity_clients import _creds


class _UserCredentials(AnonymousCredentials):
    """Authorized-user stand-in: a refresh_token classifies as USER."""

    def __init__(self) -> None:
        super().__init__()  # type: ignore[no-untyped-call]
        self.refresh_token = "rt"


def _user_creds() -> AnonymousCredentials:
    return _UserCredentials()


def _bot() -> Bot:
    return Bot(
        credentials=_creds(),
        transport=FakeChatTransport(credentials=_creds()),
    )


async def test_app_operation_routes_to_app_client() -> None:
    bot = _bot()
    executor: OperationExecutor[object] = OperationExecutor(bot)
    app_client = await bot._get_client_async()

    seen: list[object] = []

    async def call(client: object, config: RequestConfig) -> object:
        seen.append(client)
        return "ok"

    result = await executor.execute(
        Operation.MESSAGES_GET, identity=AuthMode.APP, call=call
    )
    assert result == "ok"
    assert seen == [app_client]


async def test_user_operation_routes_to_user_client() -> None:
    bot = Bot(
        app_credentials_provider=lambda: _creds(),
        user_credentials_provider=lambda: _user_creds(),
        transport=FakeChatTransport(credentials=_creds()),
    )
    executor: OperationExecutor[object] = OperationExecutor(bot)
    user_client = await bot._get_user_client_async()

    seen: list[object] = []

    async def call(client: object, config: RequestConfig) -> object:
        seen.append(client)
        return "ok"

    await executor.execute(Operation.MESSAGES_GET, identity=AuthMode.USER, call=call)
    assert seen == [user_client]


async def test_wrong_identity_fails_without_fallback() -> None:
    bot = _bot()
    executor: OperationExecutor[object] = OperationExecutor(bot)

    async def call(client: object, config: RequestConfig) -> object:
        raise AssertionError("must not be called")

    with pytest.raises(CapabilityNotSupported):
        # SPACES_LIST is APP-only; USER must fail, never fall back to APP.
        await executor.execute(Operation.SPACES_LIST, identity=AuthMode.USER, call=call)


async def test_unknown_operation_raises() -> None:
    bot = _bot()
    executor: OperationExecutor[object] = OperationExecutor(
        bot, registry=OperationRegistry([])
    )

    async def call(client: object, config: RequestConfig) -> object:
        raise AssertionError("must not be called")

    with pytest.raises(UnknownOperation):
        await executor.execute(
            Operation.SPACES_SEARCH, identity=AuthMode.APP, call=call
        )


async def test_config_is_passed_through() -> None:
    bot = _bot()
    executor: OperationExecutor[object] = OperationExecutor(bot)
    seen: list[RequestConfig] = []

    async def call(client: object, config: RequestConfig) -> object:
        seen.append(config)
        return "ok"

    config = RequestConfig(timeout=5.0)
    await executor.execute(
        Operation.MESSAGES_GET, identity=AuthMode.APP, call=call, config=config
    )
    assert seen == [config]


async def test_google_api_errors_are_wrapped() -> None:
    bot = _bot()
    executor: OperationExecutor[object] = OperationExecutor(bot)

    async def call(client: object, config: RequestConfig) -> object:
        raise api_core_exceptions.PermissionDenied("denied")  # type: ignore[no-untyped-call]

    with pytest.raises(ChatPermissionDeniedError):
        await executor.execute(Operation.MESSAGES_GET, identity=AuthMode.APP, call=call)


async def test_non_google_errors_pass_through_untouched() -> None:
    bot = _bot()
    executor: OperationExecutor[object] = OperationExecutor(bot)

    class _BusinessError(Exception):
        pass

    async def call(client: object, config: RequestConfig) -> object:
        raise _BusinessError("boom")

    with pytest.raises(_BusinessError):
        await executor.execute(Operation.MESSAGES_GET, identity=AuthMode.APP, call=call)


async def test_executor_reuses_existing_client_cache() -> None:
    bot = _bot()
    executor: OperationExecutor[object] = OperationExecutor(bot)

    async def call(client: object, config: RequestConfig) -> object:
        return client

    first = await executor.execute(
        Operation.MESSAGES_GET, identity=AuthMode.APP, call=call
    )
    second = await executor.execute(
        Operation.MESSAGES_GET, identity=AuthMode.APP, call=call
    )
    assert first is second
    assert first is bot._client  # same cache as raw.app() uses


def test_gapic_kwargs_omit_defaults_for_raw_gapic_behavior() -> None:
    """A default RequestConfig must reproduce raw GAPIC defaults exactly."""
    from chattice.client.executor import OperationExecutor

    assert OperationExecutor.gapic_kwargs(RequestConfig()) == {}


def test_gapic_kwargs_pass_explicit_values() -> None:
    from chattice.client.executor import OperationExecutor

    kwargs = OperationExecutor.gapic_kwargs(RequestConfig(timeout=5.0))
    assert kwargs == {"timeout": 5.0}
    assert "retry" not in kwargs  # None must NOT disable SDK retries
    assert "metadata" not in kwargs


def test_request_config_is_immutable() -> None:
    import dataclasses

    config = RequestConfig(timeout=1.0)
    with pytest.raises(dataclasses.FrozenInstanceError):
        config.timeout = 2.0  # type: ignore[misc]
