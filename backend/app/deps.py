from functools import lru_cache

import jwt
from fastapi import Header, HTTPException
from jwt import PyJWKClient

from .config import get_settings


class UserContext:
    def __init__(self, user_id: str):
        self.user_id = user_id


@lru_cache
def _get_jwks_client() -> PyJWKClient:
    """This project's Supabase instance uses rotating asymmetric JWT
    signing keys (no static legacy HS256 secret is exposed at all), so
    verification goes through Supabase's own JWKS endpoint rather than a
    shared-secret env var. PyJWKClient caches keys by `kid` and matches the
    current-vs-previous signing key automatically, which is what makes key
    rotation transparent here. The JWKS endpoint serves public verification
    keys only -- nothing secret is being fetched.
    """
    settings = get_settings()
    jwks_url = f"{settings.supabase_url}/auth/v1/.well-known/jwks.json"
    return PyJWKClient(jwks_url)


def get_current_user(authorization: str = Header(...)) -> UserContext:
    """Verifies the Supabase Auth JWT and returns the caller's user_id (the
    `sub` claim). This is the actual multi-user security boundary on the
    backend side -- every route that touches user data must depend on this
    and scope its query by user_id.
    """
    if not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing or malformed Authorization header")

    token = authorization.removeprefix("Bearer ").strip()
    try:
        signing_key = _get_jwks_client().get_signing_key_from_jwt(token)
        payload = jwt.decode(
            token,
            signing_key.key,
            algorithms=["ES256", "RS256"],
            audience="authenticated",
        )
    except jwt.PyJWTError as exc:
        raise HTTPException(status_code=401, detail="Invalid or expired token") from exc

    user_id = payload.get("sub")
    if not user_id:
        raise HTTPException(status_code=401, detail="Token missing subject claim")
    return UserContext(user_id=user_id)
