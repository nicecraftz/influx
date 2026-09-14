from fastapi import APIRouter, Depends
from pydantic import BaseModel

from influx.auth.dependencies import get_current_user
from influx.core.db import SessionDep

crawler = APIRouter(prefix="/crawler", tags=["crawler"], dependencies=[Depends(get_current_user)])


class CrawlRequest(BaseModel):
    link_id: int


@crawler.post("/")
async def crawl_site(body: CrawlRequest, session: SessionDep):
    pass


@crawler.get("/{crawl_id}")
async def get_crawl(crawl_id: int, session: SessionDep):
    pass
