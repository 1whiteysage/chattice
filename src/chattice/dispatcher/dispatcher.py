"""Transport-neutral event dispatcher."""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Iterable, MutableMapping
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from google.auth.credentials import Credentials

    from chattice.auth import CredentialsProvider
    from chattice.client import Bot
    from chattice.idempotency import IdempotencyStorage

from chattice.capabilities import PreviewCapabilities, PreviewFeature
from chattice.events import (
    ActionEvent,
    AddedToSpaceEvent,
    AppHomeEvent,
    CommandEvent,
    CommandKind,
    DialogEventType,
    ErrorEvent,
    Event,
    FormSubmitEvent,
    MessageEvent,
    RemovedFromSpaceEvent,
    SystemCommandEvent,
    UnknownEvent,
    WidgetUpdatedEvent,
)
from chattice.events.references import _reset_current_bot, _set_current_bot
from chattice.exceptions import (
    DependencyResolutionError,
    SkipHandler,
    StopPropagation,
    UnhandledInteractionError,
)
from chattice.filters.base import evaluate_filters
from chattice.fsm import FSMContext
from chattice.fsm.storage import BaseStorage, FSMStrategy, StorageKey
from chattice.middleware import MiddlewareLike, NextHandler
from chattice.observability import RuntimeDiagnostics

from .dependency import handler_qualified_name
from .handler import HandlerObject
from .lifespan import Lifespan, LifespanResource
from .middleware import invoke_with_middleware
from .observer import EventObserver
from .router import Router

_observability_logger = logging.getLogger("chattice.observability")
_routing_logger = logging.getLogger("chattice.routing")
_runtime_logger = logging.getLogger("chattice.runtime")


async def _maybe_hook(hooks: object | None, name: str, *args: object) -> None:
    """Invoke an optional observability hook; failures never break routing."""
    if hooks is None:
        return
    method = getattr(hooks, name, None)
    if method is None:
        return
    try:
        await method(*args)
    except Exception:
        _observability_logger.error("%s hook failed", name)


@dataclass(frozen=True, slots=True)
class _DispatchOutcome:
    handled: bool = False
    stopped: bool = False
    result: object = None


