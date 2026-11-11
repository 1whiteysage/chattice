# ruff: noqa: ASYNC109 — timeout kwarg mirrors the gapic client call convention
"""Space resource client: explicit-identity space operations (ADR-012)."""

from __future__ import annotations

from collections.abc import Sequence
from typing import TYPE_CHECKING

from google.apps.chat_v1 import ChatServiceAsyncClient
from google.apps.chat_v1.types import Space
from google.apps.chat_v1.types.membership import Membership
from google.apps.chat_v1.types.space import (
    CreateSpaceRequest,
    DeleteSpaceRequest,
    FindGroupChatsRequest,
    GetSpaceRequest,
    ListSpacesRequest,
    SearchSpacesRequest,
    UpdateSpaceRequest,
)
from google.apps.chat_v1.types.user import User as ProtoUser
from google.protobuf import field_mask_pb2  # type: ignore[import-untyped]

from chattice.auth import AuthMode
from chattice.capabilities.operations import Operation
from chattice.client._names import _canonical_space, _canonical_user
from chattice.client.config import RequestConfig
from chattice.client.errors import ChatAPIError, ChatNotFoundError
from chattice.client.paging import Pager
from chattice.client.resources.base import ResourceClient, _effective_config
from chattice.events import SpaceRef, UserRef

if TYPE_CHECKING:
    from chattice.client.bot import Bot

__all__ = ["Spaces"]


