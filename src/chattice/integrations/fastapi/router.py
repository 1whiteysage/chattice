"""Starlette-based FastAPI integration for the HTTP interaction channel."""

from __future__ import annotations

import asyncio
import json
import logging
import time
from datetime import UTC, datetime

from fastapi import APIRouter
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from chattice.adapters.google_chat.exceptions import GoogleInteractionError
from chattice.capabilities import ResponseCapabilities
from chattice.dispatcher import Dispatcher
from chattice.events import Event
from chattice.idempotency import ClaimResult, IdempotencyStorage, new_owner
from chattice.transports.http import (
    SYNC_RESPONSE_DEADLINE,
    HTTPInteractionAdapter,
    IncomingRequest,
    IncomingRequestVerifier,
    InteractionContext,
    InteractionResponse,
    ResponseState,
    serialize_response,
)
from chattice.transports.http.errors import VerificationError
from chattice.transports.pubsub import (
    PubSubEnvelopeError,
    PubSubPushAdapter,
    PubSubPushVerifier,
)
from chattice.workspace_events import (
    EventsDispatcher,
    WorkspaceEventError,
    parse_workspace_envelope,
)

logger = logging.getLogger("chattice.http")
push_logger = logging.getLogger("chattice.push")


class _PushDeliveryCoordinator:
    """Shared private state machine for push endpoints.

    Verification, envelope metadata, idempotency transitions and failure
    mapping are IDENTICAL for classic Pub/Sub and Workspace push — the
    two routers would otherwise duplicate this state machine. Each adapter keeps
    its OWN parser and Dispatcher call; interaction and Workspace event
    semantics are deliberately NOT unified.
    """

    def __init__(self, idempotency_storage: IdempotencyStorage | None) -> None:
        self._idempotency = idempotency_storage

    @staticmethod
    def envelope_metadata(
        payload: dict[str, object],
    ) -> tuple[str | None, str | None]:
        """(message_id, subscription) from the shared wire envelope shape."""
        message = payload.get("message")
        message_id = None
        if isinstance(message, dict):
            candidate = message.get("messageId")
            if isinstance(candidate, str):
                message_id = candidate
        subscription = payload.get("subscription")
        return message_id, (subscription if isinstance(subscription, str) else None)

    async def claim(
        self, *, message_id: str | None, subscription: str | None, label: str
    ) -> tuple[Response | None, str | None, str | None]:
        """Claim or short-circuit: COMPLETED -> 204, ACTIVE -> 429, storage
        failure -> 500. Returns (response_or_None, dedupe_key, owner)."""
        if self._idempotency is None or message_id is None:
            return None, None, None
        # Namespaced key: Google message IDs are unique per TOPIC, so a
        # shared store needs the subscription in the key.
        namespace = subscription or "global"
        dedupe_key = f"{namespace}:{message_id}"
        owner = new_owner()
        try:
            result = await self._idempotency.claim(
                dedupe_key, owner=owner, lease_seconds=3600.0
            )
        except Exception as error:
            push_logger.error(
                "idempotency storage failed: key=%s error=%s",
                dedupe_key,
                type(error).__name__,
            )
            return Response(status_code=500), dedupe_key, owner
        if result is ClaimResult.COMPLETED:
            push_logger.info("duplicate %s messageId=%s skipped", label, message_id)
            return Response(status_code=204), dedupe_key, owner
        if result is ClaimResult.ACTIVE:
            # Another owner is still processing: 429 makes Pub/Sub
            # redeliver later — never ack incomplete work.
            push_logger.info(
                "%s messageId=%s still processing elsewhere", label, message_id
            )
            return Response(status_code=429), dedupe_key, owner
        return None, dedupe_key, owner

    async def release(
        self,
        *,
        message_id: str | None,
        dedupe_key: str | None,
        owner: str | None,
    ) -> None:
        """Owner-checked release on dispatch failure: only OUR claim is
        dropped, so a retry re-dispatches instead of losing the work."""
        if self._idempotency is None or not dedupe_key or not owner:
            return
        try:
            await self._idempotency.release(dedupe_key, owner=owner)
        except Exception as error:
            push_logger.error(
                "idempotency release failed: messageId=%s error=%s",
                message_id,
                type(error).__name__,
            )

    async def complete(
        self,
        *,
        message_id: str | None,
        dedupe_key: str | None,
        owner: str | None,
    ) -> None:
        """Mark the delivery completed (log-only on failure)."""
        if self._idempotency is None or not dedupe_key or not owner:
            return
        try:
            await self._idempotency.complete(dedupe_key, owner=owner)
        except Exception as error:
            push_logger.error(
                "idempotency complete failed: messageId=%s error=%s",
                message_id,
                type(error).__name__,
            )


