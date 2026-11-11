# Third-party notices

Chattice is licensed under the MIT License. This file lists the direct
third-party dependencies of the project and their licenses, based on the
locked dependency inventory. It is an engineering compliance record, not legal
advice. Versions are the locked versions in `uv.lock`.

All declared direct dependencies carry permissive licenses compatible
with the MIT License (Apache-2.0, MIT, BSD-2/3-Clause, ISC). No
GPL/AGPL/SSPL dependency is declared.

## Runtime dependencies

| Package | Version | License |
| --- | --- | --- |
| [google-apps-chat](https://github.com/googleapis/google-cloud-python/tree/main/packages/google-apps-chat) | 0.10.9 | Apache-2.0 |
| [google-auth](https://github.com/googleapis/google-auth-library-python) | 2.62.2 | Apache-2.0 |
| [pydantic](https://github.com/pydantic/pydantic) | 2.14.3 | MIT |

## Optional extras

| Package | Version | License | Extra |
| --- | --- | --- | --- |
| [fastapi](https://github.com/fastapi/fastapi) | 0.162.2 | MIT | `fastapi` |
| [redis](https://github.com/redis/redis-py) | 8.1.0 | MIT | `redis` |
| [google-genai](https://github.com/googleapis/python-genai) | 3.1.0 | Apache-2.0 | `gemini` |
| [google-cloud-pubsub](https://github.com/googleapis/python-pubsub) | 2.43.0 | Apache-2.0 | `pubsub` |
| [google-api-python-client](https://github.com/googleapis/google-api-python-client) | 2.199.0 | Apache-2.0 | `media` |
| [google-cloud-storage](https://github.com/googleapis/python-storage) | 3.13.1 | Apache-2.0 | `gcs` |

## Development, documentation and build dependencies

| Package | Version | License |
| --- | --- | --- |
| [cryptography](https://github.com/pyca/cryptography) | 50.0.2 | Apache-2.0 OR BSD-3-Clause |
| [fakeredis](https://github.com/cunla/fakeredis-py) | 2.40.0 | BSD-3-Clause |
| [httpx](https://github.com/encode/httpx) | 0.28.1 | BSD-3-Clause |
| [mkdocs](https://github.com/mkdocs/mkdocs) | 1.6.1 | BSD-2-Clause |
| [mkdocs-material](https://github.com/squidfunk/mkdocs-material) | 9.8.1 | MIT |
| [mkdocstrings[python]](https://github.com/mkdocstrings/mkdocstrings) | 1.0.6 | ISC |
| [mypy](https://github.com/python/mypy) | 2.4.1 | MIT (with identified PSF-licensed portions) |
| [pyjwt](https://github.com/jpadilla/pyjwt) | 2.15.1 | MIT |
| [pytest](https://github.com/pytest-dev/pytest) | 9.2.0 | MIT |
| [pytest-asyncio](https://github.com/pytest-dev/pytest-asyncio) | 1.4.1.post1 | Apache-2.0 |
| [pytest-cov](https://github.com/pytest-dev/pytest-cov) | 7.1.0 | MIT |
| [ruff](https://github.com/astral-sh/ruff) | 0.17.4 | MIT |
| [uvicorn](https://github.com/encode/uvicorn) | 0.54.0 | BSD-3-Clause |
| [hatchling](https://github.com/pypa/hatch) | >=1.27 (build backend) | MIT |

## What is and is not distributed

The wheel packages `src/chattice` and project licensing/typing
metadata; it does NOT embed dependency source trees. Declaring
dependencies in wheel metadata causes installers to fetch their
independently licensed distributions; it does not relicense or copy
them into Chattice.

An exact-artifact SBOM for the locked dependency set is generated from
`uv.lock` with `scripts/gen_sbom.py` (SPDX 2.3 JSON, written to
`docs/release/`). Run it after every lock change and commit the result.

## Chattice license

MIT License — see [LICENSE](LICENSE). This project is independent
open-source software: not official Google software and not endorsed by
Google.
