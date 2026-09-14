"""Who gets crawled, and when.

A crawl of an organization is one Crawl per enabled Link: its own site and
the subdomains an admin switched on. An organization is crawled at most once
per CRAWL_INTERVAL whoever asks for it: an admin through the API, or the
periodic sweep that runs every CRAWL_SWEEP_INTERVAL and crawls whatever has
not been crawled within the interval. A manual request therefore also pushes
the next automatic crawl back by a full interval.

"Crawled" means a Crawl row was created, whatever became of it: a failed
crawl does not reopen the window, the operator can still use the CLI.
"""

import asyncio

from sqlalchemy import exists, func, or_
from sqlmodel import select

from influx.core.config import CRAWL_INTERVAL, CRAWL_SWEEP_INTERVAL
from influx.core.db import async_session
from influx.core.logging import get_logger
from influx.core.time import utcnow
from influx.crawler.application.scheduler import CrawlScheduler
from influx.crawler.domain.models import Crawl, Link
from influx.crawler.exceptions import CrawlRefused, CrawlTooSoon, NoEnabledLinks
from influx.organization.domain.models import Organization
from influx.organization.exceptions import OrganizationInactive, OrganizationNotFound

log = get_logger(__name__)


async def request_crawl(
    scheduler: CrawlScheduler,
    organization_id: int,
    *,
    automated: bool = False,
    requested_by_user_id: int | None = None,
) -> list[Crawl]:
    """Queue one crawl per enabled Link of the organization and return the rows.

    Raises OrganizationInactive, CrawlTooSoon (with the time the next request
    is allowed) or NoEnabledLinks. The caller has already checked that whoever
    asks may do so; this only decides whether the organization is due.
    """
    now = utcnow()
    async with async_session() as session:
        # Row lock: two admins, or an admin and the sweep, asking at the same
        # time must not both pass the interval check.
        organization = await session.get(Organization, organization_id, with_for_update=True)
        if organization is None:
            raise OrganizationNotFound(f"no organization with id {organization_id}")
        if not organization.active:
            raise OrganizationInactive(f"organization {organization_id} is inactive")

        last_at = (
            await session.exec(select(func.max(Crawl.created_at)).where(Crawl.organization_id == organization_id))
        ).one()
        if last_at is not None and now - last_at < CRAWL_INTERVAL:
            next_at = last_at + CRAWL_INTERVAL
            raise CrawlTooSoon(next_at, f"organization {organization_id} was crawled at {last_at.isoformat()}")

        links = (
            await session.exec(select(Link).where(Link.organization_id == organization_id, Link.enabled).order_by(Link.id))
        ).all()
        if not links:
            raise NoEnabledLinks(f"organization {organization_id} has no enabled link")

        crawls = [
            Crawl(
                organization_id=organization_id,
                root_url=link.url,
                link_id=link.id,
                automated=automated,
                requested_by_user_id=requested_by_user_id,
            )
            for link in links
        ]
        session.add_all(crawls)
        await session.commit()

    for crawl in crawls:
        await scheduler.enqueue(crawl.id)
    log.info(
        "%s crawl of organization %d queued: %d links",
        "automatic" if automated else "requested",
        organization_id,
        len(crawls),
    )
    return crawls


async def sweep(scheduler: CrawlScheduler) -> int:
    """Queue an automatic crawl for every organization due one; returns how many."""
    queued = 0
    for organization_id in await _due_organizations():
        try:
            await request_crawl(scheduler, organization_id, automated=True)
        except (CrawlRefused, OrganizationInactive, OrganizationNotFound):
            # Someone got there first, or the organization changed since the query.
            continue
        queued += 1
    return queued


async def periodic_crawls(scheduler: CrawlScheduler) -> None:
    """Run `sweep` every CRAWL_SWEEP_INTERVAL until cancelled, starting now."""
    while True:
        try:
            await sweep(scheduler)
        except Exception:
            log.error("periodic crawl sweep failed; retrying at the next interval")
        await asyncio.sleep(CRAWL_SWEEP_INTERVAL.total_seconds())


async def _due_organizations() -> list[int]:
    """Active organizations with at least one enabled Link and no Crawl within the interval."""
    last = (
        select(Crawl.organization_id, func.max(Crawl.created_at).label("last_at"))
        .group_by(Crawl.organization_id)
        .subquery()
    )
    statement = (
        select(Organization.id)
        .outerjoin(last, last.c.organization_id == Organization.id)
        .where(Organization.active)
        .where(or_(last.c.last_at.is_(None), last.c.last_at < utcnow() - CRAWL_INTERVAL))
        .where(exists().where(Link.organization_id == Organization.id, Link.enabled))
        .order_by(Organization.id)
    )
    async with async_session() as session:
        return [id for id in (await session.exec(statement)).all() if id is not None]
