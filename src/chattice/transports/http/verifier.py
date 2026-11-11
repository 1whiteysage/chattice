"""Incoming request verification per the official Chat documentation.

Chat apps built as Google Workspace add-ons use ``AddOnTokenVerifier``.
For Chat API interaction events ``GoogleTokenVerifier`` supports two
audience strategies (documented Google modes):

- ENDPOINT-URL audience (audience starts with https://): Google sends a
  Google-signed OIDC ID token. Verified with
  google.oauth2.id_token.verify_oauth2_token (standard Google OAuth2
  certificates, issuer validation built in); the identity must be the
  Google Chat service (email == chat@system.gserviceaccount.com,
  email_verified true). NEVER pass certs_url here — an explicit None
  makes google-auth fetch 'https://None'.

- PROJECT-NUMBER audience: a self-signed JWT by the Chat service
  account, verified against the Chat service-account certificate
  endpoint with issuer checks.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Protocol

from google.auth import exceptions as google_auth_exceptions
from google.auth.transport import requests as google_requests
from google.oauth2.id_token import verify_oauth2_token, verify_token

from .errors import VerificationError
from .request import IncomingRequest

_CHAT_ISSUER = "chat@system.gserviceaccount.com"
_CHAT_CERTS_URL = (
    "https://www.googleapis.com/service_accounts/v1/metadata/x509/" + _CHAT_ISSUER
)
_GOOGLE_ACCOUNT_ISSUERS = ("accounts.google.com", "https://accounts.google.com")


class IncomingRequestVerifier(Protocol):
    """Contract: prove that an inbound request genuinely came from Google Chat."""

    def verify(self, request: IncomingRequest) -> None:
        """Raise VerificationError when the request cannot be verified."""
        ...


def extract_bearer(request: IncomingRequest) -> str:
    """Extract a bearer token from the Authorization header."""
    header = request.header("Authorization")
    if header is None:
        raise VerificationError("Missing Authorization header")
    scheme, _, token = header.partition(" ")
    if scheme.lower() != "bearer" or not token.strip():
        raise VerificationError("Malformed Authorization header")
    token = token.strip()
    if any(char.isspace() for char in token):
        raise VerificationError("Malformed Authorization header")
    return token


def _validate_issuer(claims: Mapping[str, object]) -> None:
    issuer = claims.get("iss")
    if issuer == _CHAT_ISSUER:
        # Project-number audience strategy: self-signed JWT by the Chat service account.
        return
    if issuer in _GOOGLE_ACCOUNT_ISSUERS and claims.get("email") == _CHAT_ISSUER:
        # Endpoint-URL audience strategy: Google OIDC ID token of the service account.
        return
    raise VerificationError("Invalid token issuer")


class GoogleTokenVerifier:
    """Verify Chat bearer tokens using google-auth and the documented flows.

    One audience string supports both documented Authentication Audience
    strategies: the HTTP endpoint URL (OIDC ID token via
    verify_oauth2_token) or the project number (self-signed JWT via the
    Chat service-account certificates). Signature, exp, aud, and
    kid-based certificate selection are handled by google-auth; the
    Google Chat identity (email) and issuer are checked explicitly per
    strategy (the official samples do the same). Fail-closed: any
    verification failure answers VerificationError, never a bypass.
    """

    def __init__(
        self,
        *,
        audience: str,
        request: google_requests.Request | None = None,
        clock_skew_in_seconds: int = 10,
    ) -> None:
        self._audience = audience
        self._request = request if request is not None else google_requests.Request()
        self._clock_skew_in_seconds = clock_skew_in_seconds

    def verify(self, request: IncomingRequest) -> None:
        token = extract_bearer(request)
        try:
            if self._audience.startswith("https://"):
                # Endpoint-URL audience: the OFFICIAL Google Chat OIDC
                # flow. verify_oauth2_token checks the signature and the
                # audience against the standard Google OAuth2
                # certificates and validates the issuer itself — never
                # pass a certs_url here (an explicit None would make
                # google-auth fetch 'https://None').
                claims = verify_oauth2_token(  # type: ignore[no-untyped-call]
                    token, self._request, audience=self._audience
                )
                # Identity check: only the Google Chat service may speak
                # for this endpoint (documented expected identity).
                if claims.get("email") != _CHAT_ISSUER:
                    raise VerificationError(
                        "Token identity is not the Google Chat service"
                    )
                if claims.get("email_verified") is not True:
                    raise VerificationError("Token email is not verified")
            else:
                # Project-number audience: a self-signed JWT by the Chat
                # service account, verified against the Chat
                # service-account certificate endpoint.
                claims = verify_token(
                    token,
                    request=self._request,
                    audience=self._audience,
                    certs_url=_CHAT_CERTS_URL,
                    clock_skew_in_seconds=self._clock_skew_in_seconds,
                )
                _validate_issuer(claims)
        except VerificationError:
            raise
        except google_auth_exceptions.TransportError as error:
            # Fail-closed: an unreachable certificate endpoint is a
            # verification failure, never a bypass.
            raise VerificationError(
                "Cannot reach Google Chat issuer certificates"
            ) from error
        except (ValueError, google_auth_exceptions.GoogleAuthError) as error:
            raise VerificationError("Invalid bearer token") from error


class AddOnTokenVerifier:
    """Verify requests sent to a Chat app built as a Workspace add-on.

    Google signs add-on requests with an OIDC ID token of the add-on's
    own service account, not the Google Chat service account:
    https://developers.google.com/workspace/add-ons/guides/alternate-runtimes

    ``audience`` is the HTTPS endpoint URL configured for the add-on.
    ``service_account_email`` is shown in the Google Cloud console under
    Google Workspace Marketplace SDK > HTTP Deployments (or in the Chat
    API configuration). Fail-closed like ``GoogleTokenVerifier``.
    """

    def __init__(
        self,
        *,
        audience: str,
        service_account_email: str,
        request: google_requests.Request | None = None,
    ) -> None:
        if not audience.startswith("https://"):
            raise ValueError(
                f"audience must be the add-on's HTTPS endpoint URL; got {audience!r}"
            )
        if not service_account_email or "@" not in service_account_email:
            raise ValueError(
                "service_account_email must be the add-on's service "
                "account email address"
            )
        self._audience = audience
        self._service_account_email = service_account_email
        self._request = request if request is not None else google_requests.Request()

    def verify(self, request: IncomingRequest) -> None:
        token = extract_bearer(request)
        try:
            # Never pass certs_url here (see GoogleTokenVerifier.verify).
            claims = verify_oauth2_token(  # type: ignore[no-untyped-call]
                token, self._request, audience=self._audience
            )
        except google_auth_exceptions.TransportError as error:
            raise VerificationError("Cannot reach Google certificates") from error
        except (ValueError, google_auth_exceptions.GoogleAuthError) as error:
            raise VerificationError("Invalid bearer token") from error
        if claims.get("email") != self._service_account_email:
            raise VerificationError("Token identity is not the add-on service account")
        if claims.get("email_verified") is not True:
            raise VerificationError("Token email is not verified")


class MockVerifier:
    """Accepts (or rejects) any request; for tests and local development only."""

    def __init__(self, *, reject: bool = False) -> None:
        self._reject = reject

    def verify(self, request: IncomingRequest) -> None:
        if self._reject:
            raise VerificationError("Mock verifier rejected the request")


__all__ = [
    "AddOnTokenVerifier",
    "GoogleTokenVerifier",
    "IncomingRequestVerifier",
    "MockVerifier",
]
