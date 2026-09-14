from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI

from influx.core.config import JWT_SECRET_PATH
from influx.core.db import close_db, init_db
from influx.core.exceptions import register_problem_handlers
from influx.core.health import health
from influx.core.logging import setup_logging

from influx.auth.routes import auth
from influx.crawler.routes import crawler
from influx.organization.routes import organizations
from influx.user.routes import users
from influx.retrieval.routes import retrieval

@asynccontextmanager
async def lifespan(app: FastAPI):
    setup_logging()
    private_key = Path(JWT_SECRET_PATH).read_bytes()
    await init_db()
    yield {"private_key": private_key}
    await close_db()


routes = (auth, crawler, organizations, users, retrieval)
app = FastAPI(lifespan=lifespan)
register_problem_handlers(app)

app.include_router(health)
for r in routes:
    app.include_router(r, prefix="/api/v1")
