# ruff: noqa: ASYNC109 — timeout kwarg mirrors the gapic client call convention
"""Membership resource client: explicit-identity membership operations."""

from __future__ import annotations

from google.apps.chat_v1 import ChatServiceAsyncClient
from google.apps.chat_v1.types.membership import (
    CreateMembershipRequest,
    DeleteMembershipRequest,
    GetMembershipRequest,
    ListMembershipsRequest,
    Membership,
    UpdateMembershipRequest,
)
from google.apps.chat_v1.types.user import User as ProtoUser
from google.protobuf import field_mask_pb2  # type: ignore[import-untyped]

from chattice.capabilities.operations import Operation
from chattice.client._names import _canonical_space, _canonical_user
from chattice.client.config import RequestConfig
from chattice.client.errors import ChatAPIError
from chattice.client.paging import Pager
from chattice.client.resources.base import ResourceClient, _effective_config
from chattice.events import SpaceRef, UserRef

__all__ = ["Memberships"]


def _membership_name(name: str) -> str:
    """Validate a membership resource name before any transport work."""
    value = name.strip()
    parts = value.split("/members/", 1)
    if (
        not value.startswith("spaces/")
        or len(parts) != 2
        or not parts[0].removeprefix("spaces/")
        or not parts[1]
    ):
        raise ChatAPIError(
            "membership name must be a canonical "
            "'spaces/{space}/members/{member}' resource name"
        )
    return value


def _canonical_group(group: str) -> str:
    """Validate and canonicalize a Google Group target."""
    value = group.strip()
    if not value:
        raise ChatAPIError("group must be a non-empty group identifier")
    if "/" not in value:
        return f"groups/{value}"
    if not value.startswith("groups/") or value.count("/") != 1:
        raise ChatAPIError(
            "group must be a bare group ID or a canonical 'groups/{id}' name"
        )
    return value


class Memberships(ResourceClient):
    """Curated membership surface bound to one identity (ADR-012)."""

    async def create(
        self,
        parent: SpaceRef | str,
        *,
        user: UserRef | str | None = None,
        group: str | None = None,
        role: str | None = None,
        user_type: int | None = None,
        admin_access: bool = False,
        timeout: float | None = None,
        config: RequestConfig | None = None,
    ) -> Membership:
        """Create a membership in ``parent`` for a user or a Google Group.

        ``admin_access=True`` runs the call with the calling user's
        Google Workspace administrator privileges (USER identity and a
        ``chat.admin.*`` scope).
        """
        space = _canonical_space(parent)
        if user is not None:
            member = ProtoUser(
                name=_canonical_user(user, parameter="user"), type_=user_type
            )
        elif group is not None:
            member = ProtoUser(name=_canonical_group(group))
        else:
            raise ChatAPIError("membership create requires user= or group=")
        membership = Membership(member=member, role=role)
        effective = _effective_config(config, timeout)
        request = CreateMembershipRequest(
            parent=space, membership=membership, use_admin_access=admin_access
        )
        return await self._rpc(
            Operation.MEMBERSHIPS_CREATE, effective, admin_access=admin_access
        )(ChatServiceAsyncClient.create_membership, request=request)

    async def get(
        self,
        name: str,
        *,
        admin_access: bool = False,
        timeout: float | None = None,
        config: RequestConfig | None = None,
    ) -> Membership:
        """Get one membership by canonical name.

        ``admin_access=True`` runs the call with the calling user's
        Google Workspace administrator privileges (USER identity and a
        ``chat.admin.*`` scope).
        """
        request = GetMembershipRequest(
            name=_membership_name(name), use_admin_access=admin_access
        )
        effective = _effective_config(config, timeout)
        return await self._rpc(
            Operation.MEMBERSHIPS_GET, effective, admin_access=admin_access
        )(ChatServiceAsyncClient.get_membership, request=request)

    async def list(
        self,
        *,
        parent: SpaceRef | str,
        filter: str | None = None,
        page_size: int | None = None,
        admin_access: bool = False,
        timeout: float | None = None,
        config: RequestConfig | None = None,
    ) -> Pager[Membership]:
        """List memberships of one space, one page at a time.

        ``admin_access=True`` runs the call with the calling user's
        Google Workspace administrator privileges (USER identity and a
        ``chat.admin.*`` scope).
        """
        space = _canonical_space(parent)
        effective = _effective_config(config, timeout)
        request = ListMembershipsRequest(parent=space, use_admin_access=admin_access)
        if page_size is not None:
            request.page_size = page_size
        if filter is not None:
            request.filter = filter

        async def fetch() -> object:
            return await self._rpc(
                Operation.MEMBERSHIPS_LIST, effective, admin_access=admin_access
            )(ChatServiceAsyncClient.list_memberships, request=request)

        return Pager(fetch=fetch)

    async def update(
        self,
        name: str,
        *,
        role: Membership.MembershipRole,
        admin_access: bool = False,
        timeout: float | None = None,
        config: RequestConfig | None = None,
    ) -> Membership:
        """Change the ``role`` of one membership with THIS identity.

        ``role`` is the only field Google lets a caller update.

        ``admin_access=True`` runs the call with the calling user's
        Google Workspace administrator privileges (USER identity and a
        ``chat.admin.*`` scope).
        """
        target = _membership_name(name)
        if role == Membership.MembershipRole.MEMBERSHIP_ROLE_UNSPECIFIED:
            raise ChatAPIError("role must be a specific membership role")
        membership = Membership(name=target, role=role)
        mask = field_mask_pb2.FieldMask(paths=["role"])
        effective = _effective_config(config, timeout)
        request = UpdateMembershipRequest(
            membership=membership, update_mask=mask, use_admin_access=admin_access
        )
        return await self._rpc(
            Operation.MEMBERSHIPS_UPDATE, effective, admin_access=admin_access
        )(ChatServiceAsyncClient.update_membership, request=request)

    async def delete(
        self,
        name: str,
        *,
        admin_access: bool = False,
        timeout: float | None = None,
        config: RequestConfig | None = None,
    ) -> Membership:
        """Delete one membership by canonical name.

        ``admin_access=True`` runs the call with the calling user's
        Google Workspace administrator privileges (USER identity and a
        ``chat.admin.*`` scope).
        """
        request = DeleteMembershipRequest(
            name=_membership_name(name), use_admin_access=admin_access
        )
        effective = _effective_config(config, timeout)
        return await self._rpc(
            Operation.MEMBERSHIPS_DELETE, effective, admin_access=admin_access
        )(ChatServiceAsyncClient.delete_membership, request=request)
