from typing import Annotated

from pydantic import AfterValidator, BaseModel, EmailStr

from influx.auth.application.password import PASSWORD_MAX_BYTES, PASSWORD_MIN_BYTES


def _check_password_length(value: str) -> str:
    size = len(value.encode("utf-8"))
    if not PASSWORD_MIN_BYTES <= size <= PASSWORD_MAX_BYTES:
        raise ValueError(f"password must be between {PASSWORD_MIN_BYTES} and {PASSWORD_MAX_BYTES} bytes")
    return value


# Validated in bytes, not characters: that is bcrypt's limit, and a 72-char
# password with non-ASCII characters would still overflow it.
Password = Annotated[str, AfterValidator(_check_password_length)]


class LoginRequest(BaseModel):
    email: EmailStr
    password: Password


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
