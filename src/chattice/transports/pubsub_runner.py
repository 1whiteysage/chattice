"""Streaming-pull Pub/Sub runner: the long-lived subscriber ingress.

Feeds the SAME parser -> Dispatcher -> Router -> filters -> middleware ->
DI -> handlers pipeline as the HTTP router — no second dispatcher.

Operator flow::

    await dispatcher.run_pubsub(
        "projects/P/subscriptions/S",
        bot=bot,
        credentials_provider=...,
    )

Behavior contract:

- streaming pull via ``google-cloud-pubsub`` (lazy import; install the
  ``pubsub`` extra);
- bounded concurrency via an asyncio semaphore — no global serialization;
- one explicit per-delivery attempt state machine: fresh owner token and
  subscription-namespaced dedupe key per delivery, claim
  (COMPLETED -> ACK, ACTIVE -> NACK, FIRST -> process), lease renewal
  tied to the attempt, complete-then-ACK exactly once — a delivery is
  NEVER both ACKed and NACKed;
- pre-completion failures: owner-checked release, then NACK; a poison
  message (``max_delivery_attempts`` reached) is ACKed after a
  best-effort user notification (documented terminal policy);
- ``run()`` races the stop event against the streaming-pull future and
  surfaces unrecoverable subscriber failures; shutdown cancels the pull
  future, stops scheduling and drains every scheduled attempt;
- handler answers go outbound through the Bot resource facade:
  ``str`` -> ``bot.app.messages.create``, ``Card`` ->
  ``bot.app.messages.update`` for a clicked bot card (message identity
  from ``ActionEvent.message``) or ``bot.app.messages.create`` otherwise;
- ``Dialog`` / ``ActionStatus`` answers raise ``CapabilityNotSupported``
  because dialogs require a synchronous transport, and the space is told;
- structured logs under ``chattice.pubsub``; raw event payloads are never
  included.

Wire format: Google Chat publishes the interaction JSON directly as the
Pub/Sub message data. A base64 push envelope is also accepted for
compatibility with push-shaped topics.
"""

from __future__ import annotations

import asyncio
import json
import logging
import signal
import time
from collections.abc import Mapping
from concurrent.futures import Future
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Protocol

from google.auth.credentials import Credentials

from chattice.adapters.google_chat import parse_interaction
from chattice.auth import CredentialsProvider
from chattice.capabilities import CapabilityNotSupported, ResponseCapabilities
from chattice.cards import ActionStatus, Card, Dialog
from chattice.dispatcher import Dispatcher
from chattice.events import ActionEvent, CommandEvent, Event, ThreadRef
from chattice.exceptions import ChatticeError
from chattice.idempotency import (
    ClaimResult,
    IdempotencyStorage,
    MemoryIdempotencyStorage,
    new_owner,
)
from chattice.transports.pubsub import PubSubEnvelopeError, decode_message_data

logger = logging.getLogger("chattice.pubsub")

__all__ = ["PubSubPullRunner"]

DIALOG_UNSUPPORTED_MESSAGE = (
    "Dialogs require a synchronous Google Chat transport. "
    "Use a Card form or HTTP transport."
)

_DEFAULT_LEASE_SECONDS = 300.0


def _event_context(event: Event | None) -> str:
    """Return safe, structured event fields for delivery logs."""
    if event is None:
        return "event_type=unknown"
    fields = [f"event_type={event.event_type}"]
    if isinstance(event, ActionEvent):
        fields.append(f"action={event.function_name}")
    elif isinstance(event, CommandEvent):
        fields.append(f"command_id={event.command_id}")
    return " ".join(fields)


def _delivery_attempt(message: Any) -> object:
    """Read the optional Pub/Sub delivery attempt without assuming a proto."""
    return getattr(message, "delivery_attempt", None)


async def _maybe_hook(hooks: object | None, name: str, *args: object) -> None:
    """Invoke an optional observability hook; failures never break delivery."""
    if hooks is None:
        return
    method = getattr(hooks, name, None)
    if method is None:
        return
    try:
        await method(*args)
    except Exception:
        logger.error("%s hook failed", name)


