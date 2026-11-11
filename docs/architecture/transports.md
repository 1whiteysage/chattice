# Transports

Chattice separates interaction parsing, dispatch, and delivery. The concrete
entry points below are available in 0.4.0.

## HTTP interactions

`create_chat_router` from `chattice.integrations.fastapi` composes:

```text
POST -> IncomingRequest -> verifier -> HTTPInteractionAdapter.parse
     -> domain Event -> Dispatcher.feed_update -> response serialization
```

The framework-neutral HTTP types live in `chattice.transports.http`:

- `IncomingRequest` carries method, path, headers, body, and receipt time.
- `HTTPInteractionAdapter.parse(request)` decodes the body and calls the
  Google interaction parser.
- `InteractionResponse` records an explicit response and rejects a second one.
- `InteractionContext` carries request/response state, receipt time, deadline,
  and remaining time.

The endpoint injects `request`, `response`, `interaction`, and the event-derived
`capabilities` into the Dispatcher. A handler may return a response or call
`response.respond(...)`. Typed Cards, dialogs, App Home, and autocomplete
responses are validated for the current event before serialization.

`GoogleTokenVerifier` verifies inbound requests. HTTPS termination and request
size limits belong to the hosting server or reverse proxy. The FastAPI extra
provides an APIRouter containing a plain Starlette Route; it can also be
composed with `Starlette(routes=chat_router.routes)`.

## Pub/Sub push

`PubSubPushAdapter.parse_envelope(payload)` validates and decodes
`message.data`, then parses the Chat interaction. It preserves the complete
push envelope in `event.raw`.

`create_pubsub_router` verifies the push request and dispatches the event.
Handler return values do not become Chat replies; use an authenticated Bot
for outbound messages. Success returns 204. With idempotency storage,
completed deliveries return 204, active claims return 429, and storage or
handler failures return 500. See [Pub/Sub push](pubsub.md).

Workspace Events use `create_workspace_events_router`, their own envelope
parser, and `EventsDispatcher`. They are not routed as Chat interactions.

## Pub/Sub streaming pull

`Dispatcher.run_pubsub(...)` creates a `PubSubPullRunner` from
`chattice.transports.pubsub_runner`. It consumes a subscription until shutdown
or an unrecoverable subscriber failure and drains scheduled deliveries.

Pass `bot=bot` for outbound answers and `credentials_provider=...` or
`credentials=...` for subscriber authentication. Subscriber credentials are
independent of Bot credentials. When omitted, the Google subscriber uses
Application Default Credentials.

The pull runner maps supported text/Card returns to outbound calls through
the supplied Bot. Dialogs and App Home require HTTP; Pub/Sub has no synchronous
response capabilities. The application owns the Bot lifecycle, for example
with `async with Bot(...)`.

## Deadlines and duplicates

HTTP tracks a 30-second interaction deadline and logs late completion. It does
not automatically cancel the handler at that deadline. Long work needs an
application-owned background execution strategy and an appropriate response.

Pub/Sub is at-least-once delivery. Optional idempotency storage uses the
Pub/Sub message ID; it does not make arbitrary application side effects
exactly-once. Direct HTTP interactions have no generic built-in delivery-ID
deduplication. See [reliability](reliability.md).
