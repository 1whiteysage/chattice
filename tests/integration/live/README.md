# Live integration tests

Tests in this directory talk to **real Google Chat / Google Workspace
infrastructure**. They are skipped by default and run only when you explicitly
opt in with real credentials.

**Current state: executable when enabled.** Network tests
(send/update/delete, echo round-trip) call the real Chat API and skip
honestly without `CHATTICE_GOOGLE_CREDENTIALS` + `CHATTICE_GOOGLE_SPACE`.
Contract tests (card-button round-trip, command payloads, Workspace Pub/Sub
replay) execute in the same run without network access. No test raises
`NotImplementedError`.

## 1. GCP project

Create a Google Cloud project (or use an existing one) and enable the
**Google Chat API**:

- [Google Cloud Console](https://console.cloud.google.com) → select the project →
  **APIs & Services → Library** → search "Google Chat API" → **Enable**.

## 2. Service account

Create a service account with the Chat-scope delegation:

- **APIs & Services → Credentials → Create credentials → Service account**.
- Grant it the `chat.bot` scope — for service accounts this is configured in
  the Chat app itself (see step 4), but the account must exist and have a key:
- **Credentials → (the account) → Keys → Add key → Create new key → JSON**.
  Download the JSON key file; it is referenced by
  `CHATTICE_GOOGLE_CREDENTIALS`.

## 3. Chat app and test space

- In the [Google Chat API configuration](https://console.cloud.google.com/apis/api/chat.googleapis.com/configuration)
  of the project, create a **Google Chat app** (name, avatar, description).
- **Membership requirement:** the Chat app must be added to the test space,
  otherwise API calls fail with HTTP 403 «You are not permitted to use this
  app». Create a space (e.g. a small group space or 1:1 space with the app)
  and add the app as a member. Re-adding after any credential/app change is
  often required.
- Note the space id (it is used in the test bodies once implemented).

## 4. Chat app configuration

- **Connection settings → App status → Live** (the app must not be in test
  mode for real traffic).
- **Connection settings → App URL → HTTP endpoint URL**: the publicly
  reachable URL where the bot's FastAPI app is deployed
  (e.g. `https://your-host.example/chattice/webhook`). Google verifies the
  endpoint; requests without a valid `Authorization` header are rejected.
- **App Home** (if App Home flows are tested): set the **App Home URL** to the
  home-card endpoint.

## 5. Environment variable

```bash
export CHATTICE_GOOGLE_CREDENTIALS=/path/to/service-account.json
```

The variable must point at the downloaded JSON key file. All tests in this
directory skip (with a clear message) when it is unset.

## 6. Run

```bash
CHATTICE_GOOGLE_CREDENTIALS=/path/to/service-account.json \
  pytest tests/integration/live -m google_live
```

Without credentials the same command reports the network tests as skipped
— that is the expected, honest behavior:

```bash
uv run pytest tests/integration/live -q
```

In CI the live directory always skips (the env var is not set), so the default
`uv run pytest -q` stays green.

## 7. Developer Preview tests

`chattice.experimental` (message streaming, thread sessions) calls Google
methods that are in neither the Python SDK nor the public discovery document.
These live tests are the only check that the framework still matches Google:

```bash
CHATTICE_GOOGLE_CREDENTIALS=/path/to/service-account.json \
CHATTICE_GOOGLE_SPACE=spaces/AAA \
CHATTICE_GOOGLE_PREVIEW=1 \
CHATTICE_GOOGLE_DM_SPACE=spaces/BBB \
  uv run pytest tests/integration/live -m google_live -rs
```

- `CHATTICE_GOOGLE_PREVIEW=1` — the Cloud project is enrolled in the
  [Google Workspace Developer Preview Program](https://developers.google.com/workspace/preview).
- `CHATTICE_GOOGLE_SPACE` must be a threaded space for the streaming tests.
- `CHATTICE_GOOGLE_DM_SPACE` — a 1:1 direct message with the app, for the
  thread sessions test; without it that one test skips.

The streaming tests anchor the stream to a message the app itself creates and
delete every message they leave behind.

## 8. Run from GitHub Actions

`.github/workflows/live.yml` runs this directory on demand
(**Actions → Live Google smoke → Run workflow**). It needs an environment
named `google-live` with:

| Kind | Name | Value |
| --- | --- | --- |
| Secret | `CHATTICE_GOOGLE_CREDENTIALS_JSON` | the service-account key file content |
| Variable | `CHATTICE_GOOGLE_SPACE` | `spaces/...` test space |
| Variable | `CHATTICE_GOOGLE_DM_SPACE` | optional, for thread sessions |

The workflow never runs automatically and fails if the network tests skip, so
a green run means Google was actually called.