def _log_outbound_failure(exc: Exception, stage: str, event: Event) -> None:
    """One ERROR per failed Google API call: stage, class only — no message.

    The traceback is attached only when the logger runs at DEBUG.
    """
    logger.error(
        "outbound failed: %s stage=%s exception_type=%s",
        _event_context(event),
        stage,
        type(exc).__name__,
        exc_info=logger.isEnabledFor(logging.DEBUG) or None,
    )


def _import_pubsub() -> Any:
    try:
        from google.cloud import pubsub_v1  # type: ignore[import-untyped]
    except ImportError as error:
        raise ChatticeError(
            "Pub/Sub pull requires google-cloud-pubsub — install the "
            "chattice pubsub extra (uv add 'chattice[pubsub]')."
        ) from error
    return pubsub_v1


class _KeyedLockRegistry:
    """Fair per-key asyncio locks, cleaned up when idle.

    Serializes outbound card updates per ``message.name`` inside one
    process instance; different keys stay fully concurrent.
    """

    def __init__(self) -> None:
        self._locks: dict[str, asyncio.Lock] = {}
        self._waiters: dict[str, int] = {}

    async def acquire(self, key: str) -> None:
        lock = self._locks.get(key)
        if lock is None:
            lock = self._locks[key] = asyncio.Lock()
        self._waiters[key] = self._waiters.get(key, 0) + 1
        try:
            await lock.acquire()
        except BaseException:
            self._drop_waiter(key)
            raise

    def release(self, key: str) -> None:
        self._drop_waiter(key)
        self._locks[key].release()
        if self._waiters.get(key, 0) == 0:
            self._locks.pop(key, None)

    def _drop_waiter(self, key: str) -> None:
        remaining = self._waiters.get(key, 0) - 1
        if remaining <= 0:
            self._waiters.pop(key, None)
        else:
            self._waiters[key] = remaining


class _OutboundMessages(Protocol):
    """Answer surface of the message resource client."""

    async def create(self, *args: Any, **kwargs: Any) -> object: ...

    async def update(self, *args: Any, **kwargs: Any) -> object: ...


class _OutboundNamespace(Protocol):
    """Structural view of the identity namespace's answer surface."""

    @property
    def messages(self) -> _OutboundMessages: ...


class _OutboundBot(Protocol):
    """Structural contract for the runner's outbound bot.

    Both ``Bot`` and the testing ``MockBot`` satisfy it; the runner only
    needs the answer surface (text send, card send, card update) through
    the resource facade.
    """

    @property
    def app(self) -> _OutboundNamespace: ...


@dataclass(slots=True)
class _Attempt:
    """One delivery attempt: the message, its claim, and the parsed event."""

    message: Any
    key: str
    owner: str
    # Set once the payload parsed; failure reporting works without it.
    event: Event | None = None


def _clicked_message(event: Event) -> str | None:
    """Name of the message whose card was clicked, when the event has one."""
    if isinstance(event, ActionEvent) and event.message is not None:
        return event.message.name
    return None


def _answer_mode(event: Event, result: object) -> str:
    """How a handler result is delivered over the ack-only Pub/Sub channel."""
    if isinstance(result, str):
        return "send_message"
    if isinstance(result, Card):
        clicked = _clicked_message(event) is not None
        return "update_message" if clicked else "send_message"
    return "unsupported"


