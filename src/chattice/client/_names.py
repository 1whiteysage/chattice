"""Canonicalization of Google Chat resource names (internal).

Shared by the Bot surface and the resource clients; kept in a leaf
module so neither import direction creates a package cycle.
"""

from __future__ import annotations

import re

from chattice.events import SpaceRef, ThreadRef, UserRef

from .errors import ChatAPIError


def _canonical_space(space: SpaceRef | str) -> str:
    """Validate and canonicalize a space target.

    One resource-name policy: a bare space ID is wrapped into the
    canonical ``spaces/{id}`` form (as the identifier docs promise),
    an already-canonical name passes through, malformed values raise
    locally — no network lookups, no remote errors replacing local
    validation.
    """
    name = space if isinstance(space, str) else space.name
    if name is None:
        raise ChatAPIError("SpaceRef has no name; cannot target a space")
    parent = name.strip()
    if not parent:
        raise ChatAPIError("space must be a non-empty identifier")
    if "/" in parent:
        if not parent.startswith("spaces/") or parent.count("/") != 1:
            raise ChatAPIError(
                "space must be a bare space ID or a canonical "
                "'spaces/{id}' resource name; got {parent!r}"
            )
        return parent
    return f"spaces/{parent}"


def _canonical_user(user: UserRef | str, *, parameter: str = "private_to") -> str:
    """Validate and canonicalize a user target.

    An empty string or a nameless ``UserRef`` must FAIL CLOSED — it
    could otherwise produce a public message. A bare user ID is wrapped into
    the canonical ``users/{id}`` resource form; already-canonical names
    pass through; malformed values (whitespace, misplaced slashes) raise
    before any transport work.
    """
    name = user if isinstance(user, str) else user.name
    if name is None:
        raise ChatAPIError(f"{parameter} UserRef has no name; cannot target a user")
    viewer = name.strip()
    if not viewer:
        raise ChatAPIError(f"{parameter} must be a non-empty user identifier")
    if "/" in viewer:
        if not viewer.startswith("users/") or viewer.count("/") != 1:
            raise ChatAPIError(
                f"{parameter} must be a bare user ID or a canonical "
                f"'users/{{id}}' resource name; got {viewer!r}"
            )
        return viewer
    return f"users/{viewer}"


def _canonical_message(name: str, *, parameter: str = "message") -> str:
    """Validate a canonical ``spaces/{space}/messages/{message}`` name."""
    value = name.strip() if isinstance(name, str) else ""
    parts = value.split("/")
    if (
        len(parts) != 4
        or parts[0] != "spaces"
        or parts[2] != "messages"
        or not parts[1]
        or not parts[3]
    ):
        raise ChatAPIError(
            f"{parameter} must be a canonical "
            f"'spaces/{{space}}/messages/{{message}}' resource name; got {name!r}"
        )
    return value


def _canonical_message_pin(name: str) -> str:
    """Canonicalize a message pin target.

    Accepts the pin name (``spaces/{space}/messagePins/{pin}``) or the
    pinned message name (``spaces/{space}/messages/{message}``): Google
    documents that the pin's resource ID equals the message's resource
    ID, so the mapping is deterministic and needs no lookup.
    """
    value = name.strip() if isinstance(name, str) else ""
    parts = value.split("/")
    if (
        len(parts) == 4
        and parts[0] == "spaces"
        and parts[2] in ("messagePins", "messages")
        and parts[1]
        and parts[3]
    ):
        return f"spaces/{parts[1]}/messagePins/{parts[3]}"
    raise ChatAPIError(
        "message pin must be a canonical "
        "'spaces/{space}/messagePins/{pin}' or "
        f"'spaces/{{space}}/messages/{{message}}' resource name; got {name!r}"
    )


_USER_SPACE_STATE = re.compile(r"users/[^/]+/spaces/[^/]+/(?P<leaf>[A-Za-z]+)")
_USER_THREAD_STATE = re.compile(
    r"users/[^/]+/spaces/[^/]+/threads/[^/]+/threadReadState"
)
_THREAD = re.compile(r"spaces/[^/]+/threads/[^/]+")


def _user_space_state(space: SpaceRef | str, leaf: str) -> str:
    """Name of a per-user space resource of the calling user.

    ``leaf`` is Google's singleton id (``spaceReadState`` or
    ``spaceNotificationSetting``). A space (``spaces/{id}``, a bare id,
    or a ``SpaceRef``) becomes ``users/me/spaces/{id}/{leaf}``; a full
    resource name of that kind passes through.
    """
    if isinstance(space, str):
        match = _USER_SPACE_STATE.fullmatch(space.strip())
        if match is not None and match.group("leaf") == leaf:
            return space.strip()
        if space.strip().startswith("users/"):
            raise ChatAPIError(
                f"expected a space or a 'users/{{user}}/spaces/{{space}}/{leaf}' "
                f"resource name; got {space!r}"
            )
    return f"users/me/{_canonical_space(space)}/{leaf}"


def _user_thread_read_state(thread: ThreadRef | str) -> str:
    """``users/me/spaces/{space}/threads/{thread}/threadReadState``.

    Accepts a thread (``spaces/{space}/threads/{thread}`` or a
    ``ThreadRef``) or the full read-state resource name.
    """
    name = thread if isinstance(thread, str) else thread.name
    value = (name or "").strip()
    if _USER_THREAD_STATE.fullmatch(value) is not None:
        return value
    if _THREAD.fullmatch(value) is None:
        raise ChatAPIError(
            "thread must be a canonical 'spaces/{space}/threads/{thread}' "
            f"name or its threadReadState resource name; got {name!r}"
        )
    return f"users/me/{value}/threadReadState"
