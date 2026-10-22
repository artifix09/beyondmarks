"""Supabase JWT verification.

Supabase Auth issues the token after Google sign-in; this module only verifies
it. Every protected route depends on current_user, so an endpoint that forgets
the dependency is visible in the route signature rather than hidden in a body.
"""

from dataclasses import dataclass

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from .config import get_settings

bearer = HTTPBearer(auto_error=False)


@dataclass(frozen=True)
class CurrentUser:
    """The authenticated student. `sub` is the Supabase auth user id."""

    sub: str
    email: str | None


def current_user(
    creds: HTTPAuthorizationCredentials | None = Depends(bearer),
) -> CurrentUser:
    if creds is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Missing bearer token")

    secret = get_settings().supabase_jwt_secret
    if not secret:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE, "SUPABASE_JWT_SECRET is not configured"
        )

    try:
        claims = jwt.decode(
            creds.credentials,
            secret,
            algorithms=["HS256"],
            audience="authenticated",
        )
    except jwt.PyJWTError as exc:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid token") from exc

    sub = claims.get("sub")
    if not sub:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Token has no subject")

    return CurrentUser(sub=sub, email=claims.get("email"))