def _serialize(
    payload: object, *, event: Event, addon_action_url: str | None = None
) -> Response:
    body = serialize_response(payload, event=event, addon_action_url=addon_action_url)
    if body is None:
        return Response(status_code=200)
    try:
        encoded = json.dumps(
            body, allow_nan=False, ensure_ascii=False, separators=(",", ":")
        )
    except (TypeError, ValueError) as error:
        raise TypeError(
            f"Unsupported synchronous response payload {type(payload).__name__}"
        ) from error
    return Response(content=encoded, media_type="application/json")


def create_chat_router(
    dispatcher: Dispatcher,
    verifier: IncomingRequestVerifier,
    *,
    path: str = "/",
    addon_action_url: str | None = None,
) -> APIRouter:
    """Build a POST route wiring Google Chat interactions into the dispatcher.

    Works under FastAPI via app.include_router(...) and under plain Starlette
    via Starlette(routes=chat_router.routes).

    The route accepts both payload families (Chat API interaction events
    and Google Workspace add-on event objects) and answers each in its
    own family. For an HTTP add-on pass ``addon_action_url`` — the public
    HTTPS URL of this route — so card actions in responses call it back.
    """
    if addon_action_url is not None and not addon_action_url.startswith("https://"):
        raise ValueError(
            "addon_action_url must be the public HTTPS URL of this route; "
            f"got {addon_action_url!r}"
        )
    adapter = HTTPInteractionAdapter()
    router = APIRouter()

    async def chat_endpoint(request: Request) -> Response:
        incoming = IncomingRequest(
            method=request.method,
            path=request.url.path,
            headers=dict(request.headers),
        )
        try:
            await asyncio.to_thread(verifier.verify, incoming)
        except VerificationError as error:
            logger.info(
                "verification failed: error=%s path=%s",
                type(error).__name__,
                incoming.path,
            )
            return Response(status_code=401)
        incoming = IncomingRequest(
            method=request.method,
            path=request.url.path,
            body=await request.body(),
            headers=incoming.headers,
            received_at=incoming.received_at,
        )
        try:
            event: Event = adapter.parse(incoming)
        except GoogleInteractionError as error:
            # The GoogleInteractionError hierarchy (Invalid/Unsupported/Conflicting)
            # intentionally collapses to 400: these payloads cannot be interpreted.
            # Unknown-but-valid future event types do NOT reach this path — they
            # become UnknownEvent and are dispatched normally (200 empty).
            # error CLASS only — pydantic validation messages embed
            # input_value and would leak attacker-controlled form data.
            logger.info(
                "invalid interaction payload: error=%s path=%s",
                type(error).__name__,
                incoming.path,
            )
            return JSONResponse(
                {"error": "invalid_interaction_payload"}, status_code=400
            )
        response = InteractionResponse()
        context = InteractionContext(
            request=incoming,
            response=response,
            received_at=incoming.received_at,
            deadline_at=incoming.received_at + SYNC_RESPONSE_DEADLINE,
        )
        started = time.monotonic()
        # The webhook surface is auth-less: handlers get exactly the
        # incoming/sync-response capability set (SYNC_RESPONSE + DIALOGS).
        capabilities = ResponseCapabilities.resolve(transport="http", event=event)
        try:
            result = await dispatcher.feed_update(
                event,
                request=incoming,
                response=response,
                interaction=context,
                capabilities=capabilities,
            )
        except Exception as error:
            # Exception CLASS only — never the message: handler messages may
            # contain secrets such as tokens or form values.
            logger.error(
                "handler failed: event_type=%s path=%s error=%s",
                event.event_type,
                incoming.path,
                type(error).__name__,
            )
            return Response(status_code=500)
        latency_ms = (time.monotonic() - started) * 1000
        if datetime.now(UTC) > context.deadline_at:
            logger.warning(
                "sync response deadline exceeded: event_type=%s latency_ms=%.1f",
                event.event_type,
                latency_ms,
            )
        logger.info(
            "interaction handled: event_type=%s latency_ms=%.1f",
            event.event_type,
            latency_ms,
        )
        payload = (
            response.payload if response.state is ResponseState.RESPONDED else result
        )
        try:
            return _serialize(payload, event=event, addon_action_url=addon_action_url)
        except TypeError as error:
            logger.error(
                "response serialization failed: event_type=%s error=%s",
                event.event_type,
                type(error).__name__,
            )
            return Response(status_code=500)

    # Plain starlette Route (not APIRoute) keeps the router usable under
    # Starlette(routes=chat_router.routes); FastAPI's include_router supports
    # mixed plain Routes and generates no request schema for the webhook.
    router.add_route(path, chat_endpoint, methods=["POST"])
    return router


