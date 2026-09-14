from fastapi import APIRouter
from fastapi.responses import JSONResponse

from influx.auth.application.service import login, reset_password
from influx.auth.dependencies import PrivateKeyDep
from influx.core.db import SystemSessionDep

auth = APIRouter(prefix="/auth", tags=["authentication"])


@auth.post("/login")
async def _login(email: str, password: str, session: SystemSessionDep, private_key: PrivateKeyDep):
    token = await login(email, password, session, private_key)
    response = JSONResponse(content=token, status_code=200)
    response.set_cookie(key="Authentication", value="Bearer " + token)
    return response


@auth.post("/reset-password")
async def _reset_password():
    reset_password()
