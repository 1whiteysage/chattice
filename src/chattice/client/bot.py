"""High-level async Bot: authenticated outgoing Chat API operations."""

from __future__ import annotations

import asyncio
import inspect
from collections.abc import Awaitable, Callable, Iterable, Mapping
from typing import Any, TypeAlias, cast

from google.apps.chat_v1 import ChatServiceAsyncClient
from google.apps.chat_v1.services.chat_service.transports import (
    ChatServiceTransport,
)
from google.apps.chat_v1.types.attachment import AttachmentDataRef
from google.auth.credentials import Credentials

from chattice.assets import AssetPublisher
from chattice.auth import AuthMode, CredentialsProvider
from chattice.capabilities import (
    REGISTRY,
    CapabilityNotSupported,
    ExecutionVariant,
    Operation,
    OperationRegistry,
    PreviewCapabilities,
    PreviewFeature,
)
from chattice.events import SpaceRef, UserRef

from ._names import _canonical_space, _canonical_user
from .errors import ChatAPIError
from .executor import OperationExecutor
from .resources import (
    Attachments,
    CustomEmojis,
    Memberships,
    MessagePins,
    Messages,
    Reactions,
    Spaces,
    Users,
)

_GRPC_ASYNCIO = "grpc_asyncio"


def _attachment_data_ref_proto(mapping: Mapping[str, object]) -> AttachmentDataRef:
    """Build the SDK proto from a wire ``attachmentDataRef`` mapping."""
    kwargs: dict[str, Any] = {}
    resource_name = mapping.get("resourceName") or mapping.get("resource_name")
    if isinstance(resource_name, str) and resource_name:
        kwargs["resource_name"] = resource_name
    upload_token = mapping.get("attachmentUploadToken") or mapping.get(
        "attachment_upload_token"
    )
    if isinstance(upload_token, str) and upload_token:
        kwargs["attachment_upload_token"] = upload_token
    return AttachmentDataRef(**kwargs)


def _scope_attribute(credentials: Credentials, attribute: str) -> frozenset[str] | None:
    """Read a local credential scope attribute without doing any I/O."""
    value = cast(object, getattr(credentials, attribute, None))
    if value is None:
        return None
    if isinstance(value, str):
        return frozenset({value})
    if not isinstance(value, Iterable):
        return None
    scopes: set[str] = set()
    for scope in cast(Iterable[object], value):
        if not isinstance(scope, str):
            return None
        scopes.add(scope)
    return frozenset(scopes)


def _credential_scopes(
    auth_mode: AuthMode, credentials: Credentials | None
) -> frozenset[str] | None:
    """Return reliably known local scopes, or None when they are unknown.

    User token responses can narrow originally requested scopes, so an
    available ``granted_scopes`` value wins. App credentials use configured
    explicit/default scopes; neither source proves Workspace administrator
    approval for ``chat.app.*`` scopes.
    """
    if credentials is None:
        return None
    if auth_mode is AuthMode.USER:
        granted = _scope_attribute(credentials, "granted_scopes")
        if granted is not None:
            return granted
        return _scope_attribute(credentials, "scopes")
    if auth_mode is AuthMode.APP:
        explicit = _scope_attribute(credentials, "scopes")
        defaults = _scope_attribute(credentials, "default_scopes")
        if explicit is None and defaults is None:
            return None
        return (explicit or frozenset()) | (defaults or frozenset())
    return frozenset()


def _membership_name(space: SpaceRef | str, user: UserRef | str) -> str:
    """Build a membership resource name without a remote lookup."""
    parent = _canonical_space(space)
    member = _canonical_user(user, parameter="user").removeprefix("users/")
    return f"{parent}/members/{member}"


class RawClients:
    """Explicit raw client access: APP or USER identity.

    Each accessor builds and serves exactly the identity it names, so
    dual-auth-sensitive operations never depend on an implicit primary
    identity.
    """

    def __init__(self, bot: Bot) -> None:
        self._bot = bot

    async def app(self) -> ChatServiceAsyncClient:
        """The raw APP-authenticated Chat client."""
        return await self._bot._get_client_async()

    async def user(self) -> ChatServiceAsyncClient:
        """The raw USER-authenticated Chat client.

        Raises ``CapabilityNotSupported`` when no USER credentials are
        configured on the Bot.
        """
        return await self._bot._get_user_client_async()


_ClientGetter: TypeAlias = Callable[[], Awaitable[ChatServiceAsyncClient]]


