"""Single execution path for every registered outbound operation.

One operation -> one registry entry -> one executor path -> explicit
APP/USER identity -> one GAPIC call. Resource clients pass a closure
that performs the actual RPC on the resolved client; the executor owns
spec lookup, preview gating, identity preflight, client selection, and
the exception policy.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING, Any, Generic, TypeVar

from google.api_core import exceptions as api_core_exceptions

from chattice.auth import AuthMode
from chattice.capabilities import (
    CapabilityNotSupported,
    ExecutionVariant,
    Operation,
)
from chattice.capabilities.registry import REGISTRY, OperationRegistry
from chattice.client.config import RequestConfig
from chattice.client.errors import wrap_api_error

if TYPE_CHECKING:
    from google.apps.chat_v1 import ChatServiceAsyncClient

    from chattice.client.bot import Bot

__all__ = ["OperationExecutor"]

T = TypeVar("T")

_RpcCall = Callable[["ChatServiceAsyncClient", RequestConfig], Awaitable[T]]


class OperationExecutor(Generic[T]):
    """Execute one registered operation for one explicit identity.

    Never selects identity on its own; never falls back between APP and
    USER. Google API exceptions are wrapped into the curated
    ``Chat*Error`` family (the documented executor policy); all other
    exceptions pass through untouched.
    """

    def __init__(self, bot: Bot, registry: OperationRegistry | None = None) -> None:
        self._bot = bot
        self._registry = registry or REGISTRY

    async def execute(
        self,
        operation: Operation,
        *,
        identity: AuthMode,
        call: _RpcCall[T],
        config: RequestConfig | None = None,
        variant: ExecutionVariant = ExecutionVariant.NORMAL,
    ) -> T:
        """Run ``call`` after the registry checks for ``identity``.

        ``variant`` selects the auth paths the preflight accepts; the
        caller sets the matching request flag (for ``ADMIN``:
        ``use_admin_access``) on the request it sends.
        """
        spec = self._registry.spec(operation)
        if config is None:
            config = RequestConfig()
        if spec.preview and not self._bot._preview_enabled:
            raise CapabilityNotSupported(
                f"{operation.name} is a preview operation and requires "
                "explicit opt-in: Bot(..., enable_preview=True)"
            )
        await self._bot._preflight_operation(
            operation, identity=identity, variant=variant, registry=self._registry
        )
        client = await self._resolve_client(identity)
        try:
            return await call(client, config)
        except api_core_exceptions.GoogleAPICallError as error:
            raise wrap_api_error(error) from error

    async def _resolve_client(self, identity: AuthMode) -> ChatServiceAsyncClient:
        if identity is AuthMode.USER:
            return await self._bot._get_user_client_async()
        return await self._bot._get_client_async()

    @staticmethod
    def gapic_kwargs(config: RequestConfig) -> dict[str, Any]:
        """Build GAPIC call kwargs from a RequestConfig.

        ``None`` / empty values are OMITTED, so a default RequestConfig
        reproduces raw GAPIC defaults exactly (no accidental retry=None
        disabling the SDK's own retry policy).
        """
        kwargs: dict[str, object] = {}
        if config.timeout is not None:
            kwargs["timeout"] = config.timeout
        if config.retry is not None:
            kwargs["retry"] = config.retry
        if config.metadata:
            kwargs["metadata"] = config.metadata
        return kwargs
