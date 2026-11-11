# Installation

Chattice requires Python 3.11 or newer.

## Create a project

Option 1 — the standard path with `pip`:

```bash
mkdir hello-chattice
cd hello-chattice
python3.11 -m venv .venv
. .venv/bin/activate
python -m pip install "chattice[fastapi]" uvicorn
```

Option 2 — with `uv` (optional convenience):

```bash
mkdir hello-chattice
cd hello-chattice
uv init --python 3.11
uv add "chattice[fastapi]" uvicorn
```

Optional extras are independent:

| Extra | Use it for |
| --- | --- |
| `fastapi` | HTTP, Pub/Sub push, and Workspace Events push endpoints |
| `pubsub` | Pub/Sub streaming-pull ingress |
| `redis` | Redis FSM and idempotency storage |
| `gemini` | Experimental Google Gen AI adapter |
| `media` | Native Google Chat attachment upload/download |
| `gcs` | Publish local Card images through Google Cloud Storage |

Do not install the `gemini` extra for a normal Chat app. AI support is outside
stable core.

## Verify the environment

```bash
python -c "import chattice; print(chattice.__version__)"
```

The output for this documentation line is `0.4.0`.

Next: [5-minute Quickstart](quickstart.md).