class Spaces(ResourceClient):
    """Curated space surface bound to one identity (ADR-012).

    No implicit identity selection: the identity is chosen by which Bot
    namespace the caller used (``bot.app.spaces`` vs ``bot.user.spaces``).
    """

    def __init__(self, bot: Bot, identity: AuthMode, *, allow_setup: bool) -> None:
        super().__init__(bot, identity)
        self._allow_setup = allow_setup

    async def get(
        self,
        name: str,
        *,
        admin_access: bool = False,
        timeout: float | None = None,
        config: RequestConfig | None = None,
    ) -> Space:
        """Get one space by canonical ``spaces/{id}`` name.

        ``admin_access=True`` runs the call with the calling user's
        Google Workspace administrator privileges (USER identity and a
        ``chat.admin.*`` scope).
        """
        effective = _effective_config(config, timeout)
        request = GetSpaceRequest(name=name, use_admin_access=admin_access)
        return await self._rpc(
            Operation.SPACES_GET, effective, admin_access=admin_access
        )(ChatServiceAsyncClient.get_space, request=request)

    async def list(
        self,
        *,
        filter: str | None = None,
        page_size: int | None = None,
        timeout: float | None = None,
        config: RequestConfig | None = None,
    ) -> Pager[Space]:
        """List spaces the identity can see, one page at a time."""
        effective = _effective_config(config, timeout)
        request = self._list_request(filter, page_size)

        async def fetch() -> object:
            return await self._rpc(Operation.SPACES_LIST, effective)(
                ChatServiceAsyncClient.list_spaces, request=request
            )

        return Pager(fetch=fetch)

    @staticmethod
    def _list_request(filter: str | None, page_size: int | None) -> ListSpacesRequest:
        request = ListSpacesRequest()
        if page_size is not None:
            request.page_size = page_size
        if filter is not None:
            request.filter = filter
        return request

    async def find_direct_message(
        self,
        user: str,
        *,
        timeout: float | None = None,
        config: RequestConfig | None = None,
    ) -> Space:
        """Find the 1:1 direct-message space with ``user``.

        ``user`` is a bare user ID, an email, or a canonical
        ``users/{id}`` resource name. Returns the official Google
        ``Space``. Errors are surfaced through the curated ``Chat*Error``
        family — ``ChatPermissionDeniedError`` / ``ChatInvalidArgumentError``
        / ``ChatNotFoundError`` are never hidden.
        """
        name = _canonical_user(user, parameter="user")
        effective = _effective_config(config, timeout)
        return await self._rpc(Operation.SPACES_FIND_DIRECT_MESSAGE, effective)(
            ChatServiceAsyncClient.find_direct_message, request={"name": name}
        )

    async def get_or_setup_direct_message(
        self,
        user: str,
        *,
        timeout: float | None = None,
        config: RequestConfig | None = None,
    ) -> Space:
        """Find the DM space, or create it via ``setUpSpace`` on 404.

        USER identity only: creating a DM on behalf of the app would
        silently change who is talking to whom. ``PermissionDenied`` /
        ``InvalidArgument`` are surfaced, never hidden.
        """
        if not self._allow_setup:
            raise ChatAPIError(
                "get_or_setup_direct_message requires the USER identity; "
                "use bot.user.spaces.get_or_setup_direct_message(...)"
            )
        name = _canonical_user(user, parameter="user")
        try:
            # find_direct_message preflights SPACES_FIND_DIRECT_MESSAGE.
            return await self.find_direct_message(user, timeout=timeout, config=config)
        except ChatNotFoundError:
            pass
        effective = _effective_config(config, timeout)
        space = Space(space_type=Space.SpaceType.DIRECT_MESSAGE)
        membership = Membership(member=ProtoUser(name=name, type_=ProtoUser.Type.HUMAN))
        return await self._rpc(Operation.SPACES_SETUP, effective)(
            ChatServiceAsyncClient.set_up_space,
            request={"space": space, "memberships": [membership]},
        )

    async def search(
        self,
        query: str,
        *,
        order_by: str | None = None,
        page_size: int | None = None,
        admin_access: bool = False,
        timeout: float | None = None,
        config: RequestConfig | None = None,
    ) -> Pager[Space]:
        """Search the spaces the calling user has joined (USER-only).

        ``query`` is Google's space search query. ``admin_access=True``
        searches the whole organization with the calling user's Google
        Workspace administrator privileges (a ``chat.admin.spaces*``
        scope); Google then expects the query to name the customer,
        for example ``customer = "customers/my_customer" AND
        space_type = "SPACE"``.
        """
        text = query.strip() if isinstance(query, str) else ""
        if not text:
            raise ChatAPIError("search query must be a non-empty string")
        effective = _effective_config(config, timeout)
        request = SearchSpacesRequest(query=text, use_admin_access=admin_access)
        if order_by is not None:
            request.order_by = order_by
        if page_size is not None:
            request.page_size = page_size

        async def fetch() -> object:
            return await self._rpc(
                Operation.SPACES_SEARCH, effective, admin_access=admin_access
            )(ChatServiceAsyncClient.search_spaces, request=request)

        return Pager(fetch=fetch)

    async def find_group_chats(
        self,
        users: Sequence[UserRef | str],
        *,
        page_size: int | None = None,
        timeout: float | None = None,
        config: RequestConfig | None = None,
    ) -> Pager[Space]:
        """Find group chats of the calling user and exactly ``users`` (USER-only).

        ``users`` are the OTHER human members; Chat apps cannot be
        listed. Google returns resource names only by default.
        """
        names = [_canonical_user(user, parameter="users") for user in users]
        if not names:
            raise ChatAPIError("find_group_chats requires at least one user")
        effective = _effective_config(config, timeout)
        request = FindGroupChatsRequest(users=names)
        if page_size is not None:
            request.page_size = page_size

        async def fetch() -> object:
            return await self._rpc(Operation.SPACES_FIND_GROUP_CHATS, effective)(
                ChatServiceAsyncClient.find_group_chats, request=request
            )

        return Pager(fetch=fetch)

    async def create(
        self,
        space: Space,
        *,
        request_id: str | None = None,
        timeout: float | None = None,
        config: RequestConfig | None = None,
    ) -> Space:
        """Create a space from the official ``Space`` with THIS identity.

        The caller becomes a member: the user with USER identity, the
        Chat app with APP identity. APP creation needs Workspace
        administrator approval and ``space.customer``.
        """
        if self._identity is AuthMode.APP and not space.customer:
            raise ChatAPIError(
                "space.customer is required when a space is created with app "
                "authentication (for example 'customers/my_customer')."
            )
        effective = _effective_config(config, timeout)
        request = CreateSpaceRequest(space=space)
        if request_id is not None:
            request.request_id = request_id
        return await self._rpc(Operation.SPACES_CREATE, effective)(
            ChatServiceAsyncClient.create_space, request=request
        )

    async def update(
        self,
        space: Space,
        *,
        update_mask: Sequence[str],
        admin_access: bool = False,
        timeout: float | None = None,
        config: RequestConfig | None = None,
    ) -> Space:
        """Update the ``update_mask`` fields of one space with THIS identity.

        ``space.name`` selects the space; ``update_mask`` lists Google's
        field paths (for example ``display_name`` or
        ``permission_settings.viewSpaceMembership``). Google rejects
        some combinations of paths; that authority stays with the server.

        ``admin_access=True`` runs the call with the calling user's
        Google Workspace administrator privileges (USER identity and a
        ``chat.admin.*`` scope).
        """
        target = _canonical_space(space.name)
        if target != space.name:
            raise ChatAPIError(
                "space.name must be a canonical 'spaces/{id}' resource name; "
                f"got {space.name!r}"
            )
        paths = [path.strip() for path in update_mask]
        if not paths or not all(paths):
            raise ChatAPIError("update_mask must list at least one field path")
        mask = field_mask_pb2.FieldMask(paths=paths)
        effective = _effective_config(config, timeout)
        request = UpdateSpaceRequest(
            space=space, update_mask=mask, use_admin_access=admin_access
        )
        return await self._rpc(
            Operation.SPACES_UPDATE, effective, admin_access=admin_access
        )(ChatServiceAsyncClient.update_space, request=request)

    async def delete(
        self,
        space: SpaceRef | str,
        *,
        admin_access: bool = False,
        timeout: float | None = None,
        config: RequestConfig | None = None,
    ) -> None:
        """Delete a named space and, irreversibly, everything in it.

        Google always cascades: messages and memberships of the space
        are deleted with it.

        ``admin_access=True`` runs the call with the calling user's
        Google Workspace administrator privileges (USER identity and a
        ``chat.admin.*`` scope).
        """
        request = DeleteSpaceRequest(
            name=_canonical_space(space), use_admin_access=admin_access
        )
        effective = _effective_config(config, timeout)
        await self._rpc(Operation.SPACES_DELETE, effective, admin_access=admin_access)(
            ChatServiceAsyncClient.delete_space, request=request
        )
