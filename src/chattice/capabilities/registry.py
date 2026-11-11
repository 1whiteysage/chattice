"""Operation registry: the single source of outbound auth truth.

Preflight answers "the local configuration allows an attempt", never
"the call will succeed" — Google remains the final authority (403s from
membership, role, policy, admin approval, or resource state are still
possible). ``scopes=None`` means unknown and preserves the identity
baseline; the server decides.
"""

from __future__ import annotations

from collections.abc import Iterable, Iterator

from chattice.auth import AuthMode
from chattice.capabilities.operations import (
    AuthPath,
    ExecutionVariant,
    Operation,
    OperationSpec,
    scopes,
)

__all__ = ["REGISTRY", "SPECS", "OperationRegistry", "UnknownOperation"]


class UnknownOperation(KeyError):
    """A capability gate referenced an operation with no registry spec."""


class OperationRegistry:
    """Lookup and local preflight over OperationSpecs."""

    def __init__(self, specs: Iterable[OperationSpec]) -> None:
        self._specs: dict[Operation, OperationSpec] = {}
        for spec in specs:
            if spec.operation in self._specs:
                raise ValueError(f"Duplicate spec for {spec.operation}")
            self._specs[spec.operation] = spec

    def __contains__(self, operation: Operation) -> bool:
        return operation in self._specs

    def __iter__(self) -> Iterator[OperationSpec]:
        return iter(self._specs.values())

    def spec(self, operation: Operation) -> OperationSpec:
        try:
            return self._specs[operation]
        except KeyError:
            raise UnknownOperation(operation.value) from None

    def preflight(
        self,
        operation: Operation,
        *,
        identity: AuthMode | None,
        scopes: Iterable[str] | None = None,
        variant: ExecutionVariant = ExecutionVariant.NORMAL,
    ) -> bool:
        """Return whether the local configuration allows an attempt."""
        paths = [
            path
            for path in self.spec(operation).auth_paths
            if path.identity is identity and path.variant is variant
        ]
        if not paths:
            return False
        if scopes is None:
            return True
        known = frozenset(scopes)
        return any(path.any_scope & known for path in paths)

    def require(
        self,
        operation: Operation,
        *,
        identity: AuthMode | None,
        scopes: Iterable[str] | None = None,
        variant: ExecutionVariant = ExecutionVariant.NORMAL,
    ) -> None:
        """Raise CapabilityNotSupported when preflight fails."""
        if self.preflight(operation, identity=identity, scopes=scopes, variant=variant):
            return
        # Deferred import: matrix.py imports the registry, so the error
        # class resolves at call time to avoid a package cycle.
        from chattice.capabilities.matrix import CapabilityNotSupported

        spec = self.spec(operation)
        if variant is ExecutionVariant.ADMIN:
            admin_paths = [path for path in spec.auth_paths if path.variant is variant]
            if not admin_paths:
                raise CapabilityNotSupported(
                    f"{operation.name} has no administrator access variant."
                )
            wanted = sorted(
                scope.rsplit("/", 1)[-1]
                for path in admin_paths
                for scope in path.any_scope
            )
            raise CapabilityNotSupported(
                f"{operation.name} with administrator access requires the "
                "USER identity of a Google Workspace administrator and one "
                f"of the scopes: {', '.join(wanted)}."
            )
        raise CapabilityNotSupported(
            f"{operation.name} is not supported in this configuration. "
            f"{spec.description}".rstrip()
        )


def _describe(text: str) -> str:
    return text