class Dispatcher(Router):
    """Root router and transport-independent event feed."""

    def lifespan(self, *resources: LifespanResource) -> Lifespan:
        """An async context manager starting resources in order and closing
        them in reverse (partial-start rollback included). Plug it into
        FastAPI via ``app.router.lifespan_context = dispatcher.lifespan(...)``.
        """
        return Lifespan(*resources)

    async def run_pubsub(
        self,
        subscription: str,
        *,
        bot: Bot | None = None,
        credentials: Credentials | None = None,
        credentials_provider: CredentialsProvider | None = None,
        max_concurrency: int = 10,
        max_outstanding_messages: int = 100,
        idempotency_storage: IdempotencyStorage | None = None,
        max_delivery_attempts: int = 5,
        stop_event: asyncio.Event | None = None,
    ) -> None:
        """Streaming-pull Pub/Sub ingress: the long-lived subscriber mode.

        Runs every delivery through THIS dispatcher's router/filter/
        middleware/DI pipeline. Handler answers go outbound through
        ``bot`` where semantics allow (text -> send_message, Card ->
        update_message/send_message); Dialog answers are rejected with
        ``CapabilityNotSupported`` (dialogs require the synchronous HTTP
        transport). Requires the ``chattice[pubsub]`` extra.

        Blocks until ``stop_event`` fires or SIGINT/SIGTERM; drains
        in-flight handlers before returning.
        """
        from chattice.transports.pubsub_runner import PubSubPullRunner

        runner = PubSubPullRunner(
            self,
            subscription,
            bot=bot,
            credentials=credentials,
            credentials_provider=credentials_provider,
            max_concurrency=max_concurrency,
            max_outstanding_messages=max_outstanding_messages,
            idempotency_storage=idempotency_storage,
            max_delivery_attempts=max_delivery_attempts,
            delayed_event_ms=self._runtime_diagnostics.delayed_event_ms,
            observability_hooks=self._observability_hooks,
        )
        await runner.run(stop_event=stop_event)

    def __init__(
        self,
        *,
        name: str = "dispatcher",
        bot: object | None = None,
        fsm_storage: BaseStorage | None = None,
        fsm_strategy: FSMStrategy = FSMStrategy.USER_IN_SPACE,
        # ``object``: implementations may provide ANY subset of the
        # optional ObservabilityHooks surface.
        observability_hooks: object | None = None,
        preview_features: Iterable[PreviewFeature] = (),
        strict_interactions: bool = False,
        runtime_diagnostics: RuntimeDiagnostics | None = None,
    ) -> None:
        super().__init__(name=name)
        self._is_dispatcher = True
        self._bot = bot
        self._fsm_storage = fsm_storage
        self._fsm_strategy = fsm_strategy
        self._observability_hooks = observability_hooks
        # One enrollment for both directions: the Dispatcher's own
        # features plus those of the Bot it was constructed with.
        self._preview_capabilities = PreviewCapabilities(preview_features)
        bot_preview = getattr(bot, "preview_capabilities", None)
        if isinstance(bot_preview, PreviewCapabilities):
            self._preview_capabilities = self._preview_capabilities | bot_preview
        self._strict_interactions = strict_interactions
        self._runtime_diagnostics = runtime_diagnostics or RuntimeDiagnostics()

    @property
    def preview_capabilities(self) -> PreviewCapabilities:
        """The immutable Developer Preview enrollment for typed routing."""
        return self._preview_capabilities

    async def feed_update(self, event: Event, **context: object) -> object:
        """Route one domain event and return the handler result unchanged."""
        if not isinstance(event, Event):
            raise TypeError("feed_update() accepts chattice Event instances only")
        _routing_logger.debug("event received: %s", _event_context(event))
        _routing_logger.debug("routing started: %s", _event_context(event))
        data = dict(context)
        if "bot" not in data and self._bot is not None:
            data["bot"] = self._bot
        contextual_bot = data.get("bot")
        # Configuration, not caller context, is the source of truth: a
        # feed_update() kwarg must not bypass explicit preview enrollment.
        data["preview_capabilities"] = self._preview_capabilities
        if self._fsm_storage is not None:
            data["state"] = FSMContext(
                self._fsm_storage, StorageKey.build(event, self._fsm_strategy)
            )
        result: object = None
        error: BaseException | None = None
        bot_token = _set_current_bot(contextual_bot)
        try:
            await _maybe_hook(self._observability_hooks, "before_event", event, data)
            try:
                outcome = await self._route_event(event, data)
                if outcome.handled:
                    result = outcome.result
            except BaseException as exc:
                error = exc
                if not isinstance(exc, Exception):
                    # CancelledError and friends bypass error routing but are
                    # still reported to the after_event hook, then re-raised.
                    raise
                error_event = ErrorEvent(
                    source_event=event,
                    exception=exc,
                    raw=event.raw,
                )
                try:
                    error_outcome = await self._route_pass(error_event, data, "error")
                except Exception as error_handler_failure:
                    if error_handler_failure is exc:
                        raise
                    _runtime_logger.error(
                        "error handler failed: exception_type=%s",
                        type(error_handler_failure).__name__,
                        exc_info=_runtime_logger.isEnabledFor(logging.DEBUG) or None,
                    )
                    raise error_handler_failure from exc
                if error_outcome.handled:
                    result = error_outcome.result
                else:
                    # An unhandled failure must never be silent: one safe,
                    # structured ERROR per delivery (no payload, no message).
                    _log_unhandled_failure(event, exc)
                    raise
        finally:
            try:
                await _maybe_hook(
                    self._observability_hooks,
                    "after_event",
                    event,
                    data,
                    result,
                    error,
                )
            finally:
                _reset_current_bot(bot_token)
        return result

    async def _route_event(
        self, event: Event, data: dict[str, object]
    ) -> _DispatchOutcome:
        for observer_name in self._specific_observer_names(event):
            outcome = await self._route_pass(event, data, observer_name)
            if outcome.handled or outcome.stopped:
                return outcome
        if not isinstance(event, ErrorEvent):
            outcome = await self._route_pass(event, data, "event")
            if not outcome.handled and not outcome.stopped:
                self._log_unmatched(event)
            return outcome
        return _DispatchOutcome()

    def _log_unmatched(self, event: Event) -> None:
        """Interactive events without a handler must not pass silently."""
        if isinstance(event, ActionEvent):
            fields = [f"event_type={event.event_type}", f"action={event.function_name}"]
            message_name = getattr(event.message, "name", None)
            if message_name:
                fields.append(f"message={message_name}")
            _routing_logger.debug(
                "registered actions: %s", self._registered_action_names()
            )
            _routing_logger.warning("unhandled interaction: %s", " ".join(fields))
            if self._strict_interactions:
                raise UnhandledInteractionError(
                    f"Unhandled interactive event: {' '.join(fields)}"
                )
            return
        if isinstance(event, CommandEvent):
            fields = [
                f"event_type={event.event_type}",
                f"command_id={event.command_id}",
            ]
            _routing_logger.warning("unhandled command: %s", " ".join(fields))
            if self._strict_interactions:
                raise UnhandledInteractionError(
                    f"Unhandled interactive event: {' '.join(fields)}"
                )
            return
        _routing_logger.debug("no handler matched: %s", _event_context(event))

    def _registered_action_names(self) -> str:
        names: list[str] = []
        for router, _ in self._walk():
            for name in router.action.registered_names:
                if name not in names:
                    names.append(name)
        return ", ".join(names) if names else "-"

    async def _route_pass(
        self,
        event: Event,
        data: dict[str, object],
        observer_name: str,
    ) -> _DispatchOutcome:
        for router_index, (router, middleware) in enumerate(self._walk()):
            observer = self._observer(router, observer_name)
            handlers = observer.handlers
            if not handlers:
                continue
            _routing_logger.debug(
                "observer selected: router=%s observer=%s router_path=router[%d]",
                router.name,
                observer_name,
                router_index,
            )
            observer_data = dict(data)
            try:
                matches = await evaluate_filters(observer.filters, event, observer_data)
            except SkipHandler:
                continue
            except StopPropagation:
                return _DispatchOutcome(stopped=True)
            except Exception as exc:
                _attach_failure_context(exc, stage="filter")
                raise
            if not matches:
                continue
            for handler in handlers:
                candidate_data = dict(observer_data)
                try:
                    try:
                        matches = await evaluate_filters(
                            handler.filters, event, candidate_data
                        )
                    except Exception as exc:
                        _attach_failure_context(
                            exc,
                            stage="filter",
                            handler=handler_qualified_name(handler.callback),
                        )
                        raise
                    if not matches:
                        continue
                    # `handler_started` must be visible BEFORE the callback
                    # runs: a hung handler must not look like silence.
                    _routing_logger.debug(
                        "handler_selected: router=%s observer=%s handler=%s "
                        "router_path=router[%d]",
                        router.name,
                        observer_name,
                        handler_qualified_name(handler.callback),
                        router_index,
                    )
                    _routing_logger.info(
                        "handler_started: handler=%s",
                        handler_qualified_name(handler.callback),
                    )
                    await _maybe_hook(
                        self._observability_hooks,
                        "before_handler",
                        event,
                        candidate_data,
                        handler_qualified_name(handler.callback),
                    )
                    started_at = time.perf_counter()
                    result = await self._invoke(
                        handler, middleware, event, candidate_data
                    )
                    duration_ms = (time.perf_counter() - started_at) * 1000
                    slow_handler_ms = self._runtime_diagnostics.slow_handler_ms
                    if slow_handler_ms is not None and duration_ms > slow_handler_ms:
                        _runtime_logger.warning(
                            "slow handler: handler=%s duration_ms=%.1f",
                            handler_qualified_name(handler.callback),
                            duration_ms,
                        )
                except SkipHandler:
                    continue
                except StopPropagation:
                    return _DispatchOutcome(stopped=True)
                except Exception as exc:
                    if _failure_stage(exc) == "unknown":
                        # handler/DI exceptions are tagged inside _invoke;
                        # anything untagged escaped a middleware frame.
                        _attach_failure_context(
                            exc,
                            stage="middleware",
                            handler=handler_qualified_name(handler.callback),
                        )
                    raise
                _routing_logger.info(
                    "handler_completed: handler=%s result_type=%s",
                    handler_qualified_name(handler.callback),
                    type(result).__name__,
                )
                await _maybe_hook(
                    self._observability_hooks,
                    "after_handler",
                    event,
                    candidate_data,
                    handler_qualified_name(handler.callback),
                    result,
                )
                return _DispatchOutcome(handled=True, result=result)
        return _DispatchOutcome()

    @staticmethod
    def _observer(router: Router, name: str) -> EventObserver:
        observer = getattr(router, name)
        if not isinstance(observer, EventObserver):
            raise TypeError(f"Router attribute {name!r} is not an EventObserver")
        return observer

    def _specific_observer_names(self, event: Event) -> tuple[str, ...]:
        if isinstance(event, MessageEvent):
            return ("message",)
        if isinstance(event, ActionEvent):
            if event.dialog is not None and (
                event.dialog.type == DialogEventType.SUBMIT_DIALOG
            ):
                return ("dialog_submit",)
            if event.dialog is not None and (
                event.dialog.type == DialogEventType.CANCEL_DIALOG
            ):
                return ("dialog_cancel",)
            return ("action",)
        if isinstance(event, CommandEvent):
            if event.kind is CommandKind.MESSAGE_ACTION:
                return ("message_action", "command")
            if event.kind is CommandKind.SLASH_COMMAND:
                return ("slash_command", "command")
            if event.kind is CommandKind.QUICK_COMMAND:
                return ("quick_command", "command")
            return ()
        if isinstance(event, AddedToSpaceEvent):
            return ("added_to_space",)
        if isinstance(event, RemovedFromSpaceEvent):
            return ("removed_from_space",)
        if isinstance(event, SystemCommandEvent):
            # Developer Preview: typed routing only after explicit opt-in.
            if PreviewFeature.MESSAGE_STREAMING not in self._preview_capabilities:
                return ()
            return ("system_command",)
        if isinstance(event, WidgetUpdatedEvent):
            return ("widget_updated",)
        if isinstance(event, AppHomeEvent):
            return ("app_home",)
        if isinstance(event, FormSubmitEvent):
            return ("form_submit",)
        if isinstance(event, UnknownEvent):
            return ("unknown_event",)
        if isinstance(event, ErrorEvent):
            return ("error",)
        return ()

    @staticmethod
    async def _invoke(
        handler: HandlerObject,
        middleware: tuple[MiddlewareLike, ...],
        event: Event,
        data: MutableMapping[str, object],
    ) -> object:
        async def resolved_handler(
            resolved_event: Event, resolved_data: MutableMapping[str, object]
        ) -> object:
            try:
                return await handler.plan.invoke(resolved_event, resolved_data)
            except DependencyResolutionError as exc:
                _attach_failure_context(
                    exc,
                    stage="dependency_resolution",
                    handler=handler_qualified_name(handler.callback),
                )
                raise
            except Exception as exc:
                _attach_failure_context(
                    exc,
                    stage="handler",
                    handler=handler_qualified_name(handler.callback),
                )
                raise

        next_handler: NextHandler = resolved_handler
        return await invoke_with_middleware(next_handler, middleware, event, data)


