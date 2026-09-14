from http import HTTPStatus
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request
from sqlmodel import select

from influx.auth.dependencies import get_current_user, require_membership
from influx.core.db import SessionDep
from influx.crawler.application.policy import request_crawl
from influx.crawler.application.scheduler import CrawlScheduler
from influx.crawler.domain.models import Crawl
from influx.crawler.exceptions import CrawlNotFound
from influx.crawler.schemas import CrawlRead
from influx.organization.domain.models import Participation, Role

crawler = APIRouter(prefix="/crawler", tags=["crawler"], dependencies=[Depends(get_current_user)])


def get_scheduler(request: Request) -> CrawlScheduler:
    return request.state.scheduler


SchedulerDep = Annotated[CrawlScheduler, Depends(get_scheduler)]
OrganizationMember = Annotated[Participation, Depends(require_membership(param="organization_id"))]
OrganizationAdmin = Annotated[Participation, Depends(require_membership(Role.ADMIN, param="organization_id"))]


@crawler.post("/organizations/{organization_id}", status_code=HTTPStatus.ACCEPTED, response_model=list[CrawlRead])
async def crawl_organization(organization_id: int, membership: OrganizationAdmin, scheduler: SchedulerDep):
    return await request_crawl(scheduler, organization_id, requested_by_user_id=membership.user_id)


@crawler.get("/organizations/{organization_id}", response_model=list[CrawlRead])
async def list_crawls(
    organization_id: int,
    membership: OrganizationMember,
    session: SessionDep,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
):
    statement = (
        select(Crawl)
        .where(Crawl.organization_id == organization_id)
        .order_by(Crawl.created_at.desc(), Crawl.id.desc())
        .offset(offset)
        .limit(limit)
    )
    return (await session.exec(statement)).all()


# Crawl ids are global, but the session only sees the caller's organizations
# (core/rls.py), so anything else is a 404 rather than a leak.
@crawler.get("/{crawl_id}", response_model=CrawlRead)
async def get_crawl(crawl_id: int, session: SessionDep):
    crawl = await session.get(Crawl, crawl_id)
    if crawl is None:
        raise CrawlNotFound(f"no crawl with id {crawl_id}")
    return crawl
