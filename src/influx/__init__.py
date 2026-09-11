import argparse
import asyncio


def main() -> None:
    parser = argparse.ArgumentParser(prog="influx")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("init-db", help="create all tables")
    crawl = commands.add_parser("crawl", help="queue one crawl per URL and wait for them")
    crawl.add_argument("--organization-id", type=int, required=True)
    crawl.add_argument("urls", nargs="+")
    args = parser.parse_args()

    from influx.core.logging import setup_logging

    setup_logging()
    asyncio.run(_dispatch(args))


async def _dispatch(args: argparse.Namespace) -> None:
    from influx.core.db import init_db

    await init_db()
    if args.command == "crawl":
        from influx.crawler.application.scheduler import CrawlScheduler

        scheduler = CrawlScheduler()
        await scheduler.start()
        for url in args.urls:
            await scheduler.submit(args.organization_id, url, automated=False)
        await scheduler.stop()
