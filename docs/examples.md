# Executable examples

The flat examples are applications that use the operator's credentials.
`examples/docs/from_zero.py` is a separate credential-free tour using MockBot.
CI imports the applications and exercises their startup, handlers, and shutdown
with test substitutes; it does not contact Google. The examples use public
Chattice 0.4.0 entry points.

| Task | Example |
| --- | --- |
| Full documented tour (cards, forms, dialogs, commands, Workspace Events) | `examples/docs/from_zero.py` |
| Echo over Pub/Sub streaming pull (aiogram `echo_bot`) | `examples/echo_bot.py` |
| Echo behind an HTTP webhook (aiogram `echo_bot_webhook`) | `examples/echo_bot_webhook.py` |
| Error handling (aiogram `error_handling`) | `examples/error_handling.py` |
| FSM (aiogram `finite_state_machine`) | `examples/finite_state_machine.py` |
| Own async filters (aiogram `own_filter`) | `examples/own_filter.py` |
| Magic-filter routing (aiogram `specify_updates`) | `examples/specify_updates.py` |
| Filter → handler context injection (aiogram `context_addition_from_filter`) | `examples/context_addition_from_filter.py` |
| Outbound Bot without a dispatcher (aiogram `without_dispatcher`) | `examples/without_dispatcher.py` |
| Local files & media (copy-paste recipes) | [`docs/guides/files-media.md`](guides/files-media.md), [Cookbook](cookbook/recipes.md) |
| Regex routing (copy-paste recipes) | [`docs/guides/routing-state.md`](guides/routing-state.md) |

Media upload needs USER authentication, so media flows ship as
copy-paste recipes with MockBot exercisable in unit tests instead of a
credential-free executable.

The documented credential-free tour (synthetic payloads through the real
parser and dispatcher):

```bash
python examples/docs/from_zero.py
```

For an application using an installed package, copy the relevant example into
your project, point it at YOUR credentials through the documented
environment variables, and run. The example's imports are
all public API.

Poll, approval, incident, and AI assistant remain application recipes. They
are not framework primitives.
