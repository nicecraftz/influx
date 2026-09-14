from fastapi import APIRouter, Depends

from influx.auth.dependencies import get_current_user
from influx.core.db import SessionDep

users = APIRouter(prefix="/users", tags=["users"], dependencies=[Depends(get_current_user)])


@users.get("/")
async def get_users(session: SessionDep):
    pass


@users.get("/{id}")
async def get_user(id: int, session: SessionDep):
    pass


@users.delete("/{id}")
async def delete_user(id: int, session: SessionDep):
    pass


@users.patch("/{id}")
async def update_user(id: int, session: SessionDep):
    pass