class PubSubPullRunner:
    """Pull the subscription and run every delivery through the dispatcher."""

    def __init__(
        self,
        dispatcher: Dispatcher,
        subscription: str,
        *,
        bot: _OutboundBot | None = None,
        credentials: Credentials | None = None,
        credentials_provider: CredentialsProvider | None = None,
        max_concurrency: int = 10,
        max_outstanding_messages: int = 100,
        idempotency_storage: IdempotencyStorage | None = None,
        max_delivery_attempts: int = 5,
        renew_interval: float | None = None,
        delayed_event_ms: float | None = 5000.0,
        # ``object``: implementations may provide ANY subset of the
        # optional ObservabilityHooks surface.
        observability_hooks: object | None = None,
    ) -> None:
        if max_concurrency < 1:
            raise ValueError("max_concurrency must be >= 1")
        self._dispatcher = dispatcher
        self._subscription = subscription
        self._bot = bot
        self._credentials = credentials
        self._credentials_provider = credentials_provider
        self._max_concurrency = max_concurrency
        self._max_outstanding_messages = max_outstanding_messages
        self._max_delivery_attempts = max_delivery_attempts
        self._delayed_event_ms = delayed_event_ms
        self._observability_hooks = observability_hooks
        self._renew_interval = renew_interval or (_DEFAULT_LEASE_SECONDS / 2)
        self._idempotency = (
            idempotency_storage
            if idempotency_storage is not None
            else MemoryIdempotencyStorage()
        )
        self._semaphore = asyncio.Semaphore(max_concurrency)
        # Serialize outbound card updates per message inside this process;
        # different messages stay concurrent.
        self._update_locks = _KeyedLockRegistry()
        # Latest seen event_time per card (message resource name), used for
        # stale-interaction warnings. In-process only; never drops events.
        self._latest_event_times: dict[str, datetime] = {}
        # futures are tracked the moment _schedule runs, so close()
        # can never snapshot an empty set while a scheduled coroutine has
        # not entered its first await yet.
        self._scheduled: set[Future[None]] = set()
        self._loop: asyncio.AbstractEventLoop | None = None
        self._subscriber: Any = None
        self._pull_future: Any = None
        self._closed = False

    # ------------------------------------------------------------------ run

    async def run(self, stop_event: asyncio.Event | None = None) -> None:
        """Streaming-pull loop until ``stop_event`` fires (or SIGINT/SIGTERM).

        Races the stop event against the streaming-pull future: an
        unrecoverable subscriber failure ends the run and surfaces as a
        :class:`ChatticeError` (the docstring contract is enforced).
        Returns after the subscriber is closed and scheduled attempts are
        drained.
        """
        self._loop = asyncio.get_running_loop()
        pubsub_v1 = _import_pubsub()
        credentials = await self._resolve_credentials()
        self._subscriber = pubsub_v1.SubscriberClient(credentials=credentials)
        self._pull_future = self._subscriber.subscribe(
            self._subscription,
            callback=self._schedule,
            flow_control=pubsub_v1.types.FlowControl(
                max_messages=self._max_outstanding_messages
            ),
        )
        logger.info("pubsub runner started: subscription=%s", self._subscription)
        stop = stop_event if stop_event is not None else self._install_signals()
        stop_waiter = asyncio.ensure_future(stop.wait())
        # StreamingPullFuture.result() blocks until the stream ends; run it
        # off-loop so BOTH terminal conditions (stop, stream end) race.
        stream_waiter = asyncio.ensure_future(
            asyncio.to_thread(self._pull_future.result)
        )
        try:
            await asyncio.wait(
                {stop_waiter, stream_waiter},
                return_when=asyncio.FIRST_COMPLETED,
            )
            if not stop.is_set():
                # The stream ended on its own — unrecoverable by definition
                # of StreamingPullFuture. Surface the subscriber's error.
                try:
                    stream_waiter.result()
                except Exception as error:
                    raise ChatticeError("Pub/Sub subscriber failed") from error
                raise ChatticeError("Pub/Sub subscriber stopped unexpectedly")
        finally:
            self._pull_future.cancel()
            try:
                await asyncio.to_thread(self._pull_future.result)
            except Exception:  # subscriber teardown is best-effort here
                pass
            await self.close()

    def _install_signals(self) -> asyncio.Event:
        stop = asyncio.Event()
        loop = self._loop
        assert loop is not None
        for sig in (signal.SIGINT, signal.SIGTERM):
            try:
                loop.add_signal_handler(sig, stop.set)
            except (NotImplementedError, RuntimeError):
                pass  # non-main thread or unsupported platform
        return stop

    async def _resolve_credentials(self) -> Credentials | None:
        if self._credentials is not None:
            return self._credentials
        if self._credentials_provider is not None:
            return await asyncio.to_thread(self._credentials_provider)
        return None

    async def close(self) -> None:
        """Stop the subscriber, stop scheduling, drain attempts (idempotent)."""
        if self._closed:
            return
        self._closed = True
        self._loop = None  # no new scheduling after close begins
        if self._subscriber is not None:
            await asyncio.to_thread(self._subscriber.close)
            self._subscriber = None
        scheduled = list(self._scheduled)
        self._scheduled.clear()
        if scheduled:
            await asyncio.gather(
                *(asyncio.wrap_future(future) for future in scheduled),
                return_exceptions=True,
            )
        logger.info("pubsub runner stopped")

    # ----------------------------------------------------------- delivery

    def _schedule(self, message: Any) -> None:
        """Subscriber callback (worker thread) -> asyncio handler task."""
        if self._loop is None:
            return
        try:
            future = asyncio.run_coroutine_threadsafe(self._handle(message), self._loop)
        except RuntimeError:
            return  # loop already gone during shutdown
        self._scheduled.add(future)
        future.add_done_callback(self._scheduled.discard)

    async def _handle(self, message: Any) -> None:
        """One explicit per-delivery attempt state machine.

        claim -> COMPLETED: ACK | ACTIVE: NACK | FIRST: process -> complete
        claim -> ACK exactly once. Any pre-completion failure: owner-checked
        release, then NACK — or poison-ACK under the documented terminal
        policy (max attempts reached, after a best-effort notification).
        The same delivery is NEVER both ACKed and NACKed.
        """
        # Namespaced key: Google message IDs are unique per TOPIC, so a
        # shared store needs the subscription in the key (push parity).
        attempt = _Attempt(
            message=message,
            key=f"{self._subscription}:{message.message_id}",
            owner=new_owner(),
        )
        if not await self._claim(attempt):
            return
        renewal: asyncio.Task[None] | None = None
        try:
            renewal = asyncio.create_task(
                self._renew_loop(attempt.key, attempt.owner, message)
            )
            await self._process(attempt)
        except asyncio.CancelledError:
            message.nack()
            raise
        except Exception as error:
            await self._fail(attempt, error)
        finally:
            if renewal is not None:
                await self._stop_renewal(renewal, message)

    async def _claim(self, attempt: _Attempt) -> bool:
        """Claim the delivery; False when it was settled without processing."""
        message = attempt.message
        logger.debug(
            "claim_started: message_id=%s attempt=%s",
            message.message_id,
            _delivery_attempt(message),
        )
        try:
            claim = await self._idempotency.claim(
                attempt.key, owner=attempt.owner, lease_seconds=_DEFAULT_LEASE_SECONDS
            )
        except Exception as error:
            # Storage unavailable: NACK so Pub/Sub redelivers later — never
            # ack work whose ownership we could not record.
            logger.error(
                "claim failed: message_id=%s attempt=%s error=%s",
                message.message_id,
                _delivery_attempt(message),
                str(error),
                exc_info=logger.isEnabledFor(logging.DEBUG) or None,
            )
            message.nack()
            return False
        logger.debug(
            "claim_result=%s: message_id=%s attempt=%s",
            claim.name.lower(),
            message.message_id,
            _delivery_attempt(message),
        )
        if claim is ClaimResult.COMPLETED:
            logger.info(
                "duplicate acked: message_id=%s delivery_kind=duplicate_completed",
                message.message_id,
            )
            message.ack()
            return False
        if claim is ClaimResult.ACTIVE:
            # Another owner is processing: hand the delivery back.
            logger.warning(
                "active duplicate nacked: message_id=%s delivery_kind=active_duplicate",
                message.message_id,
            )
            message.nack()
            return False
        return True

    async def _process(self, attempt: _Attempt) -> None:
        """Parse, dispatch, answer, then complete the claim and ACK."""
        message = attempt.message
        delivery_started = time.perf_counter()
        event = attempt.event = self._parse(message)
        logger.debug(
            "parsed: %s message_id=%s",
            _event_context(event),
            message.message_id,
        )
        self._log_delivery_received(message, event)
        capabilities = ResponseCapabilities.resolve(transport="pubsub", event=event)
        result = await self._dispatcher.feed_update(
            event,
            bot=self._bot,
            capabilities=capabilities,
        )
        handler_duration_ms = (time.perf_counter() - delivery_started) * 1000
        outbound_started = time.perf_counter()
        try:
            outbound_operation = await self._answer(event, result)
        except CapabilityNotSupported as error:
            await self._reject_capability(attempt, event, error)
            return
        # Success: complete the claim FIRST, then ACK exactly once. If
        # complete fails, the attempt falls into the failure path —
        # release + NACK — preserving at-least-once semantics.
        outbound_duration_ms = (time.perf_counter() - outbound_started) * 1000
        await self._complete(attempt)
        message.ack()
        await _maybe_hook(
            self._observability_hooks,
            "delivery_acked",
            message.message_id,
            event,
        )
        logger.info(
            "acked: message_id=%s event_type=%s handler_duration_ms=%.1f "
            "outbound_operation=%s outbound_duration_ms=%.1f "
            "total_duration_ms=%.1f",
            message.message_id,
            event.event_type,
            handler_duration_ms,
            outbound_operation or "none",
            outbound_duration_ms,
            (time.perf_counter() - delivery_started) * 1000,
        )

    async def _reject_capability(
        self, attempt: _Attempt, event: Event, error: CapabilityNotSupported
    ) -> None:
        """Terminal for this delivery: tell the space, complete, THEN ack.

        A completion failure would otherwise leave an acked-but-unrecorded
        delivery.
        """
        message = attempt.message
        logger.error(
            "capability rejected: message_id=%s attempt=%s %s error=%s",
            message.message_id,
            _delivery_attempt(message),
            _event_context(event),
            str(error),
            exc_info=logger.isEnabledFor(logging.DEBUG) or None,
        )
        space_name = event.space.name if event.space is not None else None
        if self._bot is not None and space_name is not None:
            await self._bot.app.messages.create(space_name, text=str(error))
        await self._complete(attempt)
        message.ack()

    async def _complete(self, attempt: _Attempt) -> None:
        message = attempt.message
        logger.debug(
            "complete_started: message_id=%s attempt=%s",
            message.message_id,
            _delivery_attempt(message),
        )
        await self._idempotency.complete(attempt.key, owner=attempt.owner)
        logger.debug(
            "complete_succeeded: message_id=%s attempt=%s",
            message.message_id,
            _delivery_attempt(message),
        )

    async def _fail(self, attempt: _Attempt, error: Exception) -> None:
        """Release the claim, then NACK — or poison-ACK at the attempt limit."""
        message = attempt.message
        await self._release(attempt)
        if message.delivery_attempt >= self._max_delivery_attempts:
            # Documented terminal policy: notify first (best-effort),
            # then poison-ACK so the message cannot redeliver forever.
            await self._notify_poison(attempt.event, type(error).__name__)
            logger.error(
                "poison message acked: message_id=%s attempt=%s %s exception_type=%s",
                message.message_id,
                _delivery_attempt(message),
                _event_context(attempt.event),
                type(error).__name__,
                exc_info=logger.isEnabledFor(logging.DEBUG) or None,
            )
            message.ack()
            return
        # Exception CLASS only — never the message: it may contain
        # secrets (form values, tokens, user text).
        logger.error(
            "delivery failed, nacked: message_id=%s attempt=%s %s exception_type=%s",
            message.message_id,
            _delivery_attempt(message),
            _event_context(attempt.event),
            type(error).__name__,
            exc_info=logger.isEnabledFor(logging.DEBUG) or None,
        )
        message.nack()
        await _maybe_hook(
            self._observability_hooks,
            "delivery_nacked",
            message.message_id,
            attempt.event,
        )

    async def _release(self, attempt: _Attempt) -> None:
        """Owner-checked release; a failure is logged, never raised."""
        message = attempt.message
        logger.debug(
            "release_started: message_id=%s attempt=%s",
            message.message_id,
            _delivery_attempt(message),
        )
        try:
            await self._idempotency.release(attempt.key, owner=attempt.owner)
        except Exception as release_error:
            logger.error(
                "release failed: message_id=%s attempt=%s error=%s",
                message.message_id,
                _delivery_attempt(message),
                str(release_error),
                exc_info=logger.isEnabledFor(logging.DEBUG) or None,
            )
            return
        logger.debug(
            "release_succeeded: message_id=%s attempt=%s",
            message.message_id,
            _delivery_attempt(message),
        )

    @staticmethod
    async def _stop_renewal(renewal: asyncio.Task[None], message: Any) -> None:
        renewal.cancel()
        try:
            await renewal
        except asyncio.CancelledError:
            pass
        except Exception as renew_error:
            logger.exception(
                "renewal task failed: message_id=%s attempt=%s error=%s",
                message.message_id,
                _delivery_attempt(message),
                str(renew_error),
            )

    async def _renew_loop(self, key: str, owner: str, message: Any) -> None:
        """Renew the claim lease while the attempt is in flight.

        A valid long handler must not be reclaimed by an expired lease.
        On renewal failure the loop stops renewing; the attempt itself
        continues — at-least-once survives because the work is already
        running (a takeover duplicates, it never loses).
        """
        while True:
            await asyncio.sleep(self._renew_interval)
            try:
                renewed = await self._idempotency.renew(
                    key, owner=owner, lease_seconds=_DEFAULT_LEASE_SECONDS
                )
            except Exception as error:
                logger.error(
                    "renewal failed: message_id=%s attempt=%s error=%s",
                    message.message_id,
                    _delivery_attempt(message),
                    str(error),
                    exc_info=logger.isEnabledFor(logging.DEBUG) or None,
                )
                return
            if not renewed:
                logger.error(
                    "renewal refused: message_id=%s (lease lost)",
                    message.message_id,
                )
                return

    async def _notify_poison(self, event: Event | None, error_class: str) -> None:
        """Best-effort user notification before a poison ACK (documented)."""
        if (
            self._bot is None
            or event is None
            or event.space is None
            or event.space.name is None
        ):
            return
        try:
            await self._bot.app.messages.create(
                event.space.name,
                text=f"Error while processing your message ({error_class}).",
            )
        except Exception as notify_error:
            logger.exception("poison notification failed: error=%s", str(notify_error))

    # ------------------------------------------------------------ diagnostics

    def _log_delivery_received(self, message: Any, event: Event) -> None:
        """One structured INFO per FIRST-claim delivery.

        Identity fields, event age (no invented values: age and kind are
        omitted when the source data is missing), and a WARNING for
        delayed interactions. Stale-interaction tracking is side-effect
        free: it never drops a delivery.
        """
        attempt = _delivery_attempt(message)
        kind: str | None = None
        if attempt is not None:
            kind = "redelivery" if isinstance(attempt, int) and attempt >= 1 else "new"
        fields = [
            f"pubsub_message_id={message.message_id}",
            f"event_type={event.event_type}",
        ]
        if attempt is not None:
            fields.append(f"delivery_attempt={attempt}")
        if isinstance(event, ActionEvent):
            fields.append(f"action={event.function_name}")
        elif isinstance(event, CommandEvent):
            fields.append(f"command_id={event.command_id}")
        space_name = getattr(getattr(event, "space", None), "name", None)
        message_name = getattr(getattr(event, "message", None), "name", None)
        if space_name:
            fields.append(f"space_resource_name={space_name}")
        if message_name:
            fields.append(f"message_resource_name={message_name}")
        received = datetime.now(UTC)
        fields.append(f"received_time={received.isoformat()}")
        if event.event_time is not None:
            fields.append(f"event_time={event.event_time.isoformat()}")
            age_ms = (received - event.event_time).total_seconds() * 1000
            fields.append(f"event_age_ms={age_ms:.1f}")
            if self._delayed_event_ms is not None and age_ms > self._delayed_event_ms:
                logger.warning(
                    "delayed interaction received: event_age_ms=%.1f message_id=%s %s",
                    age_ms,
                    message.message_id,
                    _event_context(event),
                )
            self._track_stale_interaction(event)
        if kind is not None:
            fields.append(f"delivery_kind={kind}")
        logger.info("delivery received: %s", " ".join(fields))

    def _track_stale_interaction(self, event: Event) -> None:
        """Warn when an OLDER interaction for the same card arrives later.

        The stale event is not dropped because a handler
        may contain business side effects.
        """
        message_name = getattr(getattr(event, "message", None), "name", None)
        if message_name is None or event.event_time is None:
            return
        latest = self._latest_event_times.get(message_name)
        if latest is not None and event.event_time < latest:
            logger.warning(
                "stale interaction detected: message=%s event_time=%s "
                "latest_seen_event_time=%s",
                message_name,
                event.event_time.isoformat(),
                latest.isoformat(),
            )
            return  # do NOT advance latest; do NOT drop the event
        self._latest_event_times[message_name] = event.event_time

    # ------------------------------------------------------------ parsing

    def _parse(self, message: Any) -> Event:
        raw = message.data
        if isinstance(raw, (bytes, bytearray)):
            raw = raw.decode()
        if not isinstance(raw, str):
            raise PubSubEnvelopeError("message data is not text")
        try:
            payload: object = json.loads(raw)
        except (json.JSONDecodeError, UnicodeDecodeError) as error:
            raise PubSubEnvelopeError("message data is not valid JSON") from error
        interaction: object = payload
        # Push-shaped topics carry the interaction base64-wrapped under
        # message.data — accept both wire shapes. An interaction's own
        # "message" object (text/sender/...) is NOT an envelope: only a
        # message mapping with a string "data" marks one.
        if isinstance(payload, Mapping):
            envelope_message = payload.get("message")
            if isinstance(envelope_message, Mapping) and isinstance(
                envelope_message.get("data"), str
            ):
                inner = decode_message_data(payload)
                if inner is not None:
                    interaction = inner
        if not isinstance(interaction, Mapping):
            raise PubSubEnvelopeError("interaction must be a JSON object")
        return parse_interaction(interaction)

    # ----------------------------------------------------------- answers

    async def _answer(self, event: Event, result: object) -> str | None:
        """Send the handler answer outbound; return the operation mode used."""
        if result is None:
            return None
        mode = _answer_mode(event, result)
        logger.debug(
            "answer_started: %s result_type=%s mode=%s",
            _event_context(event),
            type(result).__name__,
            mode,
        )
        if isinstance(result, (Dialog, ActionStatus)):
            raise CapabilityNotSupported(DIALOG_UNSUPPORTED_MESSAGE)
        if self._bot is None:
            logger.warning(
                "handler answer dropped: no Bot configured: event_type=%s "
                "result_type=%s",
                event.event_type,
                type(result).__name__,
            )
            return None
        space = event.space.name if event.space is not None else None
        if space is None:
            logger.warning(
                "handler answer dropped: event has no space: event_type=%s",
                event.event_type,
            )
            return None
        if isinstance(result, str):
            await self._send_text(self._bot, event, space, result)
        elif isinstance(result, Card):
            message_name = _clicked_message(event)
            if message_name is not None:
                await self._update_card(self._bot, event, message_name, result)
            else:
                await self._send_card(self._bot, event, space, result)
        else:
            logger.warning(
                "handler answer type unsupported in Pub/Sub: event_type=%s "
                "result_type=%s",
                event.event_type,
                type(result).__name__,
            )
            return None
        await _maybe_hook(self._observability_hooks, "after_outbound", event, mode)
        logger.debug("answer_completed: %s mode=%s", _event_context(event), mode)
        return mode

    async def _send_text(
        self, bot: _OutboundBot, event: Event, space: str, text: str
    ) -> None:
        thread = event.thread.name if event.thread is not None else None
        await _maybe_hook(
            self._observability_hooks, "before_outbound", event, "send_message"
        )
        try:
            await bot.app.messages.create(
                space,
                text=text,
                thread=ThreadRef(name=thread) if thread else None,
            )
        except Exception as exc:
            _log_outbound_failure(exc, "outbound_send_message", event)
            raise
        logger.info("text sent: space=%s %s", space, _event_context(event))

    async def _send_card(
        self, bot: _OutboundBot, event: Event, space: str, card: Card
    ) -> None:
        await _maybe_hook(
            self._observability_hooks, "before_outbound", event, "send_message"
        )
        try:
            await bot.app.messages.create(space, card=card)
        except Exception as exc:
            _log_outbound_failure(exc, "outbound_send_message", event)
            raise
        logger.info("card sent: space=%s %s", space, _event_context(event))

    async def _update_card(
        self, bot: _OutboundBot, event: Event, message_name: str, card: Card
    ) -> None:
        """Update the clicked message; updates of one message are serialized."""
        await self._update_locks.acquire(message_name)
        try:
            try:
                await bot.app.messages.update(message_name, card=card)
            except Exception as exc:
                _log_outbound_failure(exc, "outbound_update_message", event)
                raise
        finally:
            self._update_locks.release(message_name)
        logger.info("card updated: message=%s %s", message_name, _event_context(event))
