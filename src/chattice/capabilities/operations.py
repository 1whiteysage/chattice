"""Declarative outbound operation model.

An Operation names one Google Chat outbound surface. AuthPath captures
one identity-specific, any-of OAuth scope rule plus an optional
execution variant. Admin and import are execution variants of an
identity, not AuthMode values (ADR-012).
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from chattice.auth import AuthMode

__all__ = [
    "AuthPath",
    "ExecutionVariant",
    "Operation",
    "OperationSpec",
    "scopes",
]

GOOGLE_AUTH_SCOPE_PREFIX = "https://www.googleapis.com/auth/"


def scopes(*names: str) -> frozenset[str]:
    """Build fully qualified Google OAuth scopes from short names."""
    return frozenset(GOOGLE_AUTH_SCOPE_PREFIX + name for name in names)


class Operation(StrEnum):
    """A Google Chat outbound operation."""

    MESSAGES_CREATE = "messages.create"
    MESSAGES_GET = "messages.get"
    MESSAGES_LIST = "messages.list"
    MESSAGES_SEARCH = "messages.search"
    MESSAGES_UPDATE = "messages.update"
    MESSAGES_DELETE = "messages.delete"
    MESSAGES_REPLACE_CARDS = "messages.replace_cards"
    MESSAGE_PINS_CREATE = "message_pins.create"
    MESSAGE_PINS_LIST = "message_pins.list"
    MESSAGE_PINS_DELETE = "message_pins.delete"
    MEDIA_UPLOAD = "media.upload"
    MEDIA_DOWNLOAD = "media.download"
    ATTACHMENT_METADATA_GET = "spaces.messages.attachments.get"
    SPACES_GET = "spaces.get"
    SPACES_LIST = "spaces.list"
    SPACES_SEARCH = "spaces.search"
    SPACES_FIND_DIRECT_MESSAGE = "spaces.find_direct_message"
    SPACES_FIND_GROUP_CHATS = "spaces.find_group_chats"
    SPACES_SETUP = "spaces.setup"
    SPACES_CREATE = "spaces.create"
    SPACES_UPDATE = "spaces.update"
    SPACES_DELETE = "spaces.delete"
    MEMBERSHIPS_CREATE = "memberships.create"
    MEMBERSHIPS_GET = "memberships.get"
    MEMBERSHIPS_LIST = "memberships.list"
    MEMBERSHIPS_UPDATE = "memberships.update"
    MEMBERSHIPS_DELETE = "memberships.delete"
    REACTIONS_CREATE = "reactions.create"
    REACTIONS_LIST = "reactions.list"
    REACTIONS_DELETE = "reactions.delete"
    SPACE_READ_STATE_GET = "space_read_state.get"
    SPACE_READ_STATE_UPDATE = "space_read_state.update"
    THREAD_READ_STATE_GET = "thread_read_state.get"
    NOTIFICATION_SETTING_GET = "notification_setting.get"
    NOTIFICATION_SETTING_UPDATE = "notification_setting.update"
    AVAILABILITY_GET = "availability.get"
    AVAILABILITY_UPDATE = "availability.update"
    AVAILABILITY_MARK_ACTIVE = "availability.mark_active"
    AVAILABILITY_MARK_AWAY = "availability.mark_away"
    AVAILABILITY_MARK_DO_NOT_DISTURB = "availability.mark_do_not_disturb"
    SECTIONS_CREATE = "sections.create"
    SECTIONS_LIST = "sections.list"
    SECTIONS_UPDATE = "sections.update"
    SECTIONS_DELETE = "sections.delete"
    SECTIONS_POSITION = "sections.position"
    SECTION_ITEMS_LIST = "section_items.list"
    SECTION_ITEMS_MOVE = "section_items.move"
    CUSTOM_EMOJIS_CREATE = "custom_emojis.create"
    CUSTOM_EMOJIS_GET = "custom_emojis.get"
    CUSTOM_EMOJIS_LIST = "custom_emojis.list"
    CUSTOM_EMOJIS_DELETE = "custom_emojis.delete"


class ExecutionVariant(StrEnum):
    """Execution variant of an identity for an operation."""

    NORMAL = "normal"
    ADMIN = "admin"
    IMPORT = "import"


@dataclass(frozen=True, slots=True)
class AuthPath:
    """One identity-specific, any-of OAuth scope rule.

    identity: the credential identity class (APP or USER).
    any_scope: any one of these scopes makes the path admissible.
    variant: execution variant; ADMIN adds the request_flag, IMPORT
        selects import scopes.
    request_flag: optional wire flag sent with the request (e.g.
        "use_admin_access").
    """

    identity: AuthMode
    any_scope: frozenset[str]
    variant: ExecutionVariant = ExecutionVariant.NORMAL
    request_flag: str | None = None


@dataclass(frozen=True, slots=True)
class OperationSpec:
    """Declarative local-preflight description of one operation.

    google_method is the discovery-document method id used by the CI
    registry verifier. ``paginated`` marks SDK pager-backed methods;
    ``preview`` marks Developer Preview surface (explicit opt-in via
    ``Bot(enable_preview=True)``); ``retry_policy`` is a human-readable
    label — the executor never runs its own retry loop, it passes the
    per-call ``RequestConfig.retry`` through to GAPIC.
    """

    operation: Operation
    google_method: str
    auth_paths: tuple[AuthPath, ...]
    description: str = ""
    paginated: bool = False
    preview: bool = False
    retry_policy: str | None = None