class IdentityNamespace:
    """Operations pinned to ONE auth identity: APP or USER (ADR-012).

    A pure facade: no credential I/O at construction, no own GAPIC
    lifecycle. Resource clients attach lazily and delegate every check
    to the OperationRegistry.
    """

    def __init__(
        self, bot: Bot, identity: AuthMode, *, allow_setup: bool = False
    ) -> None:
        self._bot = bot
        self._identity = identity
        self._allow_setup = allow_setup

    @property
    def identity(self) -> AuthMode:
        return self._identity

    @property
    def spaces(self) -> Spaces:
        """Space operations executed with THIS identity."""
        return Spaces(self._bot, self._identity, allow_setup=self._allow_setup)

    @property
    def messages(self) -> Messages:
        """Message operations executed with THIS identity."""
        return Messages(self._bot, self._identity)

    @property
    def memberships(self) -> Memberships:
        """Membership operations executed with THIS identity."""
        return Memberships(self._bot, self._identity)

    @property
    def reactions(self) -> Reactions:
        """Reaction operations executed with THIS identity (USER-only)."""
        return Reactions(self._bot, self._identity)

    @property
    def custom_emojis(self) -> CustomEmojis:
        """Custom emoji operations executed with THIS identity (USER-only)."""
        return CustomEmojis(self._bot, self._identity)

    @property
    def message_pins(self) -> MessagePins:
        """Message pin operations executed with THIS identity (USER-only)."""
        return MessagePins(self._bot, self._identity)

    @property
    def users(self) -> Users:
        """Per-user state operations (USER-only)."""
        return Users(self._bot, self._identity)

    @property
    def attachments(self) -> Attachments:
        """Attachment operations executed with THIS identity."""
        return Attachments(self._bot, self._identity)


