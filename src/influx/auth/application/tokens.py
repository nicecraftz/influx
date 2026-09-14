from datetime import datetime, timedelta, timezone

from jwt import decode, encode

from influx.core.config import JWT_ALGORITHM, JWT_TTL_MINUTES

TOKEN_TTL = timedelta(minutes=JWT_TTL_MINUTES)


def decode_token(token: str, private_key: bytes) -> dict:
    """Verify signature and expiry; raises jwt.InvalidTokenError otherwise."""
    return decode(token, key=private_key, algorithms=[JWT_ALGORITHM], options={"require": ["sub", "exp"]})


def encode_token(user_id: int, private_key: bytes) -> str:
    now = datetime.now(timezone.utc)
    # RFC 7519 §4.1.2: `sub` is the standard subject claim, and PyJWT requires
    # it to be a string.
    claims = {"sub": str(user_id), "iat": now, "exp": now + TOKEN_TTL}
    return encode(claims, key=private_key, algorithm=JWT_ALGORITHM)
