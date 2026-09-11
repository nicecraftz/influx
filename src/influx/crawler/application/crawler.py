"""One crawl of one site: pages -> Page rows, attachments -> Document rows,
other hosts under the same domain -> Link rows (disabled until toggled)."""

import asyncio
import logging
import signal
import uuid
from dataclasses import dataclass

from crawlee import ConcurrencySettings
from crawlee._service_locator import ServiceLocator
from crawlee.crawlers import ParselCrawler, ParselCrawlingContext
from crawlee.http_clients import ImpitHttpClient
from crawlee.request_loaders import ThrottlingRequestManager
from crawlee.storage_clients import MemoryStorageClient
from crawlee.storages import RequestQueue

from influx.core.config import (
    CRAWL_MAX_CONCURRENCY,
    CRAWL_RESPECT_ROBOTS_TXT,
    DOCUMENT_MAX_CONCURRENCY,
    MAX_DOCUMENT_BYTES,
)
from influx.core.logging import get_logger
from influx.crawler.application.service import (
    LinkKind,
    SiteScope,
    UrlRules,
    absolute_links,
    extract_text,
    link_origin,
)
from influx.crawler.application.storage import CrawlStorage

log = get_logger(__name__)

_HTML_TYPES = ("text/html", "application/xhtml+xml")

# A URL that answers with one of these is dead, not blocked: don't rotate the
# session, don't retry, don't dump a stacktrace. The handler sees the response
# and skips it with one warning. 429 stays out so the throttler backs off.
_DEAD_STATUS_CODES = (401, 403, 404, 410, 451)
# Rotations still happen for 429 and for the odd 403 that really is a bot
# wall; Crawlee's default of 10 is for scraping behind proxies, not for this.
_MAX_SESSION_ROTATIONS = 2


@dataclass(frozen=True)
class CrawlResult:
    requests_finished: int
    requests_failed: int
    pages: int
    documents: int
    links: int


class DocumentTooLarge(Exception):
    pass


class CrawlInterrupted(Exception):
    """The crawl was stopped by SIGINT before the queue ran dry. Whatever was
    gathered so far is flushed to storage."""


async def run_crawl(organization_id: int, root_url: str, rules: UrlRules | None = None) -> CrawlResult:
    """Crawl `root_url` for `organization_id` and persist everything. Raises when
    the crawl cannot complete (storage failure, bad root URL, ...)."""
    scope = SiteScope.for_root(root_url, rules)
    # Each crawl gets a private in-memory queue so concurrent crawls never share
    # URL de-duplication state. The throttler wraps it to honour robots.txt
    # crawl-delay and back off on 429s; its per-host sub-queues are opened
    # through the locator, which must point at the same in-memory client or
    # Crawlee falls back to its JSON-on-disk default.
    storage_client = MemoryStorageClient()
    queue = await RequestQueue.open(name=f"crawl-{uuid.uuid4().hex}", storage_client=storage_client)
    throttler = ThrottlingRequestManager(
        inner=queue,
        domains=sorted(scope.hosts),
        request_manager_opener=RequestQueue.open,
        service_locator=ServiceLocator(storage_client=storage_client),
    )
    # Kept in hand so attachments can be streamed with a size cap; `context.send_request`
    # buffers the whole body before returning.
    http_client = ImpitHttpClient()
    crawler = ParselCrawler(
        request_manager=throttler,
        storage_client=storage_client,
        http_client=http_client,
        concurrency_settings=ConcurrencySettings(max_concurrency=CRAWL_MAX_CONCURRENCY),
        respect_robots_txt_file=CRAWL_RESPECT_ROBOTS_TXT,
        ignore_http_error_status_codes=_DEAD_STATUS_CODES,
        max_session_rotations=_MAX_SESSION_ROTATIONS,
        configure_logging=False,
        statistics_log_format="inline",
        _logger=logging.getLogger("crawlee.crawler"),
    )
    # Attachments are fetched outside the request queue, so it can't de-duplicate
    # them for us; subdomain links repeat on every page (nav, footer) and would
    # otherwise be re-sent to storage on every flush.
    seen_documents: set[str] = set()
    seen_links: set[str] = set()
    # Downloads run as their own tasks: doing them inline would hold the page
    # handler (and its 60 s timeout) hostage to the size of every PDF it links.
    downloads: set[asyncio.Task[None]] = set()
    download_slots = asyncio.Semaphore(DOCUMENT_MAX_CONCURRENCY)

    async with CrawlStorage(organization_id) as storage:

        @crawler.router.default_handler
        async def handle_page(context: ParselCrawlingContext) -> None:
            url = context.request.url
            status = context.http_response.status_code
            if status >= 400:
                log.warning("skipping %s: HTTP %d", url, status)
                return
            content_type = context.http_response.headers.get("content-type", "")
            if not content_type.startswith(_HTML_TYPES):
                log.warning("skipping %s: content-type %r is not HTML", url, content_type)
                return

            await storage.add_page(url, extract_text(context.selector))

            pages: list[str] = []
            for raw in absolute_links(context.selector, context.request.loaded_url or url):
                link = scope.canonical(raw)
                match scope.classify(link):
                    case LinkKind.PAGE:
                        pages.append(link)
                    case LinkKind.DOCUMENT:
                        if link not in seen_documents:
                            seen_documents.add(link)
                            task = asyncio.create_task(_download_document(http_client, storage, link, download_slots))
                            downloads.add(task)
                            task.add_done_callback(downloads.discard)
                    case LinkKind.SUBDOMAIN:
                        origin = link_origin(link)
                        if origin not in seen_links:
                            seen_links.add(origin)
                            await storage.add_link(origin)
                    case LinkKind.EXTERNAL | LinkKind.IGNORED:
                        pass
            if pages:
                await context.add_requests(pages)

        @crawler.failed_request_handler
        async def handle_failure(context: ParselCrawlingContext, error: Exception) -> None:
            log.warning("giving up on %s: %s", context.request.url, error)

        log.info("crawl started: %s (organization %s, %d exclusion rules)", root_url, organization_id, len(scope.rules))
        try:
            stats = await crawler.run([scope.canonical(root_url)])
            # Crawlee installs its own SIGINT handler for the duration of `run()`:
            # Ctrl+C lets in-flight requests finish and then returns as if the
            # crawl had completed. Requests still queued are the tell.
            if not await throttler.is_finished():
                raise CrawlInterrupted(root_url)
            if downloads:
                log.info("crawl of %s: waiting for %d document downloads", root_url, len(downloads))
                await _wait_or_interrupt(downloads)
        except CrawlInterrupted:
            log.warning("crawl of %s interrupted; flushing what was gathered", root_url)
            raise
        finally:
            for task in downloads:
                task.cancel()
            await queue.drop()

    result = CrawlResult(
        requests_finished=stats.requests_finished,
        requests_failed=stats.requests_failed,
        pages=storage.pages_written,
        documents=storage.documents_written,
        links=storage.links_written,
    )
    log.info(
        "crawl finished: %s — %d requests ok, %d failed, %d pages, %d documents, %d links",
        root_url, result.requests_finished, result.requests_failed, result.pages, result.documents, result.links,
    )
    return result


