from fastapi import APIRouter, Depends

from influx.auth.dependencies import get_current_user
from influx.core.db import SessionDep

retrieval = APIRouter(prefix="/retrieval", tags=["retrieval"], dependencies=[Depends(get_current_user)])


@retrieval.get("/")
async def query(message: str, session: SessionDep):
    pass


@retrieval.get("/metrics")
async def get_metrics(session: SessionDep):
    pass