class Bot:
    """Authenticated outgoing Google Chat operations.

    The SDK client is created lazily on the first call so that Bot() can be
    constructed before credentials are available (e.g. in app factories).
    """

    def __init__(
        self,
        credentials: Credentials | None = None,
        *,
        credentials_provider: CredentialsProvider | None = None,
        app_credentials_provider: CredentialsProvider | None = None,
        user_credentials_provider: CredentialsProvider | None = None,
        asset_publisher: AssetPublisher | None = None,
        auth_mode: AuthMode | None = None,
        transport: ChatServiceTransport | None = None,
        enable_preview: bool = False,
        preview_features: Iterable[PreviewFeature] | None = None,
        addon_action_url: str | None = None,
    ) -> None:
        has_dual_providers = (
            app_credentials_provider is not None
            or user_credentials_provider is not None
        )
        if has_dual_providers:
            if credentials is not None or credentials_provider is not None:
                raise ValueError(
                    "app_credentials_provider/user_credentials_provider cannot "
                    "be combined with credentials/credentials_provider"
                )
            if auth_mode is not None:
                raise ValueError(
                    "auth_mode is implied by the app/user credential "
                    "providers; pass it only for a single-identity Bot"
                )
        self._credentials = credentials
        # Explicit app/user providers take precedence; credentials_provider
        # covers single-identity construction.
        self._credentials_provider = credentials_provider or app_credentials_provider
        self._user_credentials_provider = user_credentials_provider
        self._auth_mode = auth_mode
        self._transport = transport
        # Preview gating: registry is the source of truth for WHICH
        # operations are preview; this flag is the user's explicit
        # opt-in (per Bot instance).
        # ``enable_preview=True`` enrolls in every Developer Preview
        # feature; ``preview_features`` enrolls in the named ones. A
        # Dispatcher constructed with this Bot routes preview events by
        # the same enrollment.
        self._preview = PreviewCapabilities(preview_features or ())
        if enable_preview:
            self._preview = self._preview | PreviewCapabilities.all()
        # A Chat app built as an HTTP Google Workspace add-on addresses
        # card actions by endpoint URL (chattice.cards.addon). When set,
        # cards and accessory widgets sent through this Bot are bound to
        # that endpoint.
        if addon_action_url is not None and not addon_action_url.startswith("https://"):
            raise ValueError(
                "addon_action_url must be the HTTPS endpoint that receives "
                f"card interactions; got {addon_action_url!r}"
            )
        self._addon_action_url = addon_action_url
        if asset_publisher is not None and not callable(
            getattr(asset_publisher, "publish", None)
        ):
            raise TypeError("asset_publisher must define an async publish() method")
        self._asset_publisher = asset_publisher
        self._client: ChatServiceAsyncClient | None = None
        self._resolved_credentials: Credentials | None = None
        self._resolved_set = False
        self._resolved_user_credentials: Credentials | None = None
        self._resolved_user_set = False
        self._closed = False
        # single-flight tasks — concurrent first calls share ONE
        # credential resolution and ONE client construction (a shared
        # Task, not a lock held across provider code).
        self._credential_task: asyncio.Task[Credentials | None] | None = None
        self._user_credential_task: asyncio.Task[Credentials | None] | None = None
        self._init_task: asyncio.Task[ChatServiceAsyncClient] | None = None
        # The USER identity has its own cached client: attachment messages
        # must be created with the SAME USER credentials that uploaded
        # them (an APP-authenticated create cannot consume
        # a USER-uploaded attachment — Google rejects the handoff).
        self._user_client: ChatServiceAsyncClient | None = None
        self._user_init_task: asyncio.Task[ChatServiceAsyncClient] | None = None
        # Explicit identity facades (ADR-012). Roots are cached: the
        # facade must stay stable across accesses and cost no I/O.
        self._app_root = IdentityNamespace(self, AuthMode.APP)
        self._user_root = IdentityNamespace(self, AuthMode.USER, allow_setup=True)
        self._raw_namespace = RawClients(self)
        self._executor: OperationExecutor[object] = OperationExecutor(self)

    @property
    def app(self) -> IdentityNamespace:
        """Resource clients bound to the APP identity."""
        return self._app_root

    @property
    def user(self) -> IdentityNamespace:
        """Resource clients bound to the USER identity."""
        return self._user_root

    @property
    def raw(self) -> RawClients:
        """Async raw SDK access split by identity."""
        return self._raw_namespace

    async def warmup(self, *, app: bool = True, user: bool = False) -> None:
        """Resolve credentials and build clients before the first event.

        May resolve credentials and prepare clients/transports; never
        performs business API calls. Useful to move the slow first
        outbound request (credential resolution, IAM, gRPC channel)
        into startup.
        """
        if app:
            await self._get_client_async()
        if user:
            await self._get_user_client_async()

    def _classify(self, credentials: Credentials | None) -> AuthMode | None:
        if credentials is None:
            return None
        if getattr(credentials, "_subject", None):
            # Domain-wide delegation: a service account impersonating a
            # user (with_subject) acts as USER authentication.
            return AuthMode.USER
        if hasattr(credentials, "signer"):  # service account
            return AuthMode.APP
        if getattr(credentials, "refresh_token", None):
            return AuthMode.USER
        return None

    @property
    def auth_mode(self) -> AuthMode | None:
        """The outgoing auth mode: explicit, or classified from credentials.

        Synchronous classification; the async Bot methods use
        ``_auth_mode_async`` so blocking providers never run on the loop.
        """
        if self._auth_mode is not None:
            return self._auth_mode
        return self._classify(self._resolve_credentials())

    async def close(self) -> None:
        """Close the underlying SDK transport (idempotent, awaitable).

        Close is linearizable with initialization. Once close
        begins, NO client may be published; if construction already
        completed, its transport is closed exactly once before close
        returns. The async gRPC transport's closer is itself awaitable —
        it is AWAITED here (a plain sync call would leak the channel).
        Safe to call multiple times; after close the client must not be
        used. Also available as ``async with Bot(...)``.
        """
        if self._closed:
            return
        self._closed = True
        await self._settle_initialization()
        await self._close_transports()

    async def _settle_initialization(self) -> None:
        """Wait for credential resolution and client construction in flight.

        Each task either completes and publishes (then its transport is
        closed) or observes ``_closed`` and raises — both are
        deterministic. ``shield`` keeps OUR cancellation from breaking
        the shared task for other waiters.
        """
        for task in (
            self._credential_task,
            self._user_credential_task,
            self._init_task,
            self._user_init_task,
        ):
            if task is None:
                continue
            try:
                await asyncio.shield(task)
            except asyncio.CancelledError:
                raise
            except ChatAPIError:
                pass  # aborted by our own close — nothing to close

    async def _close_transports(self) -> None:
        """Close every initialized client's transport exactly once.

        The injected test transport may back both clients.
        """
        transports: dict[int, object] = {}
        for client in (self._client, self._user_client):
            if client is not None:
                transports.setdefault(id(client.transport), client.transport)
        for transport in transports.values():
            closer = getattr(transport, "close", None)
            if closer is None:
                continue
            result = closer()
            if inspect.isawaitable(result):
                await result

    async def __aenter__(self) -> Bot:
        return self

    async def __aexit__(
        self,
        exc_type: object,
        exc_value: object,
        traceback: object,
    ) -> None:
        await self.close()

    async def _auth_mode_async(self) -> AuthMode | None:
        """Off-loop variant of :attr:`auth_mode` for async call paths."""
        if self._auth_mode is not None:
            return self._auth_mode
        return self._classify(await self._resolve_credentials_async())

    def _get_client(self) -> ChatServiceAsyncClient:
        if self._closed:
            raise ChatAPIError("Bot is closed; create a new instance")
        client = self._client
        if client is not None:
            return client
        return self._build_client(self._resolve_credentials())

    async def _get_client_async(self) -> ChatServiceAsyncClient:
        """Single-flight async client initialization.

        Credential providers may perform blocking I/O (file reads, token
        refresh); the async path runs them in a worker thread. Concurrent
        first calls share ONE construction task. A failed construction is
        not cached — the next call retries (provider errors stay
        retryable, the pinned contract).
        """
        client = self._client
        if client is not None:
            return client
        task = self._init_task
        if task is None:
            task = asyncio.create_task(self._initialize_client())
            self._init_task = task
        try:
            # Shield: cancellation of a WAITER must not kill the shared
            # construction for everyone else.
            return await asyncio.shield(task)
        except asyncio.CancelledError:
            raise
        except Exception:
            if self._init_task is task:
                self._init_task = None
            raise

    async def _initialize_client(self) -> ChatServiceAsyncClient:
        """Resolve credentials and build the client; never publish after close."""
        if self._closed:
            raise ChatAPIError("Bot is closed; create a new instance")
        credentials = await self._resolve_credentials_async()
        if self._closed:
            # close() began while the provider ran off-loop: the client
            # must NOT be published after terminal close.
            raise ChatAPIError("Bot is closed; create a new instance")
        return self._build_client(credentials)

    def _build_client(self, credentials: Credentials | None) -> ChatServiceAsyncClient:
        if self._transport is not None:
            # SDK rule: a transport instance carries its own credentials;
            # passing credentials alongside raises ValueError.
            self._client = ChatServiceAsyncClient(transport=self._transport)
            return self._client
        if credentials is None:
            raise ChatAPIError(
                "Bot has no credentials; pass google.auth credentials "
                "or a credentials_provider to Bot(...)"
            )
        self._client = ChatServiceAsyncClient(
            credentials=credentials,
            transport=_GRPC_ASYNCIO,
        )
        return self._client

    def _build_user_client(self, credentials: Credentials) -> ChatServiceAsyncClient:
        """Build the cached USER Chat client.

        Mirrors the APP client construction: an injected transport (used
        by the testing toolkit) carries no identity, so the same fake
        transport may back both clients in tests. In production the USER
        client gets its own real gRPC-asyncio transport.
        """
        if self._transport is not None:
            self._user_client = ChatServiceAsyncClient(transport=self._transport)
            return self._user_client
        self._user_client = ChatServiceAsyncClient(
            credentials=credentials,
            transport=_GRPC_ASYNCIO,
        )
        return self._user_client

    async def _get_user_client_async(self) -> ChatServiceAsyncClient:
        """Single-flight async USER client initialization.

        Same contract as the APP path: concurrent first attachment sends
        share ONE construction task, a waiter's cancellation never kills
        the shared construction, and a failed construction is not cached
        (provider errors stay retryable).
        """
        client = self._user_client
        if client is not None:
            return client
        task = self._user_init_task
        if task is None:
            task = asyncio.create_task(self._initialize_user_client())
            self._user_init_task = task
        try:
            return await asyncio.shield(task)
        except asyncio.CancelledError:
            raise
        except Exception:
            if self._user_init_task is task:
                self._user_init_task = None
            raise

    async def _initialize_user_client(self) -> ChatServiceAsyncClient:
        """Resolve USER credentials and build the client; never publish after close."""
        if self._closed:
            raise ChatAPIError("Bot is closed; create a new instance")
        credentials = await self._resolve_user_credentials_async()
        if credentials is None:
            raise CapabilityNotSupported(
                "Sending message attachments requires USER authentication for "
                "both media.upload and messages.create. Configure "
                "user_credentials_provider=... — UserCredentialsProvider, or "
                "DelegatedUserCredentialsProvider for domain-wide delegation."
            )
        if self._closed:
            # close() began while the provider ran off-loop: the client
            # must NOT be published after terminal close.
            raise ChatAPIError("Bot is closed; create a new instance")
        return self._build_user_client(credentials)

    def _resolve_credentials(self) -> Credentials | None:
        """Resolve credentials once (the provider is called a single time).

        A provider failure is NOT cached: the flag is set only on success,
        so the error re-raises on every attempt instead of silently
        degrading to None (which would disable the capability guards).
        """
        if not self._resolved_set:
            if self._closed:
                raise ChatAPIError("Bot is closed; create a new instance")
            if self._credentials_provider is not None:
                self._resolved_credentials = self._credentials_provider()
            else:
                self._resolved_credentials = self._credentials
            self._resolved_set = True
        return self._resolved_credentials

    async def _resolve_credentials_async(self) -> Credentials | None:
        """Async-safe single-flight credential resolution.

        The provider is called exactly ONCE even under concurrent first
        sends (the previous lock-free path raced on the resolve flag). A
        provider failure is not cached: the shared task is dropped so the
        next attempt re-invokes the provider.
        """
        task = self._credential_task
        if task is None:
            task = asyncio.create_task(self._resolve_credentials_once())
            self._credential_task = task
        try:
            return await asyncio.shield(task)
        except asyncio.CancelledError:
            raise
        except Exception:
            if self._credential_task is task:
                self._credential_task = None
            raise

    async def _resolve_credentials_once(self) -> Credentials | None:
        if self._closed:
            raise ChatAPIError("Bot is closed; create a new instance")
        if self._resolved_set:
            return self._resolved_credentials
        if self._credentials_provider is not None:
            self._resolved_credentials = await asyncio.to_thread(
                self._credentials_provider
            )
        else:
            self._resolved_credentials = self._credentials
        self._resolved_set = True
        return self._resolved_credentials

    async def _resolve_user_credentials_async(self) -> Credentials | None:
        """Async-safe single-flight USER identity resolution."""
        task = self._user_credential_task
        if task is None:
            task = asyncio.create_task(self._resolve_user_credentials_once())
            self._user_credential_task = task
        try:
            return await asyncio.shield(task)
        except asyncio.CancelledError:
            raise
        except Exception:
            if self._user_credential_task is task:
                self._user_credential_task = None
            raise

    async def _resolve_user_credentials_once(self) -> Credentials | None:
        if self._closed:
            raise ChatAPIError("Bot is closed; create a new instance")
        if self._resolved_user_set:
            return self._resolved_user_credentials
        if self._user_credentials_provider is not None:
            self._resolved_user_credentials = await asyncio.to_thread(
                self._user_credentials_provider
            )
        else:
            single = await self._resolve_credentials_async()
            self._resolved_user_credentials = (
                single if self._classify(single) is AuthMode.USER else None
            )
        self._resolved_user_set = True
        return self._resolved_user_credentials

    @property
    def preview_capabilities(self) -> PreviewCapabilities:
        """The Developer Preview features this Bot is enrolled in."""
        return self._preview

    @property
    def _preview_enabled(self) -> bool:
        """Whether any Developer Preview feature is enrolled."""
        return bool(self._preview)

    async def _preflight_operation(
        self,
        operation: Operation,
        *,
        identity: AuthMode,
        variant: ExecutionVariant = ExecutionVariant.NORMAL,
        registry: OperationRegistry | None = None,
    ) -> None:
        """Registry preflight for an explicit identity (ADR-012).

        Resolves the identity's credentials, classifies the mode and
        known scopes, then delegates to the registry. A mismatch
        between requested and resolved identity fails, never silently
        switches.
        """
        credentials = (
            await self._resolve_user_credentials_async()
            if identity is AuthMode.USER
            else await self._resolve_credentials_async()
        )
        if credentials is None:
            # Fail closed for BOTH identities: a call with no credentials
            # is deterministically invalid and must never reach the
            # transport (with a custom transport the SDK client would
            # happily issue an unauthenticated request).
            if identity is AuthMode.USER:
                raise CapabilityNotSupported(
                    "USER identity is not configured on this Bot"
                )
            raise CapabilityNotSupported(
                "The APP identity has no credentials; pass google.auth "
                "credentials or a credentials_provider to Bot(...)"
            )
        mode = self._classify(credentials)
        if mode is None:
            # Unclassifiable credentials: local preflight cannot decide,
            # the attempt proceeds and the server remains the authority.
            return
        if mode is not identity:
            raise CapabilityNotSupported(
                f"Requested {identity.name} identity but resolved "
                f"credentials are {mode.name}"
            )
        (registry or REGISTRY).require(
            operation,
            identity=mode,
            scopes=_credential_scopes(mode, credentials),
            variant=variant,
        )


__all__ = ["Bot"]
