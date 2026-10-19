"""Validate delegated Entra v2 access tokens; authorize provisioned local identities."""

import ssl
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any
from uuid import UUID

import jwt
from fastapi import Depends, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jwt import PyJWKClient
from jwt.exceptions import PyJWKClientConnectionError, PyJWKClientError
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import Settings
from app.db import get_session
from app.models import User

bearer = HTTPBearer(auto_error=False)


@dataclass(frozen=True)
class EntraIdentity:
    tenant_id: UUID
    object_id: UUID


class EntraTokenValidator:
    def __init__(self, settings: Settings, key_resolver: Callable[[str], Any] | None = None):
        self.settings = settings
        # The JWKS endpoint is constructed from a validated tenant UUID, never from token claims.
        context = ssl.create_default_context()
        if settings.entra_ca_bundle:
            context.load_verify_locations(cafile=settings.entra_ca_bundle)
        self.jwks = PyJWKClient(settings.jwks_url, timeout=5, lifespan=300, ssl_context=context)
        self.key_resolver = key_resolver or self._resolve_key

    def _resolve_key(self, token: str):
        return self.jwks.get_signing_key_from_jwt(token).key

    def validate(self, token: str) -> EntraIdentity:
        if not self.settings.entra_configured or not self.settings.entra_allowed_client_ids:
            raise HTTPException(503, "Microsoft Entra ID is not configured")
        try:
            if len(token) > 16384:
                raise ValueError("Token too large")
            header = jwt.get_unverified_header(token)
            if header.get("alg") != "RS256" or not isinstance(header.get("kid"), str):
                raise ValueError("Unsupported signing algorithm")
            if not 1 <= len(header["kid"]) <= 200:
                raise ValueError("Invalid key identifier")
            key = self.key_resolver(token)
            claims = jwt.decode(
                token,
                key,
                algorithms=["RS256"],
                issuer=self.settings.issuer,
                audience=str(self.settings.entra_api_client_id),
                leeway=self.settings.jwt_leeway_seconds,
                options={
                    "strict_aud": True,
                    "require": [
                        "exp",
                        "nbf",
                        "iat",
                        "iss",
                        "aud",
                        "tid",
                        "oid",
                        "sub",
                        "ver",
                        "scp",
                        "azp",
                    ],
                },
            )
            if any(not isinstance(claims[name], str) for name in ("tid", "oid", "azp")):
                raise ValueError("Identity identifiers must be UUID strings")
            tenant_id, object_id = UUID(claims["tid"]), UUID(claims["oid"])
            if claims["ver"] != "2.0" or tenant_id != self.settings.entra_tenant_id:
                raise ValueError("Wrong tenant or token version")
            if not isinstance(claims["scp"], str):
                raise ValueError("Delegated user scope required")
            if self.settings.entra_required_scope not in claims["scp"].split():
                raise ValueError("Missing delegated scope")
            if UUID(claims["azp"]) not in self.settings.entra_allowed_client_ids:
                raise ValueError("Unauthorized client application")
            return EntraIdentity(tenant_id=tenant_id, object_id=object_id)
        except PyJWKClientConnectionError:
            raise HTTPException(503, "Entra signing keys temporarily unavailable") from None
        except (jwt.InvalidTokenError, PyJWKClientError, ValueError, TypeError, KeyError):
            raise HTTPException(
                401,
                "Invalid access token",
                headers={"WWW-Authenticate": "Bearer"},
            ) from None


def current_user(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer),
    session: Session = Depends(get_session),
) -> User:
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise HTTPException(
            401, "Bearer access token required", headers={"WWW-Authenticate": "Bearer"}
        )
    identity = request.app.state.token_validator.validate(credentials.credentials)
    user = session.scalar(
        select(User).where(
            User.entra_tenant_id == identity.tenant_id,
            User.entra_object_id == identity.object_id,
        )
    )
    if user is None or not user.is_active:
        raise HTTPException(403, "User is not provisioned or is inactive")
    # App roles and identity come from the local database. Email and token roles cannot elevate access.
    return user


def admin_user(user: User = Depends(current_user)) -> User:
    if user.role != "SUPER_ADMIN":
        raise HTTPException(403, "Super Admin role required")
    return user


def operational_user(user: User = Depends(current_user)) -> User:
    if user.role not in {"OPERATOR", "FINANCE", "SUPER_ADMIN"}:
        raise HTTPException(403, "This role has read-only operational access")
    return user


def master_writer(user: User = Depends(current_user)) -> User:
    if user.role not in {"OPERATOR", "SUPER_ADMIN"}:
        raise HTTPException(403, "This role cannot modify operational masters")
    return user


def consolidated(user: User) -> bool:
    return user.role in {"MANAGER", "SUPER_ADMIN"}