# Reviewed scope facts per official Google Chat references. Semantic
# constraints (identity selection, admin approval, preview status) are
# human-reviewed; the CI verifier checks method existence and scopes
# against the discovery document.
SPECS: tuple[OperationSpec, ...] = (
    OperationSpec(
        operation=Operation.MESSAGES_CREATE,
        google_method="spaces.messages.create",
        auth_paths=(
            AuthPath(AuthMode.APP, scopes("chat.bot")),
            AuthPath(
                AuthMode.USER,
                scopes("chat.messages.create", "chat.messages", "chat.import"),
            ),
        ),
        description=_describe(
            "Creating messages requires app or user authentication and an "
            "admissible OAuth scope."
        ),
    ),
    OperationSpec(
        operation=Operation.MESSAGES_UPDATE,
        google_method="spaces.messages.update",
        auth_paths=(
            AuthPath(AuthMode.APP, scopes("chat.bot")),
            AuthPath(AuthMode.USER, scopes("chat.messages", "chat.import")),
        ),
        description=_describe(
            "Updating messages requires app or user authentication and an "
            "admissible OAuth scope."
        ),
    ),
    OperationSpec(
        operation=Operation.MESSAGES_GET,
        google_method="spaces.messages.get",
        auth_paths=(
            AuthPath(AuthMode.APP, scopes("chat.bot")),
            AuthPath(AuthMode.USER, scopes("chat.messages.readonly", "chat.messages")),
        ),
        description=_describe(
            "Getting messages requires app or user authentication and an "
            "admissible OAuth scope."
        ),
    ),
    OperationSpec(
        operation=Operation.MESSAGES_LIST,
        paginated=True,
        google_method="spaces.messages.list",
        auth_paths=(
            AuthPath(AuthMode.APP, scopes("chat.app.messages.readonly")),
            AuthPath(AuthMode.USER, scopes("chat.messages.readonly", "chat.messages")),
        ),
        description=_describe(
            "Listing messages requires app or user authentication and an "
            "admissible OAuth scope."
        ),
    ),
    OperationSpec(
        operation=Operation.MESSAGES_DELETE,
        google_method="spaces.messages.delete",
        auth_paths=(
            AuthPath(AuthMode.APP, scopes("chat.bot")),
            AuthPath(AuthMode.USER, scopes("chat.messages")),
        ),
        description=_describe(
            "Deleting messages requires app or user authentication and an "
            "admissible OAuth scope."
        ),
    ),
    OperationSpec(
        operation=Operation.MESSAGES_SEARCH,
        paginated=True,
        google_method="spaces.messages.search",
        auth_paths=(
            AuthPath(AuthMode.USER, scopes("chat.messages.readonly", "chat.messages")),
        ),
        description=_describe(
            "Searching messages requires user authentication; results are "
            "limited to messages the calling user can access."
        ),
    ),
    OperationSpec(
        operation=Operation.MESSAGES_REPLACE_CARDS,
        google_method="spaces.messages.replaceCards",
        auth_paths=(AuthPath(AuthMode.APP, scopes("chat.bot")),),
        description=_describe(
            "Replacing the cards of a message requires app authentication "
            "(chat.bot); the app must be a member of the space and own the "
            "cards it replaces."
        ),
    ),
    OperationSpec(
        operation=Operation.MESSAGE_PINS_CREATE,
        google_method="spaces.messagePins.create",
        auth_paths=(
            AuthPath(AuthMode.USER, scopes("chat.spaces.pins", "chat.spaces")),
        ),
        description=_describe("Pinning a message requires user authentication."),
    ),
    OperationSpec(
        operation=Operation.MESSAGE_PINS_LIST,
        paginated=True,
        google_method="spaces.messagePins.list",
        auth_paths=(
            AuthPath(
                AuthMode.USER,
                scopes(
                    "chat.spaces.pins.readonly",
                    "chat.spaces.pins",
                    "chat.spaces.readonly",
                    "chat.spaces",
                ),
            ),
        ),
        description=_describe("Listing message pins requires user authentication."),
    ),
    OperationSpec(
        operation=Operation.MESSAGE_PINS_DELETE,
        google_method="spaces.messagePins.delete",
        auth_paths=(
            AuthPath(AuthMode.USER, scopes("chat.spaces.pins", "chat.spaces")),
        ),
        description=_describe("Unpinning a message requires user authentication."),
    ),
    OperationSpec(
        operation=Operation.MEDIA_UPLOAD,
        google_method="media.upload",
        auth_paths=(
            AuthPath(
                AuthMode.USER,
                scopes("chat.messages.create", "chat.messages", "chat.import"),
            ),
        ),
        description="media.upload requires user authentication.",
    ),
    OperationSpec(
        operation=Operation.MEDIA_DOWNLOAD,
        google_method="media.download",
        auth_paths=(
            AuthPath(AuthMode.USER, scopes("chat.messages.readonly", "chat.messages")),
            AuthPath(AuthMode.APP, scopes("chat.bot")),
        ),
        description="media.download allows user scopes or app auth.",
    ),
    OperationSpec(
        operation=Operation.ATTACHMENT_METADATA_GET,
        google_method="spaces.messages.attachments.get",
        auth_paths=(AuthPath(AuthMode.APP, scopes("chat.bot")),),
        description="Attachment metadata requires app authentication.",
    ),
    OperationSpec(
        operation=Operation.SPACES_GET,
        google_method="spaces.get",
        auth_paths=(
            AuthPath(AuthMode.APP, scopes("chat.bot", "chat.spaces")),
            AuthPath(AuthMode.USER, scopes("chat.spaces", "chat.spaces.readonly")),
            AuthPath(
                AuthMode.USER,
                scopes("chat.admin.spaces", "chat.admin.spaces.readonly"),
                variant=ExecutionVariant.ADMIN,
                request_flag="use_admin_access",
            ),
        ),
        description=_describe(
            "Getting a space requires app or user authentication and an "
            "admissible OAuth scope."
        ),
    ),
    OperationSpec(
        operation=Operation.SPACES_LIST,
        paginated=True,
        google_method="spaces.list",
        auth_paths=(AuthPath(AuthMode.APP, scopes("chat.bot")),),
        description=_describe(
            "Listing spaces as the Chat app requires app authentication with chat.bot."
        ),
    ),
    OperationSpec(
        operation=Operation.SPACES_FIND_DIRECT_MESSAGE,
        google_method="spaces.findDirectMessage",
        auth_paths=(
            AuthPath(AuthMode.USER, scopes("chat.spaces", "chat.spaces.readonly")),
            AuthPath(AuthMode.APP, scopes("chat.bot")),
        ),
        description=_describe(
            "Finding a direct message requires user authentication or app "
            "auth with chat.bot."
        ),
    ),
    OperationSpec(
        operation=Operation.SPACES_SETUP,
        google_method="spaces.setup",
        auth_paths=(
            AuthPath(AuthMode.USER, scopes("chat.spaces", "chat.spaces.create")),
        ),
        description=_describe(
            "Setting up a space requires user authentication with chat.spaces."
        ),
    ),
    OperationSpec(
        operation=Operation.SPACES_SEARCH,
        paginated=True,
        google_method="spaces.search",
        auth_paths=(
            AuthPath(AuthMode.USER, scopes("chat.spaces.readonly", "chat.spaces")),
            AuthPath(
                AuthMode.USER,
                scopes("chat.admin.spaces", "chat.admin.spaces.readonly"),
                variant=ExecutionVariant.ADMIN,
                request_flag="use_admin_access",
            ),
        ),
        description=_describe(
            "Searching spaces requires user authentication; results are "
            "limited to spaces the calling user has joined unless the "
            "search runs with administrator access."
        ),
    ),
    OperationSpec(
        operation=Operation.SPACES_FIND_GROUP_CHATS,
        paginated=True,
        google_method="spaces.findGroupChats",
        auth_paths=(
            AuthPath(
                AuthMode.USER,
                scopes("chat.memberships.readonly", "chat.memberships"),
            ),
        ),
        description=_describe("Finding group chats requires user authentication."),
    ),
    OperationSpec(
        operation=Operation.SPACES_CREATE,
        google_method="spaces.create",
        auth_paths=(
            AuthPath(AuthMode.APP, scopes("chat.app.spaces.create", "chat.app.spaces")),
            AuthPath(
                AuthMode.USER,
                scopes("chat.spaces.create", "chat.spaces", "chat.import"),
            ),
        ),
        description=_describe(
            "Creating spaces requires user authentication, or app "
            "authentication with Workspace administrator approval."
        ),
    ),
    OperationSpec(
        operation=Operation.SPACES_UPDATE,
        google_method="spaces.patch",
        auth_paths=(
            AuthPath(AuthMode.APP, scopes("chat.app.spaces")),
            AuthPath(AuthMode.USER, scopes("chat.spaces", "chat.import")),
            AuthPath(
                AuthMode.USER,
                scopes("chat.admin.spaces"),
                variant=ExecutionVariant.ADMIN,
                request_flag="use_admin_access",
            ),
        ),
        description=_describe(
            "Updating spaces requires user authentication, or app "
            "authentication with Workspace administrator approval."
        ),
    ),
    OperationSpec(
        operation=Operation.SPACES_DELETE,
        google_method="spaces.delete",
        auth_paths=(
            AuthPath(AuthMode.APP, scopes("chat.app.delete")),
            AuthPath(AuthMode.USER, scopes("chat.delete", "chat.import")),
            AuthPath(
                AuthMode.USER,
                scopes("chat.admin.delete"),
                variant=ExecutionVariant.ADMIN,
                request_flag="use_admin_access",
            ),
        ),
        description=_describe(
            "Deleting spaces requires user authentication, or app "
            "authentication with Workspace administrator approval (only "
            "spaces the app created)."
        ),
    ),
    OperationSpec(
        operation=Operation.MEMBERSHIPS_CREATE,
        google_method="spaces.members.create",
        auth_paths=(
            AuthPath(AuthMode.APP, scopes("chat.app.memberships")),
            AuthPath(
                AuthMode.USER,
                scopes("chat.admin.memberships"),
                variant=ExecutionVariant.ADMIN,
                request_flag="use_admin_access",
            ),
        ),
        description=_describe(
            "Creating memberships requires app authentication with "
            "chat.app.memberships and Workspace administrator approval."
        ),
    ),
    OperationSpec(
        operation=Operation.MEMBERSHIPS_GET,
        google_method="spaces.members.get",
        auth_paths=(
            AuthPath(AuthMode.APP, scopes("chat.bot", "chat.app.memberships")),
            AuthPath(
                AuthMode.USER,
                scopes("chat.admin.memberships", "chat.admin.memberships.readonly"),
                variant=ExecutionVariant.ADMIN,
                request_flag="use_admin_access",
            ),
        ),
        description=_describe(
            "Getting memberships requires app authentication with chat.bot "
            "or chat.app.memberships."
        ),
    ),
    OperationSpec(
        operation=Operation.MEMBERSHIPS_LIST,
        paginated=True,
        google_method="spaces.members.list",
        auth_paths=(
            AuthPath(AuthMode.APP, scopes("chat.bot", "chat.app.memberships")),
            AuthPath(
                AuthMode.USER,
                scopes("chat.admin.memberships", "chat.admin.memberships.readonly"),
                variant=ExecutionVariant.ADMIN,
                request_flag="use_admin_access",
            ),
        ),
        description=_describe(
            "Listing memberships requires app authentication with chat.bot "
            "or chat.app.memberships."
        ),
    ),
    OperationSpec(
        operation=Operation.MEMBERSHIPS_UPDATE,
        google_method="spaces.members.patch",
        auth_paths=(
            AuthPath(AuthMode.APP, scopes("chat.app.memberships")),
            AuthPath(AuthMode.USER, scopes("chat.memberships", "chat.import")),
            AuthPath(
                AuthMode.USER,
                scopes("chat.admin.memberships"),
                variant=ExecutionVariant.ADMIN,
                request_flag="use_admin_access",
            ),
        ),
        description=_describe(
            "Updating memberships requires user authentication, or app "
            "authentication with chat.app.memberships and Workspace "
            "administrator approval (only spaces the app created)."
        ),
    ),
    OperationSpec(
        operation=Operation.MEMBERSHIPS_DELETE,
        google_method="spaces.members.delete",
        auth_paths=(
            AuthPath(AuthMode.APP, scopes("chat.app.memberships")),
            AuthPath(
                AuthMode.USER,
                scopes("chat.admin.memberships"),
                variant=ExecutionVariant.ADMIN,
                request_flag="use_admin_access",
            ),
        ),
        description=_describe(
            "Deleting memberships requires app authentication with "
            "chat.app.memberships and Workspace administrator approval."
        ),
    ),
    OperationSpec(
        operation=Operation.REACTIONS_CREATE,
        google_method="spaces.messages.reactions.create",
        auth_paths=(
            AuthPath(
                AuthMode.USER,
                scopes("chat.messages.reactions", "chat.messages.reactions.create"),
            ),
        ),
        description=_describe("Creating reactions requires user authentication."),
    ),
    OperationSpec(
        operation=Operation.REACTIONS_LIST,
        paginated=True,
        google_method="spaces.messages.reactions.list",
        auth_paths=(
            AuthPath(
                AuthMode.USER,
                scopes("chat.messages.reactions", "chat.messages.reactions.readonly"),
            ),
        ),
        description=_describe("Listing reactions requires user authentication."),
    ),
    OperationSpec(
        operation=Operation.REACTIONS_DELETE,
        google_method="spaces.messages.reactions.delete",
        auth_paths=(AuthPath(AuthMode.USER, scopes("chat.messages.reactions")),),
        description=_describe("Deleting reactions requires user authentication."),
    ),
    OperationSpec(
        operation=Operation.SPACE_READ_STATE_GET,
        google_method="users.spaces.getSpaceReadState",
        auth_paths=(
            AuthPath(
                AuthMode.USER,
                scopes("chat.users.readstate", "chat.users.readstate.readonly"),
            ),
        ),
        description=_describe(
            "Getting a space read state requires user authentication."
        ),
    ),
    OperationSpec(
        operation=Operation.SPACE_READ_STATE_UPDATE,
        google_method="users.spaces.updateSpaceReadState",
        auth_paths=(AuthPath(AuthMode.USER, scopes("chat.users.readstate")),),
        description=_describe(
            "Updating a space read state requires user authentication."
        ),
    ),
    OperationSpec(
        operation=Operation.THREAD_READ_STATE_GET,
        google_method="users.spaces.threads.getThreadReadState",
        auth_paths=(
            AuthPath(
                AuthMode.USER,
                scopes("chat.users.readstate", "chat.users.readstate.readonly"),
            ),
        ),
        description=_describe(
            "Getting a thread read state requires user authentication."
        ),
    ),
    OperationSpec(
        operation=Operation.NOTIFICATION_SETTING_GET,
        google_method="users.spaces.spaceNotificationSetting.get",
        auth_paths=(AuthPath(AuthMode.USER, scopes("chat.users.spacesettings")),),
        description=_describe(
            "Getting space notification settings requires user authentication."
        ),
    ),
    OperationSpec(
        operation=Operation.NOTIFICATION_SETTING_UPDATE,
        google_method="users.spaces.spaceNotificationSetting.patch",
        auth_paths=(AuthPath(AuthMode.USER, scopes("chat.users.spacesettings")),),
        description=_describe(
            "Updating space notification settings requires user authentication."
        ),
    ),
    OperationSpec(
        operation=Operation.AVAILABILITY_GET,
        google_method="users.availability.get",
        auth_paths=(
            AuthPath(
                AuthMode.USER,
                scopes("chat.users.availability.readonly", "chat.users.availability"),
            ),
        ),
        description=_describe("Reading availability requires user authentication."),
    ),
    OperationSpec(
        operation=Operation.AVAILABILITY_UPDATE,
        google_method="users.availability.patch",
        auth_paths=(AuthPath(AuthMode.USER, scopes("chat.users.availability")),),
        description=_describe("Updating a custom status requires user authentication."),
    ),
    OperationSpec(
        operation=Operation.AVAILABILITY_MARK_ACTIVE,
        google_method="users.availability.markAsActive",
        auth_paths=(AuthPath(AuthMode.USER, scopes("chat.users.availability")),),
        description=_describe("Changing availability requires user authentication."),
    ),
    OperationSpec(
        operation=Operation.AVAILABILITY_MARK_AWAY,
        google_method="users.availability.markAsAway",
        auth_paths=(AuthPath(AuthMode.USER, scopes("chat.users.availability")),),
        description=_describe("Changing availability requires user authentication."),
    ),
    OperationSpec(
        operation=Operation.AVAILABILITY_MARK_DO_NOT_DISTURB,
        google_method="users.availability.markAsDoNotDisturb",
        auth_paths=(AuthPath(AuthMode.USER, scopes("chat.users.availability")),),
        description=_describe("Changing availability requires user authentication."),
    ),
    OperationSpec(
        operation=Operation.SECTIONS_CREATE,
        google_method="users.sections.create",
        auth_paths=(AuthPath(AuthMode.USER, scopes("chat.users.sections")),),
        description=_describe("Creating sections requires user authentication."),
    ),
    OperationSpec(
        operation=Operation.SECTIONS_LIST,
        paginated=True,
        google_method="users.sections.list",
        auth_paths=(
            AuthPath(
                AuthMode.USER,
                scopes("chat.users.sections.readonly", "chat.users.sections"),
            ),
        ),
        description=_describe("Listing sections requires user authentication."),
    ),
    OperationSpec(
        operation=Operation.SECTIONS_UPDATE,
        google_method="users.sections.patch",
        auth_paths=(AuthPath(AuthMode.USER, scopes("chat.users.sections")),),
        description=_describe("Updating sections requires user authentication."),
    ),
    OperationSpec(
        operation=Operation.SECTIONS_DELETE,
        google_method="users.sections.delete",
        auth_paths=(AuthPath(AuthMode.USER, scopes("chat.users.sections")),),
        description=_describe("Deleting sections requires user authentication."),
    ),
    OperationSpec(
        operation=Operation.SECTIONS_POSITION,
        google_method="users.sections.position",
        auth_paths=(AuthPath(AuthMode.USER, scopes("chat.users.sections")),),
        description=_describe("Positioning sections requires user authentication."),
    ),
    OperationSpec(
        operation=Operation.SECTION_ITEMS_LIST,
        paginated=True,
        google_method="users.sections.items.list",
        auth_paths=(
            AuthPath(
                AuthMode.USER,
                scopes("chat.users.sections.readonly", "chat.users.sections"),
            ),
        ),
        description=_describe("Listing section items requires user authentication."),
    ),
    OperationSpec(
        operation=Operation.SECTION_ITEMS_MOVE,
        google_method="users.sections.items.move",
        auth_paths=(AuthPath(AuthMode.USER, scopes("chat.users.sections")),),
        description=_describe("Moving section items requires user authentication."),
    ),
    OperationSpec(
        operation=Operation.CUSTOM_EMOJIS_CREATE,
        google_method="customEmojis.create",
        auth_paths=(AuthPath(AuthMode.USER, scopes("chat.customemojis")),),
        description=_describe("Creating custom emojis requires user authentication."),
    ),
    OperationSpec(
        operation=Operation.CUSTOM_EMOJIS_GET,
        google_method="customEmojis.get",
        auth_paths=(
            AuthPath(
                AuthMode.USER, scopes("chat.customemojis.readonly", "chat.customemojis")
            ),
        ),
        description=_describe("Reading custom emojis requires user authentication."),
    ),
    OperationSpec(
        operation=Operation.CUSTOM_EMOJIS_LIST,
        paginated=True,
        google_method="customEmojis.list",
        auth_paths=(
            AuthPath(
                AuthMode.USER, scopes("chat.customemojis.readonly", "chat.customemojis")
            ),
        ),
        description=_describe("Listing custom emojis requires user authentication."),
    ),
    OperationSpec(
        operation=Operation.CUSTOM_EMOJIS_DELETE,
        google_method="customEmojis.delete",
        auth_paths=(AuthPath(AuthMode.USER, scopes("chat.customemojis")),),
        description=_describe("Deleting custom emojis requires user authentication."),
    ),
)

REGISTRY = OperationRegistry(SPECS)
