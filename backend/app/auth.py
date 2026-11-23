"""Clerk session-token verification.

The frontend sends the Clerk session JWT as a Bearer token. The backend
verifies it against Clerk's JWKS (fetched from CLERK_JWKS_URL, cached) and
takes the user id from the token's ``sub`` claim — never from anything the
frontend sends in a body or query string.

For tests, ``verify_token`` accepts a ``jwks`` dict directly, so tests can
sign tokens with a throwaway RSA key and pass the matching JWKS without
any network or real Clerk app.
"""
import time

from . import http_client
import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from .config import settings

_bearer = HTTPBearer(auto_error=False)
_jwks_cache: dict = {"keys": None, "fetched_at": 0.0}
_JWKS_TTL_SECONDS = 3600


class CurrentUser:
    """The signed-in user, as proven by the Clerk token."""

    def __init__(self, user_id: str):
        self.id = user_id


def _fetch_jwks() -> dict:
    """Fetch Clerk's JWKS, cached for an hour."""
    if not settings.clerk_jwks_url:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="CLERK_JWKS_URL is not configured. See README / .env.example.",
        )
    now = time.time()
    if _jwks_cache["keys"] is not None and now - _jwks_cache["fetched_at"] < _JWKS_TTL_SECONDS:
        return _jwks_cache["keys"]
    resp = http_client.get(settings.clerk_jwks_url, timeout=10)
    resp.raise_for_status()
    _jwks_cache["keys"] = resp.json()
    _jwks_cache["fetched_at"] = now
    return _jwks_cache["keys"]


def verify_token(token: str, jwks: dict | None = None) -> str:
    """Verify a Clerk session JWT, return the user id (sub claim).

    Raises ValueError on any problem (bad signature, expired, wrong issuer).
    """
    keys = jwks if jwks is not None else _fetch_jwks()
    header = jwt.get_unverified_header(token)
    kid = header.get("kid")
    key_data = None
    for k in keys.get("keys", []):
        if k.get("kid") == kid:
            key_data = k
            break
    if key_data is None:
        raise ValueError("no matching key in JWKS")
    public_key = jwt.algorithms.RSAAlgorithm.from_jwk(key_data)
    options = {"verify_aud": False}  # Clerk session tokens carry no fixed aud
    claims = jwt.decode(
        token,
        public_key,
        algorithms=["RS256"],
        options=options,
        # Clerk's servers and this server never share a clock exactly; a
        # token minted a second ago can still have iat in our future.
        # 10s of leeway is the standard tolerance (applies to exp/nbf/iat).
        leeway=10,
    )
    if settings.clerk_issuer and claims.get("iss") != settings.clerk_issuer:
        raise ValueError("wrong issuer")
    user_id = claims.get("sub")
    if not user_id:
        raise ValueError("token has no sub claim")
    return user_id


async def get_current_user(
    creds: HTTPAuthorizationCredentials | None = Depends(_bearer),
) -> CurrentUser:
    if creds is None or not creds.credentials:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing bearer token"
        )
    try:
        user_id = verify_token(creds.credentials)
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or expired session"
        )
    return CurrentUser(user_id)
