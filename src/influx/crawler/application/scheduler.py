"""In-process crawl queue.

`submit()` records a PENDING Crawl and enqueues its id; a fixed pool of workers
picks ids up, flips the row to ONGOING, runs the crawl, and closes it as
SUCCEEDED or FAILED. Crawls of different organizations or sites run side by
side, bounded by CRAWL_WORKERS.
"""

import asyncio
from datetime import datetime, timezone

from influx.core.config import CRAWL_WORKERS
from influx.core.db import async_session
from influx.core.logging import get_logger
from influx.crawler.application.crawler import run_crawl
from influx.crawler.domain.models import Crawl, CrawlStatus

log = get_logger(__name__)


class CrawlScheduler:
    def __init__(self, workers: int = CRAWL_WORKERS) -> None:
        self._workers = workers
        self._queue: asyncio.Queue[int] = asyncio.Queue()
        self._tasks: list[asyncio.Task[None]] = []

    async def start(self) -> None:
        if self._tasks:
            return
        self._tasks = [asyncio.create_task(self._worker(i), name=f"crawl-worker-{i}") for i in range(self._workers)]
        log.info("crawl scheduler started with %d workers", self._workers)

    async def stop(self, *, drain: bool = True) -> None:
        """Stop the workers. With `drain` (default) queued crawls finish first."""
        if drain:
            await self._queue.join()
        for task in self._tasks:
            task.cancel()
        await asyncio.gather(*self._tasks, return_exceptions=True)
        self._tasks = []
        log.info("crawl scheduler stopped")

    async def submit(self, organization_id: int, root_url: str, *, automated: bool = True) -> int:
        """Queue a crawl and return its Crawl id."""
        async with async_session() as session:
            crawl = Crawl(organization_id=organization_id, root_url=root_url, automated=automated)
            session.add(crawl)
            await session.commit()
            crawl_id = crawl.id
        assert crawl_id is not None
        await self._queue.put(crawl_id)
        log.info("crawl %d queued: %s (organization %s)", crawl_id, root_url, organization_id)
        return crawl_id

    @property
    def pending(self) -> int:
        return self._queue.qsize()

    async def _worker(self, index: int) -> None:
        while True:
            crawl_id = await self._queue.get()
            try:
                await self._run(crawl_id)
            except Exception:
                # _run handles its own failures; this only guards the worker loop itself.
                log.error("worker %d crashed on crawl %d", index, crawl_id)
            finally:
                self._queue.task_done()

    async def _run(self, crawl_id: int) -> None:
        async with async_session() as session:
            crawl = await session.get(Crawl, crawl_id)
            if crawl is None:
                log.warning("crawl %d vanished before it could start", crawl_id)
                return
            crawl.status = CrawlStatus.ONGOING
            crawl.started_at = datetime.now(timezone.utc)
            await session.commit()

        try:
            await run_crawl(crawl.organization_id, crawl.root_url)
            status = CrawlStatus.SUCCEEDED
        except Exception:
            log.error("crawl %d failed: %s", crawl_id, crawl.root_url)
            status = CrawlStatus.FAILED

        async with async_session() as session:
            crawl = await session.get(Crawl, crawl_id)
            if crawl is not None:
                crawl.status = status
                crawl.finished_at = datetime.now(timezone.utc)
                await session.commit()
