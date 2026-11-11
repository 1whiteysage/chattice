"""Base for identity-bound resource clients."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING, Any, Concatenate, ParamSpec, TypeVar

from google.apps.chat_v1 import ChatServiceAsyncClient

from chattice.auth import AuthMode
from chattice.capabilities.operations import ExecutionVariant, Operation
from chattice.client.config import RequestConfig
from chattice.client.executor import OperationExecutor

if TYPE_CHECKING:
    from chattice.client.bot import Bot

__all__ = ["ResourceClient"]

_P = ParamSpec("_P")
_R = TypeVar("_R")


def _effective_config(
    config: RequestConfig | None, timeout: float | None
) -> RequestConfig:
    """Per-call config override: ``config`` wins over the ``timeout`` shorthand."""
    if config is not None:
        return config
    return RequestConfig(timeout=timeout)


class _Rpc:
    """One registered operation, ready to run a single GAPIC method."""

    __slots__ = ("_config", "_executor", "_identity", "_operation", "_variant")

    def __init__(
        self,
        executor: OperationExecutor[Any],
        operation: Operation,
        identity: AuthMode,
        config: RequestConfig,
        variant: ExecutionVariant,
    ) -> None:
        self._executor = executor
        self._operation = operation
        self._identity = identity
        self._config = config
        self._variant = variant

    async def __call__(
        self,
        method: Callable[Concatenate[ChatServiceAsyncClient, _P], Awaitable[_R]],
        *args: _P.args,
        **kwargs: _P.kwargs,
    ) -> _R:
        """Call ``method`` on the identity's client with the request config.

        ``method`` is the unbound SDK method, so the arguments and the
        result are type-checked against the SDK. It is looked up by name
        on the resolved client, which keeps substituted clients working.
        """
        name = method.__name__

        async def call(client: ChatServiceAsyncClient, cfg: RequestConfig) -> _R:
            bound: Callable[..., Awaitable[_R]] = getattr(client, name)
            return await bound(*args, **kwargs, **OperationExecutor.gapic_kwargs(cfg))

        if self._variant is ExecutionVariant.NORMAL:
            normal: _R = await self._executor.execute(
                self._operation,
                identity=self._identity,
                call=call,
                config=self._config,
            )
            return normal
        result: _R = await self._executor.execute(
            self._operation,
            identity=self._identity,
            call=call,
            config=self._config,
            variant=self._variant,
        )
        return result


class ResourceClient:
    """Base class for one resource facade bound to one identity.

    Subclasses own ONLY input normalization, request building, and
    response normalization. Credential selection, preflight, client
    lifecycle, timeout/retry/metadata plumbing, and the exception policy
    all live in :class:`OperationExecutor`.
    """

    def __init__(self, bot: Bot, identity: AuthMode) -> None:
        self._bot = bot
        self._identity = identity
        self._executor: OperationExecutor[Any] = OperationExecutor(bot)

    @property
    def identity(self) -> AuthMode:
        return self._identity

    def _rpc(
        self,
        operation: Operation,
        config: RequestConfig,
        *,
        admin_access: bool = False,
    ) -> _Rpc:
        """The single way a resource method reaches the SDK.

        ``await self._rpc(Operation.X, config)(ChatServiceAsyncClient.x,
        request=...)`` runs the executor chain (spec lookup, preview
        gate, identity preflight, error policy) for THIS identity.

        ``admin_access`` preflights the operation's administrator auth
        path; the caller also sets ``use_admin_access`` on the request.
        """
        variant = ExecutionVariant.ADMIN if admin_access else ExecutionVariant.NORMAL
        return _Rpc(self._executor, operation, self._identity, config, variant)

    async def _preflight(self, operation: Operation) -> None:
        """Registry preflight for THIS identity, before any side work.

        Runs the executor's spec/preview/preflight chain with a no-op
        call — used when a resource must fail locally BEFORE expensive
        or irreversible work (e.g. media uploads).
        """

        async def _noop(client: object, cfg: RequestConfig) -> None:
            del client, cfg

        await self._executor.execute(
            operation,
            identity=self._identity,
            call=_noop,
        )