def create_pubsub_router(
    dispatcher: Dispatcher,
    *,
    path: str = "/pubsub",
    idempotency_storage: IdempotencyStorage | None = None,
    verifier: PubSubPushVerifier | None = None,
    allow_unverified: bool = False,
) -> APIRouter:
    """Push endpoint for Pub/Sub-delivered interactions (ack-only, 204).

    Secure by default: pass ``verifier=`` (authenticated push) or an
    explicit ``allow_unverified=True`` (test/local environments). Without
    either the router refuses to be created.
    """
    if verifier is None and not allow_unverified:
        raise ValueError(
            "push endpoints require verification: pass verifier= "
            "(authenticated push) or allow_unverified=True"
        )
    adapter = PubSubPushAdapter()
    router = APIRouter()
    delivery = _PushDeliveryCoordinator(idempotency_storage)

    async def pubsub_endpoint(request: Request) -> Response:
        if verifier is not None:
            try:
                await asyncio.to_thread(
                    verifier.verify,
                    IncomingRequest(
                        method=request.method,
                        path=request.url.path,
                        headers=dict(request.headers),
                    ),
                )
            except VerificationError as error:
                push_logger.info(
                    "push verification failed: error=%s", type(error).__name__
                )
                return Response(status_code=401)
        try:
            payload = json.loads(await request.body())
        except (json.JSONDecodeError, UnicodeDecodeError) as error:
            push_logger.info(
                "pubsub payload is not JSON: error=%s path=%s",
                type(error).__name__,
                request.url.path,
            )
            return Response(status_code=400)
        try:
            event = adapter.parse_envelope(payload)
        except (PubSubEnvelopeError, GoogleInteractionError) as error:
            push_logger.info(
                "invalid pubsub envelope: error=%s path=%s",
                type(error).__name__,
                request.url.path,
            )
            return Response(status_code=400)
        message_id, subscription = delivery.envelope_metadata(payload)
        short, dedupe_key, owner = await delivery.claim(
            message_id=message_id, subscription=subscription, label="pubsub"
        )
        if short is not None:
            return short
        # The push surface is ack-only: the response-channel capability
        # set is empty (no sync channel for handlers).
        capabilities = ResponseCapabilities.resolve(transport="pubsub", event=event)
        try:
            await dispatcher.feed_update(event, capabilities=capabilities)
        except Exception as error:
            push_logger.error(
                "pubsub handler failed: event_type=%s error=%s",
                event.event_type,
                type(error).__name__,
            )
            await delivery.release(
                message_id=message_id, dedupe_key=dedupe_key, owner=owner
            )
            return Response(status_code=500)
        await delivery.complete(
            message_id=message_id, dedupe_key=dedupe_key, owner=owner
        )
        return Response(status_code=204)

    router.add_route(path, pubsub_endpoint, methods=["POST"])
    return router


