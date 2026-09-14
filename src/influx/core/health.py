"""Liveness and readiness probes, mounted at the root (no API version).

`GET /health` answers 200 as soon as the process serves requests, for restart
decisions. `GET /health/ready` also pings the database and Ollama and answers
503 while either is unreachable, for load balancers and compose healthchecks.
"""

import asyncio
from typing import Literal

from fastapi import APIRouter
from fastapi.responses import JSONResponse
from ollama import AsyncClient
from sqlalchemy import text

from influx.core.config import OLLAMA_HOST
from influx.core.db import engine
from influx.core.exceptions import ProblemDetailsException
from influx.core.logging import get_logger

log = get_logger(__name__)

health = APIRouter(prefix="/health", tags=["health"])

CheckStatus = Literal["ok", "failed"]
_PROBE_TIMEOUT = 5.0

class NotReady(ProblemDetailsException):
    status = 503
    type = "tag:influx,2026:not-ready"
    title = "Service not ready"

@health.get("")
async def liveness() -> dict[str, str]:
    return {"status": "ok"}


@health.get("/ready")
async def readiness() -> JSONResponse:
    checks = {"database": await _check_database(), "ollama": await _check_ollama()}
    if all(status == "ok" for status in checks.values()):
        return JSONResponse({"status": "ok", "checks": checks})
    raise NotReady(checks=checks)


async def _check_database() -> CheckStatus:
    try:
        async with asyncio.timeout(_PROBE_TIMEOUT), engine.connect() as connection:
            await connection.execute(text("SELECT 1"))
    except Exception:
        log.warning("readiness: database unreachable")
        return "failed"
    return "ok"


async def _check_ollama() -> CheckStatus:
    try:
        async with asyncio.timeout(_PROBE_TIMEOUT):
            await AsyncClient(host=OLLAMA_HOST).list()  # GET /api/tags
    except Exception:
        log.warning("readiness: ollama unreachable at %s", OLLAMA_HOST)
        return "failed"
    return "ok"
