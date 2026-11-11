"""Predictable single-parent router hierarchy."""

from __future__ import annotations

import logging
from collections.abc import Iterator

from chattice.exceptions import RouterConfigurationError
from chattice.middleware import MiddlewareLike

from .middleware import MiddlewareManager
from .observer import EventObserver

logger = logging.getLogger("chattice.routing")


class Router:
    """A named collection of observers, middleware, and child routers."""

    def __init__(self, *, name: str | None = None) -> None:
        self.name = name or "router"
        if not self.name.strip():
            raise ValueError("Router name cannot be empty")
        self.message = EventObserver("message")
        self.action = EventObserver("action", action_shortcut=True)
        self.command = EventObserver("command")
        self.slash_command = EventObserver("slash_command")
        self.quick_command = EventObserver("quick_command")
        self.message_action = EventObserver("message_action")
        self.added_to_space = EventObserver("added_to_space")
        self.removed_from_space = EventObserver("removed_from_space")
        self.system_command = EventObserver("system_command")
        self.widget_updated = EventObserver("widget_updated")
        self.app_home = EventObserver("app_home")
        self.form_submit = EventObserver("form_submit")
        self.dialog_submit = EventObserver("dialog_submit")
        self.dialog_cancel = EventObserver("dialog_cancel")
        self.event = EventObserver("event")
        self.unknown_event = EventObserver("unknown_event")
        self.error = EventObserver("error")
        self.middleware = MiddlewareManager()
        self._parent: Router | None = None
        self._children: list[Router] = []
        self._is_dispatcher = False

    @property
    def parent(self) -> Router | None:
        """The owning parent, or ``None`` for a detached/root router."""
        return self._parent

    @property
    def children(self) -> tuple[Router, ...]:
        """Child routers in deterministic inclusion order."""
        return tuple(self._children)

    def include_router(self, router: Router) -> Router:
        """Attach one detached router as a child."""
        if not isinstance(router, Router):
            raise TypeError("include_router() requires a Router")
        if router is self:
            raise RouterConfigurationError("A router cannot include itself")
        if router._is_dispatcher:
            raise RouterConfigurationError("A Dispatcher cannot be attached as a child")
        if router._parent is not None:
            raise RouterConfigurationError(
                f"Router {router.name!r} is already attached to {router._parent.name!r}"
            )
        if router._contains(self):
            raise RouterConfigurationError(
                f"Including {router.name!r} in {self.name!r} would create a cycle"
            )
        router._parent = self
        if any(child.name == router.name for child in self._children):
            logger.warning("duplicate router name: %s", router.name)
        self._children.append(router)
        return router

    def _contains(self, candidate: Router) -> bool:
        if self is candidate:
            return True
        return any(child._contains(candidate) for child in self._children)

    def _walk(
        self, inherited: tuple[MiddlewareLike, ...] = ()
    ) -> Iterator[tuple[Router, tuple[MiddlewareLike, ...]]]:
        middleware = (*inherited, *tuple(self.middleware))
        yield self, middleware
        for child in tuple(self._children):
            yield from child._walk(middleware)

    def __repr__(self) -> str:
        return (
            f"Router(name={self.name!r}, children={len(self._children)}, "
            f"parent={self._parent.name if self._parent else None!r})"
        )


__all__ = ["Router"]
