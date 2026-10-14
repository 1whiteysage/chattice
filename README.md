<img src="https://raw.githubusercontent.com/1whiteysage/chattice/main/docs/assets/brand/chattice-logo.png"
     alt="Chattice" width="320" />

# Chattice

Async, typed event framework for Google Chat apps — aiogram-quality DX, Google-native semantics.

[![Python](https://img.shields.io/badge/python-3.11%20%7C%203.12%20%7C%203.13-blue)](https://pypi.org/project/chattice/)
[![License](https://img.shields.io/badge/license-MIT-green)](LICENSE)
[![Status](https://img.shields.io/badge/status-pre--1.0-orange)](#status)
[![Discussions](https://img.shields.io/badge/discussions-questions%20%26%20help-blue)](https://github.com/1whiteysage/chattice/discussions)

```python
from chattice import Dispatcher, F, Router
from chattice.events import MessageEvent

router = Router()


@router.message(F.text == "ping")
async def ping(message: MessageEvent) -> str:
    return "pong"  # HTTP response; no outbound credentials, 30 s deadline


dispatcher = Dispatcher()
dispatcher.include_router(router)
```

## What this is

- **Google Chat-native.** Space, Thread, Message, Command, Action, Card,
  Dialog, App Home, Workspace Events are first-class typed objects. No
  Telegram concepts leak into the domain model.
- **aiogram ergonomics.** Routers, magic filters (`F`), middleware,
  dependency injection, FSM — the DX you know, without Telegram
  semantics.
- **Explicit response model.** A handler RETURN is the synchronous
  interaction response (30 s deadline); outbound `Bot` calls are
  separate authenticated operations. Contextual `message.reply()` /
  `thread.send()` / `space.send()` methods are zero-fetch adapters over
  that same Bot, never a hidden second channel.
- **Secure by default.** Incoming verification is fail-closed, push
  endpoints require a verifier, outbound privacy gates (private
  messages, notifications, preview features) fail closed before any
  network call.
- **Core is small.** Core abstracts Google Chat platform primitives and
  technical boilerplate ONLY. Business scenarios (polls, approvals,
  tickets) are assembled from the primitives in your
  application code — never added to core.
- **Curated outbound facade.** An operation registry is the single
  source of outbound auth truth; identity-bound resource clients
  (`bot.app.*` / `bot.user.*` for spaces, messages, memberships,
  reactions, and per-user state) and one executor path make every
  Google call explicit about who is calling.
- **Explicit identity.** APP and USER are always chosen by the caller
  (`bot.raw.app()` / `bot.raw.user()`); the framework never switches
  silently. Direct messages are first-class:
  `bot.user.spaces.get_or_setup_direct_message(...)` returns the
  official `Space` with its clickable `space_uri`.
- **Diagnosable in production.** Structured lifecycle stages
  (`handler_started` before invocation), stage-tagged error logs,
  Pub/Sub delivery identity/age, per-card update serialization,
  configurable `RuntimeDiagnostics` thresholds, and CI-verified
  operation registry against the Google discovery document. DEBUG can include
  exception text in tracebacks; see the [logging guidance](docs/guides/debugging.md).

## What this is not

- **Not a Telegram framework.** No `chat_id`, no `CallbackQuery`, no
  `Update` hierarchy, no Telegram-style long polling (see the
  [aiogram comparison](https://1whiteysage.github.io/chattice/aiogram-comparison/)).
- **Not a Google product.** Independent open-source project, not
  endorsed by Google.

## Two ways to run

Chattice has two startup models (see the
[aiogram side-by-side](docs/aiogram-comparison.md)):

```python
# HTTP — Google calls your HTTPS endpoint; the handler RETURN is the
# synchronous response (Dialogs and App Home work here).
app.include_router(create_chat_router(dispatcher, GoogleTokenVerifier(audience=...)))
# python -m uvicorn app:app

# Pub/Sub streaming pull — a persistent subscriber process, visually
# like aiogram's start_polling, but it is NOT Telegram polling.
# No domain/TLS needed; no Dialogs, no App Home — answers go outbound
# through the authenticated Bot.
await dispatcher.run_pubsub(
    subscription, bot=bot, credentials_provider=pull_credentials
)
# python app.py
```

## Capabilities

| Area | Support |
| --- | --- |
| Events | MESSAGE, CARD_CLICKED, APP_COMMAND (slash/quick/message actions), ADDED/REMOVED_FROM_SPACE, APP_HOME, SUBMIT_FORM, WIDGET_UPDATED |
| Routing | Routers, observer-wide filters, magic filters, middleware, DI |
| Cards | Typed facades, public/non-sensitive PNG/JPEG publication through an optional AssetPublisher, sync updates |
| Memberships | APP-auth add/get/list/remove for human users; caller-member Space listing |
| Dialogs | OPEN_DIALOG, submit/cancel observers, action status; capability-gated per transport |
| FSM | State/StatesGroup, Memory + Redis record storage (compare-and-set) |
| Ingress | HTTP (verified), Pub/Sub push (verified), Pub/Sub streaming pull, Workspace Events CloudEvents |
| Media | Local-file attachments sent with USER auth end to end (`media.upload` → `messages.create`, sender = HUMAN); download USER/APP; metadata APP; 200 MB local preflight |
| Auth | App (service account), user (OAuth refresh), incoming verification |
| Diagnostics | DEBUG routing diagnostics, structured Pub/Sub failure logs, typed Chat API errors |
| Testing | MockBot, EventFactory, assertions, fake transport |

## Install

Python 3.11+ (3.11–3.13 tested). MIT-licensed.

```bash
pip install "chattice[fastapi,pubsub,redis]"  # HTTP, streaming pull, Redis

# or pick only what you need:
#   pip install chattice            core
#   pip install "chattice[fastapi]" FastAPI integration
#   pip install "chattice[redis]"   Redis FSM/idempotency storage
#   pip install "chattice[pubsub]"  Pub/Sub streaming pull
#   pip install "chattice[media]"   Media/attachment uploads (Google API client)
#   pip install "chattice[gcs]"     Local Card image publication through GCS
#   pip install "chattice[gemini]"  Experimental Gemini agent bridge

# using uv
uv add "chattice[fastapi,pubsub,redis]"
```

## Quickstart

1. Parse a documented interaction payload:

```python
from chattice.adapters.google_chat import parse_interaction

event = parse_interaction(payload)
result = await dispatcher.feed_update(event)
```

2. Serve HTTP interactions (FastAPI):

```python
from fastapi import FastAPI
from chattice.integrations.fastapi import create_chat_router
from chattice.transports.http import GoogleTokenVerifier

app = FastAPI()
app.include_router(create_chat_router(dispatcher, GoogleTokenVerifier(audience="...")))
```

3. Send messages:

```python
from chattice.client import Bot

bot = Bot(credentials=...)
await bot.app.messages.create("spaces/AAA", text="hello")
```

Inside an interaction handler, configure the same Bot once and use the known
Google context without extra fetches:

```python
dispatcher = Dispatcher(bot=bot)


@router.message()
async def reply(message: MessageEvent) -> None:
    await message.reply("hello in this thread")
```

## Docs

Start with [Installation](https://1whiteysage.github.io/chattice/getting-started/installation/), the
[5-minute Quickstart](https://1whiteysage.github.io/chattice/getting-started/quickstart/), and the
[Space → Thread → Message mental model](https://1whiteysage.github.io/chattice/concepts/mental-model/). The
[public API reference](https://1whiteysage.github.io/chattice/public-api/), [Google mapping](https://1whiteysage.github.io/chattice/reference/google-api-mapping/),
the [debugging guide](https://1whiteysage.github.io/chattice/guides/debugging/), and
[aiogram comparison](https://1whiteysage.github.io/chattice/aiogram-comparison/) are linked from the docs site.
Runnable examples live in [`examples/`](https://github.com/1whiteysage/chattice/tree/main/examples).

## Status

Pre-1.0 **public release** (current version 0.3.5) — see
[CHANGELOG](CHANGELOG.md). The documented public
surface is the compatibility baseline: patch releases preserve it; pre-1.0
incompatible changes require a minor-version bump and upgrade notes. `chattice.experimental`
has no compatibility promise. `bot.raw.app()` / `bot.raw.user()` and raw event payloads
follow Google's SDK and wire schema rather than the stable facade
promise. **Not an official Google product** — independent open-source
software, not endorsed by Google. MIT License, see [LICENSE](https://github.com/1whiteysage/chattice/blob/main/LICENSE).
