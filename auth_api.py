"""OAuth2 client-credentials + JWT bearer auth for the practice API.

Tokens are HS256 JWTs. Secrets are never hard-coded: the signing key and the
demo client secrets come from the environment, or are generated randomly per
process (tests read them from ``settings``).
"""
import hmac
import os
import secrets
import time
import uuid
from dataclasses import dataclass, field
from urllib.parse import parse_qs

import jwt
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.responses import JSONResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel

bearer_scheme = HTTPBearer(auto_error=False, bearerFormat="JWT")


class ErrorDetail(BaseModel):
    detail: str


class OAuthError(BaseModel):
    error: str
    error_description: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str
    expires_in: int
    scope: str


class Identity(BaseModel):
    sub: str
    role: str | None
    scope: str


UNAUTHORIZED = {401: {"model": ErrorDetail, "description": "Missing, invalid, expired or revoked token"}}
FORBIDDEN = {403: {"model": ErrorDetail, "description": "Authenticated but not permitted"}}

TOKEN_FORM = {
    "requestBody": {
        "required": True,
        "content": {
            "application/x-www-form-urlencoded": {
                "schema": {
                    "type": "object",
                    "required": ["grant_type", "client_id", "client_secret"],
                    "properties": {
                        "grant_type": {"type": "string", "enum": ["client_credentials"]},
                        "client_id": {"type": "string"},
                        "client_secret": {"type": "string"},
                        "scope": {"type": "string"},
                    },
                }
            }
        },
    }
}

ALGORITHM = "HS256"


@dataclass
class Client:
    secret: str
    role: str
    allowed_scopes: frozenset


def _default_clients() -> dict[str, Client]:
    return {
        "reader": Client(secrets.token_urlsafe(16), "user", frozenset({"reports:read"})),
        "admin": Client(
            secrets.token_urlsafe(16), "admin", frozenset({"reports:read", "admin"})
        ),
        "noscope": Client(secrets.token_urlsafe(16), "user", frozenset()),
    }


@dataclass
class AuthSettings:
    secret: str = field(
        default_factory=lambda: os.getenv("AUTH_JWT_SECRET") or secrets.token_urlsafe(32)
    )
    issuer: str = "practice-api"
    audience: str = "practice-api-clients"
    ttl_seconds: int = field(
        default_factory=lambda: int(os.getenv("AUTH_TOKEN_TTL_S", "300"))
    )
    clients: dict[str, Client] = field(default_factory=_default_clients)
    revoked: set = field(default_factory=set)


settings = AuthSettings()
router = APIRouter()


def oauth_error(status: int, error: str, description: str) -> JSONResponse:
    headers = {"Cache-Control": "no-store"}
    if status == 401:
        headers["WWW-Authenticate"] = 'Basic realm="token"'
    return JSONResponse(
        {"error": error, "error_description": description},
        status_code=status,
        headers=headers,
    )


def issue_token(client_id: str, client: Client, scopes: list[str]) -> str:
    now = int(time.time())
    claims = {
        "iss": settings.issuer,
        "aud": settings.audience,
        "sub": client_id,
        "iat": now,
        "nbf": now,
        "exp": now + settings.ttl_seconds,
        "jti": str(uuid.uuid4()),
        "scope": " ".join(sorted(scopes)),
        "role": client.role,
    }
    return jwt.encode(claims, settings.secret, algorithm=ALGORITHM)


@router.post(
    "/auth/token",
    tags=["auth"],
    response_model=TokenResponse,
    responses={
        400: {"model": OAuthError, "description": "Unsupported grant or invalid scope"},
        401: {"model": OAuthError, "description": "Client authentication failed"},
    },
    openapi_extra=TOKEN_FORM,
)
async def token(request: Request):
    form = {k: v[0] for k, v in parse_qs((await request.body()).decode()).items()}

    if form.get("grant_type") != "client_credentials":
        return oauth_error(400, "unsupported_grant_type", "Only client_credentials is supported")

    client = settings.clients.get(form.get("client_id", ""))
    presented = form.get("client_secret", "")
    # Compare against a dummy when the client is unknown to keep timing uniform.
    expected = client.secret if client else "x" * 22
    if not hmac.compare_digest(presented.encode(), expected.encode()) or client is None:
        return oauth_error(401, "invalid_client", "Client authentication failed")

    requested = form.get("scope", "").split()
    if not set(requested) <= client.allowed_scopes:
        return oauth_error(400, "invalid_scope", "Requested scope not permitted")
    granted = requested or sorted(client.allowed_scopes)

    return JSONResponse(
        {
            "access_token": issue_token(form["client_id"], client, granted),
            "token_type": "Bearer",
            "expires_in": settings.ttl_seconds,
            "scope": " ".join(sorted(granted)),
        },
        headers={"Cache-Control": "no-store"},
    )


def _unauthorized(detail: str) -> HTTPException:
    return HTTPException(
        status_code=401, detail=detail, headers={"WWW-Authenticate": "Bearer"}
    )


def authenticate(
    credentials_in: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
) -> dict:
    if credentials_in is None:
        raise _unauthorized("Missing bearer token")
    credentials = credentials_in.credentials
    try:
        claims = jwt.decode(
            credentials,
            settings.secret,
            algorithms=[ALGORITHM],
            audience=settings.audience,
            issuer=settings.issuer,
            options={"require": ["exp", "iat", "sub", "jti"]},
        )
    except jwt.ExpiredSignatureError:
        raise _unauthorized("Token expired") from None
    except jwt.PyJWTError:
        raise _unauthorized("Invalid token") from None
    if claims["jti"] in settings.revoked:
        raise _unauthorized("Token revoked")
    return claims


@router.post("/auth/revoke", tags=["auth"], responses=UNAUTHORIZED)
def revoke(claims: dict = Depends(authenticate)):
    settings.revoked.add(claims["jti"])
    return {"revoked": True}


def require(scope: str | None = None, role: str | None = None):
    def dependency(claims: dict = Depends(authenticate)) -> dict:
        if scope and scope not in claims.get("scope", "").split():
            raise HTTPException(403, f"Missing required scope: {scope}")
        if role and claims.get("role") != role:
            raise HTTPException(403, f"Requires role: {role}")
        return claims

    return dependency


@router.get("/me", tags=["auth"], response_model=Identity, responses=UNAUTHORIZED)
def me(claims: dict = Depends(authenticate)):
    return {"sub": claims["sub"], "role": claims.get("role"), "scope": claims.get("scope", "")}


@router.get("/reports", tags=["auth"], responses={**UNAUTHORIZED, **FORBIDDEN})
def reports(claims: dict = Depends(require(scope="reports:read"))):
    return {"reports": [], "requested_by": claims["sub"]}


@router.delete(
    "/admin/users/{user_id}", status_code=204, tags=["auth"], responses={**UNAUTHORIZED, **FORBIDDEN}
)
def delete_user(user_id: int, claims: dict = Depends(require(role="admin", scope="admin"))):
    return Response(status_code=204)
