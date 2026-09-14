from fastapi import APIRouter

from influx.auth.application.service import login, reset_password
from influx.auth.dependencies import PrivateKeyDep
from influx.auth.schemas import LoginRequest, TokenResponse
from influx.core.db import SystemSessionDep

auth = APIRouter(prefix="/auth", tags=["authentication"])


# Bearer token in the response body only (RFC 6750 §4): no cookie, so there is
# no CSRF surface and the client decides where to keep it.
@auth.post("/login", response_model=TokenResponse)
async def _login(body: LoginRequest, session: SystemSessionDep, private_key: PrivateKeyDep) -> TokenResponse:
    token = await login(body.email, body.password, session, private_key)
    return TokenResponse(access_token=token)


@auth.post("/reset-password")
async def _reset_password():
    reset_password()