async def _wait_or_interrupt(tasks: set[asyncio.Task[None]]) -> None:
    """Wait for `tasks`, or raise CrawlInterrupted on SIGINT. Crawlee removes its
    handler when `run()` returns, so from here on Ctrl+C would otherwise be a bare
    KeyboardInterrupt tearing down the loop mid-flush."""
    loop = asyncio.get_running_loop()
    interrupted = asyncio.Event()
    loop.add_signal_handler(signal.SIGINT, interrupted.set)
    stop = asyncio.ensure_future(interrupted.wait())
    pending: set[asyncio.Future[None]] = set(tasks)
    try:
        while pending and not interrupted.is_set():
            _, pending = await asyncio.wait({*pending, stop}, return_when=asyncio.FIRST_COMPLETED)
            pending.discard(stop)
        if interrupted.is_set():
            raise CrawlInterrupted
    finally:
        stop.cancel()
        loop.remove_signal_handler(signal.SIGINT)


async def _download_document(
    http_client: ImpitHttpClient, storage: CrawlStorage, url: str, slots: asyncio.Semaphore
) -> None:
    """Fetch an attachment and hand it to storage. Failures are logged, never raised:
    one broken PDF must not fail the page that linked to it."""
    try:
        async with slots, http_client.stream(url) as response:
            if response.status_code >= 400:
                log.warning("document %s returned HTTP %d", url, response.status_code)
                return
            declared = int(response.headers.get("content-length") or 0)
            if declared > MAX_DOCUMENT_BYTES:
                raise DocumentTooLarge(declared)
            chunks: list[bytes] = []
            size = 0
            async for chunk in response.read_stream():
                size += len(chunk)
                if size > MAX_DOCUMENT_BYTES:
                    raise DocumentTooLarge(size)
                chunks.append(chunk)
        await storage.add_document(url, b"".join(chunks))
    except DocumentTooLarge as too_large:
        log.warning("document %s skipped: exceeds %d bytes (%s+)", url, MAX_DOCUMENT_BYTES, too_large)
    except asyncio.CancelledError:
        raise
    except Exception:
        log.error("document %s could not be downloaded", url)