def _event_context(event: Event) -> str:
    """Return safe, structured event fields for DEBUG logs."""
    fields = [f"event_type={event.event_type}"]
    if isinstance(event, ActionEvent):
        fields.append(f"action={event.function_name}")
    elif isinstance(event, CommandEvent):
        fields.append(f"command_id={event.command_id}")
    return " ".join(fields)


def _attach_failure_context(
    exc: BaseException, *, stage: str, handler: str | None = None
) -> BaseException:
    """Tag an in-flight exception with the pipeline stage it escaped from."""
    try:
        # Dynamic tag on a foreign exception object — setattr is deliberate
        # (the attribute does not exist on BaseException's static shape).
        setattr(exc, "_chattice_stage", stage)  # noqa: B010
    except Exception:
        pass  # exotic exception objects must not break routing
    if handler is not None:
        try:
            setattr(exc, "_chattice_handler", handler)  # noqa: B010
        except Exception:
            pass
    return exc


def _failure_stage(exc: BaseException) -> str:
    return getattr(exc, "_chattice_stage", "unknown")


def _log_unhandled_failure(event: Event, exc: BaseException) -> None:
    """One structured ERROR per unhandled failure: never silent, never leaky.

    Exception CLASS only — never the message: handler messages may contain
    secrets such as tokens or form values. The traceback is attached only
    when the logger runs at DEBUG (developer mode).
    """
    fields = [
        f"event_type={event.event_type}",
        f"exception_type={type(exc).__name__}",
        f"stage={_failure_stage(exc)}",
    ]
    if isinstance(event, ActionEvent):
        fields.append(f"action={event.function_name}")
    elif isinstance(event, CommandEvent):
        fields.append(f"command_id={event.command_id}")
    handler = getattr(exc, "_chattice_handler", None)
    if handler is not None:
        fields.append(f"handler={handler}")
    message_name = getattr(getattr(event, "message", None), "name", None)
    if message_name:
        fields.append(f"message_id={message_name}")
    _runtime_logger.error(
        "handler failed: %s",
        " ".join(fields),
        exc_info=_runtime_logger.isEnabledFor(logging.DEBUG) or None,
    )


__all__ = ["Dispatcher"]
