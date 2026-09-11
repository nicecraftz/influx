import argparse
import asyncio


def main() -> None:
    parser = argparse.ArgumentParser(prog="influx")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("init-db", help="create all tables")
    args = parser.parse_args()

    from influx.core.logging import setup_logging

    setup_logging()
    asyncio.run(_dispatch(args))


async def _dispatch(args: argparse.Namespace) -> None:
    from influx.core.db import init_db

    await init_db()
