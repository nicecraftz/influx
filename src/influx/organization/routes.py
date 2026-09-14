from fastapi import APIRouter
from pydantic import BaseModel

from influx.auth.dependencies import Admin, CurrentUser, Member, SuperAdmin
from influx.core.db import SessionDep

organizations = APIRouter(prefix="/organizations", tags=["organizations"])


class CrawlRuleCreate(BaseModel):
    regex: str


class LinkStatusUpdate(BaseModel):
    enabled: bool


@organizations.get("/")
async def get_all_organizations(user: CurrentUser, session: SessionDep):
    pass


@organizations.get("/{id}")
async def get_organization(id: int, membership: Member, session: SessionDep):
    pass


@organizations.patch("/{id}")
async def update_organization(id: int, membership: Admin, session: SessionDep):
    pass


@organizations.delete("/{id}")
async def delete_organization(id: int, membership: SuperAdmin, session: SessionDep):
    pass


@organizations.get("/{id}/members")
async def get_members(id: int, membership: Member, session: SessionDep):
    pass


@organizations.post("/{id}/rules")
async def add_crawl_rule(id: int, body: CrawlRuleCreate, membership: Admin, session: SessionDep):
    pass


@organizations.delete("/{id}/rules/{rule_id}")
async def remove_crawl_rule(id: int, rule_id: int, membership: Admin, session: SessionDep):
    pass


@organizations.patch("/{id}/links/{link_id}")
async def set_link_status(id: int, link_id: int, body: LinkStatusUpdate, membership: Admin, session: SessionDep):
    pass
