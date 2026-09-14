"""In-process crawl queue.

`submit()` records a PENDING Crawl and enqueues its id; a fixed pool of workers
picks ids up, flips the row to ONGOING, runs the crawl, and closes it as
SUCCEEDED or FAILED. Crawls of different organizations or sites run side by
side, bounded by CRAWL_WORKERS.

SIGTERM (what `docker stop` sends) is handled while the scheduler is running:
crawls in progress finish their in-flight requests and flush, crawls still
queued are left PENDING, and `stop()` returns once that is done. Under uvicorn
the server owns the signal, so the API builds the scheduler with
`handle_sigterm=False` and calls `shutdown()` itself when its lifespan ends.
"""

import asyncio
import signal
from contextlib import suppress

from sqlmodel import select

from influx.core.config import CRAWL_WORKERS
from influx.core.db import async_session
from influx.core.logging import get_logger
from influx.core.time import utcnow
from influx.crawler.application.crawler import CrawlInterrupted, CrawlResult, run_crawl
from influx.crawler.application.service import UrlRules
from influx.crawler.domain.models import Crawl, CrawlStatus

log = get_logger(__name__)


class CrawlScheduler:
    def __init__(self, workers: int = CRAWL_WORKERS, *, handle_sigterm: bool = True) -> None:
        self._workers = workers
        self._handle_sigterm = handle_sigterm
        self._queue: asyncio.Queue[int] = asyncio.Queue()
        # Exclusion rules are not persisted with the Crawl row: they live here
        # until the worker picks the crawl up.
        self._rules: dict[int, UrlRules] = {}
        self._tasks: list[asyncio.Task[None]] = []
        # Set by SIGTERM; shared with every run_crawl so they wind down together.
        self._shutdown = asyncio.Event()

    async def start(self) -> None:
        if self._tasks:
            return
        self._tasks = [asyncio.create_task(self._worker(i), name=f"crawl-worker-{i}") for i in range(self._workers)]
        # Loop signal handlers only exist on Unix and in the main thread.
        if self._handle_sigterm:
            with suppress(NotImplementedError, ValueError):
                asyncio.get_running_loop().add_signal_handler(signal.SIGTERM, self._on_sigterm)
        log.info("crawl scheduler started with %d workers", self._workers)

    async def stop(self, *, drain: bool = True) -> None:
        """Stop the workers. With `drain` (default) queued crawls finish first."""
        if drain:
            await self._queue.join()
        for task in self._tasks:
            task.cancel()
        await asyncio.gather(*self._tasks, return_exceptions=True)
        self._tasks = []
        if self._handle_sigterm:
            with suppress(NotImplementedError, ValueError):
                asyncio.get_running_loop().remove_signal_handler(signal.SIGTERM)
        log.info("crawl scheduler stopped")

    @property
    def terminated(self) -> bool:
        """True once SIGTERM has been received: some crawls were cut short."""
        return self._shutdown.is_set()

    def _on_sigterm(self) -> None:
        log.warning("SIGTERM received")
        self.shutdown()

    def shutdown(self) -> None:
        """Wind down: running crawls finish their in-flight requests and flush,
        queued ones are left PENDING. `stop()` then returns once they are done."""
        if self._shutdown.is_set():
            return
        log.warning("shutting down: finishing running crawls, leaving queued ones PENDING")
        self._shutdown.set()
        self._abandon_queue()

    async def submit(
        self,
        organization_id: int,
        root_url: str,
        *,
        automated: bool = False,
        rules: UrlRules | None = None,
        link_id: int | None = None,
        requested_by_user_id: int | None = None,
    ) -> int:
        """Queue a crawl and return its Crawl id. `rules` excludes URLs from this crawl only."""
        async with async_session() as session:
            crawl = Crawl(
                organization_id=organization_id,
                root_url=root_url,
                automated=automated,
                link_id=link_id,
                requested_by_user_id=requested_by_user_id,
            )
            session.add(crawl)
            await session.commit()
            crawl_id = crawl.id
        if crawl_id is None:
            raise RuntimeError("crawl row committed without an id")
        await self.enqueue(crawl_id, rules)
        log.info("crawl %d queued: %s (organization %s)", crawl_id, root_url, organization_id)
        return crawl_id

    async def enqueue(self, crawl_id: int, rules: UrlRules | None = None) -> None:
        """Queue a PENDING Crawl row somebody else has already committed."""
        if rules is not None:
            self._rules[crawl_id] = rules
        await self._queue.put(crawl_id)

    async def recover(self) -> None:
        """Pick up what a previous process left behind: crawls still PENDING
        are queued again (rules given on the CLI are gone, the organization's
        own still apply), crawls ONGOING when it died are closed as FAILED.

        Meant for the one long-lived scheduler (the API's); a second process
        calling it would queue the same crawls twice and fail crawls the first
        one is still running.
        """
        async with async_session() as session:
            stale = (await session.exec(select(Crawl).where(Crawl.status == CrawlStatus.ONGOING))).all()
            for crawl in stale:
                crawl.status = CrawlStatus.FAILED
                crawl.finished_at = utcnow()
                crawl.error = "CrawlInterrupted: process restarted"
            pending = (
                await session.exec(select(Crawl.id).where(Crawl.status == CrawlStatus.PENDING).order_by(Crawl.id))
            ).all()
            await session.commit()
        for crawl_id in pending:
            if crawl_id is not None:
                await self.enqueue(crawl_id)
        if stale or pending:
            log.warning("recovered %d PENDING crawls, %d ONGOING marked FAILED", len(pending), len(stale))

    @property
    def pending(self) -> int:
        return self._queue.qsize()

    async def _worker(self, index: int) -> None:
        while True:
            crawl_id = await self._queue.get()
            try:
                if self._shutdown.is_set():
                    # Submitted after the queue was abandoned: same fate.
                    self._rules.pop(crawl_id, None)
                    log.warning("crawl %d not started: left PENDING after interruption", crawl_id)
                    continue
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
            crawl.started_at = utcnow()
            await session.commit()

        interrupted = False
        result: CrawlResult | None = None
        error: str | None = None
        try:
            result = await run_crawl(
                crawl.organization_id, crawl.root_url, self._rules.pop(crawl_id, None), shutdown=self._shutdown
            )
            status = CrawlStatus.SUCCEEDED
        except CrawlInterrupted as exc:
            log.warning("crawl %d interrupted: %s", crawl_id, crawl.root_url)
            status = CrawlStatus.FAILED
            error = f"{type(exc).__name__}: {exc}"
            interrupted = True
        except Exception as exc:
            log.error("crawl %d failed: %s", crawl_id, crawl.root_url)
            status = CrawlStatus.FAILED
            error = f"{type(exc).__name__}: {exc}"

        async with async_session() as session:
            crawl = await session.get(Crawl, crawl_id)
            if crawl is not None:
                crawl.status = status
                crawl.finished_at = utcnow()
                crawl.error = error
                if result is not None:
                    crawl.requests_finished = result.requests_finished
                    crawl.requests_failed = result.requests_failed
                    crawl.pages = result.pages
                    crawl.documents = result.documents
                    crawl.links = result.links
                await session.commit()

        if interrupted:
            self._abandon_queue()

    def _abandon_queue(self) -> None:
        """Ctrl+C and SIGTERM mean stop everything: crawls still queued are left
        PENDING in the database and dropped from the queue so `stop()` can
        return. Crawls already running on other workers finish on their own."""
        while True:
            try:
                crawl_id = self._queue.get_nowait()
            except asyncio.QueueEmpty:
                return
            self._rules.pop(crawl_id, None)
            log.warning("crawl %d not started: left PENDING after interruption", crawl_id)
            self._queue.task_done()
