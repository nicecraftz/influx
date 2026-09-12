import argparse
import asyncio
import sys
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from influx.organization.domain.models import Organization

EXAMPLE_USER_EMAIL = "mario.rossi@example.com"
EXAMPLE_ORGANIZATION_NAME = "Esempio"


def main() -> None:
    parser = argparse.ArgumentParser(prog="influx")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("init-db", help="create all tables and an example user/organization")
    crawl = commands.add_parser("crawl", help="queue one crawl per URL and wait for them")
    crawl.add_argument("--organization-id", type=int, required=True)
    crawl.add_argument(
        "--exclude",
        action="append",
        default=[],
        metavar="REGEX",
        help="skip URLs whose path+query matches (repeatable, e.g. '^/ateneo/bandi[?]')",
    )
    crawl.add_argument(
        "--exclude-file",
        metavar="PATH",
        help="text file with one exclusion regex per line ('#' starts a comment)",
    )
    crawl.add_argument("urls", nargs="+")
    embed = commands.add_parser("embed", help="chunk and embed the crawled pages of an organization")
    embed.add_argument("--organization-id", type=int, required=True)
    embed.add_argument(
        "--force",
        action="store_true",
        help="re-embed every page, not only those changed since the last run",
    )
    args = parser.parse_args()

    from influx.core.logging import setup_logging

    setup_logging()
    try:
        asyncio.run(_dispatch(parser, args))
    except KeyboardInterrupt:
        # Only reachable when Ctrl+C lands outside the crawl itself (e.g. during
        # the final flush); the crawl code handles SIGINT on its own.
        sys.exit(130)


async def _dispatch(parser: argparse.ArgumentParser, args: argparse.Namespace) -> None:
    from influx.core.db import init_db

    await init_db()
    if args.command == "init-db":
        organization = await _seed_example(EXAMPLE_USER_EMAIL, EXAMPLE_ORGANIZATION_NAME)
        print(f"organization '{organization.name}' has id {organization.id}")
        return

    await _require_organization(parser, args.organization_id)
    if args.command == "crawl":
        from influx.crawler.application.scheduler import CrawlScheduler
        from influx.crawler.application.service import UrlRules

        rules = UrlRules(args.exclude)
        if args.exclude_file:
            rules += UrlRules.from_file(args.exclude_file)

        scheduler = CrawlScheduler()
        await scheduler.start()
        for url in args.urls:
            await scheduler.submit(args.organization_id, url, automated=False, rules=rules)
        await scheduler.stop()
    elif args.command == "embed":
        from influx.ingestion.application.page_service import embed_pages

        stats = await embed_pages(args.organization_id, force=args.force)
        print(
            f"{stats.embedded} pages embedded ({stats.chunks} chunks), "
            f"{stats.skipped} unchanged, {stats.empty} without text"
        )


async def _require_organization(parser: argparse.ArgumentParser, organization_id: int) -> None:
    from influx.core.db import async_session
    from influx.organization.domain.models import Organization

    async with async_session() as session:
        if await session.get(Organization, organization_id) is None:
            parser.error(f"organization {organization_id} does not exist (see README, 'Utente e organizzazione')")


async def _seed_example(email: str, organization_name: str) -> "Organization":
    """Create the example user and organization unless they already exist."""
    from sqlmodel import select

    from influx.core.db import async_session
    from influx.organization.domain.models import Organization
    from influx.user.domain.models import User

    async with async_session() as session:
        organization = (
            await session.exec(select(Organization).where(Organization.name == organization_name))
        ).first()
        if organization is not None:
            return organization

        user = (await session.exec(select(User).where(User.email == email))).first()
        if user is None:
            user = User(name="Mario", last_name="Rossi", email=email, hashed_password="placeholder")
            session.add(user)
            await session.flush()

        organization = Organization(name=organization_name, administrator_id=user.id)
        session.add(organization)
        await session.commit()
        return organization