def create_workspace_events_router(
    dispatcher: EventsDispatcher,
    *,
    path: str = "/workspace-events",
    idempotency_storage: IdempotencyStorage | None = None,
    verifier: PubSubPushVerifier | None = None,
    allow_unverified: bool = False,
) -> APIRouter:
    """Push endpoint for Workspace Events (ack-only, 204).

    Google delivers Workspace Events exclusively as Pub/Sub push messages:
    the CloudEvents context attributes travel in ``message.attributes``
    (``ce-*`` keys) and ``message.data`` (base64) holds the event resource
    data. A structured CloudEvent POSTed directly is NOT a supported
    delivery mode and is rejected.

    ``idempotency_storage`` dedupes redeliveries by the Pub/Sub message id
    with the same claim/complete/release semantics as the classic push
    router: a failed dispatch releases the claim so a redelivery
    re-dispatches.

    Secure by default: pass ``verifier=`` or an explicit
    ``allow_unverified=True``.
    """
    if verifier is None and not allow_unverified:
        raise ValueError(
            "push endpoints require verification: pass verifier= "
            "(authenticated push) or allow_unverified=True"
        )
    router = APIRouter()
    delivery = _PushDeliveryCoordinator(idempotency_storage)

    async def workspace_endpoint(request: Request) -> Response:
        if verifier is not None:
            try:
                await asyncio.to_thread(
                    verifier.verify,
                    IncomingRequest(
                        method=request.method,
                        path=request.url.path,
                        headers=dict(request.headers),
                    ),
                )
            except VerificationError as error:
                push_logger.info(
                    "push verification failed: error=%s", type(error).__name__
                )
                return Response(status_code=401)
        try:
            payload = json.loads(await request.body())
        except (json.JSONDecodeError, UnicodeDecodeError) as error:
            push_logger.info(
                "workspace event payload is not JSON: error=%s path=%s",
                type(error).__name__,
                request.url.path,
            )
            return Response(status_code=400)
        if not isinstance(payload, dict):
            push_logger.info("workspace event payload must be a JSON object")
            return Response(status_code=400)
        try:
            # Parse BEFORE claiming: an invalid envelope must never be
            # recorded as a completed delivery (it would be swallowed as a
            # duplicate on retry).
            event = parse_workspace_envelope(payload)
        except WorkspaceEventError as error:
            push_logger.info(
                "invalid workspace push envelope: error=%s path=%s",
                type(error).__name__,
                request.url.path,
            )
            return Response(status_code=400)
        message_id, subscription = delivery.envelope_metadata(payload)
        short, dedupe_key, owner = await delivery.claim(
            message_id=message_id, subscription=subscription, label="workspace"
        )
        if short is not None:
            return short
        try:
            await dispatcher.feed_event(event)
        except Exception as error:
            push_logger.error(
                "workspace handler failed: type=%s error=%s",
                event.cloud_type,
                type(error).__name__,
            )
            await delivery.release(
                message_id=message_id, dedupe_key=dedupe_key, owner=owner
            )
            return Response(status_code=500)
        await delivery.complete(
            message_id=message_id, dedupe_key=dedupe_key, owner=owner
        )
        return Response(status_code=204)

    router.add_route(path, workspace_endpoint, methods=["POST"])
    return router


__all__ = [
    "create_chat_router",
    "create_pubsub_router",
    "create_workspace_events_router",
]
