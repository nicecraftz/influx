from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from influx.auth.application.password import check_password
from influx.auth.application.tokens import encode_token
from influx.auth.exceptions import InvalidCredentialsException
from influx.user.domain.models import User


async def login(email: str, password: str, session: AsyncSession, private_key: bytes) -> str:
    """Checks for valid credentials and returns the JWT token string"""
    statement = select(User).where(User.email == email.lower())
    user = (await session.exec(statement)).first()
    if not check_password(password, user.hashed_password if user else None) or user is None:
        raise InvalidCredentialsException()
    if not user.is_active:
        raise InvalidCredentialsException()
    return encode_token(user.id, private_key)

def reset_password():
    pass
