import bcrypt

# bcrypt hashes at most 72 bytes; since 5.0 it raises instead of truncating.
# Enforced on the request schema (auth/schemas.py) so the API answers 422,
# never 500. The lower bound is a plain policy choice.
PASSWORD_MIN_BYTES = 8
PASSWORD_MAX_BYTES = 72

# A hash to check against when the email is unknown, so that a miss costs the
# same ~100 ms as a wrong password and the response time does not reveal which
# emails are registered.
_DUMMY_HASH = bcrypt.hashpw(b"influx-dummy-password", bcrypt.gensalt())


def encrypt_password(password: str) -> bytes:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt())


def check_password(password: str, hashed_password: bytes | None) -> bool:
    """Constant-cost check: a missing hash still runs bcrypt and returns False."""
    if hashed_password is None:
        bcrypt.checkpw(password.encode("utf-8"), _DUMMY_HASH)
        return False
    return bcrypt.checkpw(password.encode("utf-8"), hashed_password)
