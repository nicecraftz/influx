"""One crawl of one site: pages -> Page rows, attachments -> Document rows,
other hosts under the same domain -> Link rows (disabled until toggled)."""

import logging
import uuid
from dataclasses import dataclass

from crawlee import ConcurrencySettings
from crawlee._service_locator import ServiceLocator
from crawlee.crawlers import ParselCrawler, ParselCrawlingContext
from crawlee.http_clients import ImpitHttpClient
from crawlee.request_loaders import ThrottlingRequestManager
from crawlee.storage_clients import MemoryStorageClient
from crawlee.storages import RequestQueue

from influx.core.config import CRAWL_MAX_CONCURRENCY, CRAWL_RESPECT_ROBOTS_TXT, MAX_DOCUMENT_BYTES
from influx.core.logging import get_logger
from influx.crawler.application.service import LinkKind, SiteScope, absolute_links, extract_text, link_origin
from influx.crawler.application.storage import CrawlStorage

log = get_logger(__name__)

_HTML_TYPES = ("text/html", "application/xhtml+xml")


@dataclass(frozen=True)
class CrawlResult:
    requests_finished: int
    requests_failed: int
    pages: int
    documents: int
    links: int


class DocumentTooLarge(Exception):
    pass


async def run_crawl(organization_id: int, root_url: str) -> CrawlResult:
    """Crawl `root_url` for `organization_id` and persist everything. Raises when
    the crawl cannot complete (storage failure, bad root URL, ...)."""
    scope = SiteScope.for_root(root_url)
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
        configure_logging=False,
        statistics_log_format="inline",
        _logger=logging.getLogger("crawlee.crawler"),
    )
    # Attachments are fetched from within page handlers, so the request queue
    # can't de-duplicate them for us.
    seen_documents: set[str] = set()

    async with CrawlStorage(organization_id) as storage:

        @crawler.router.default_handler
        async def handle_page(context: ParselCrawlingContext) -> None:
            url = context.request.url
            content_type = context.http_response.headers.get("content-type", "")
            if not content_type.startswith(_HTML_TYPES):
                log.warning("skipping %s: content-type %r is not HTML", url, content_type)
                return

            await storage.add_page(url, extract_text(context.selector))

            pages: list[str] = []
            for link in absolute_links(context.selector, context.request.loaded_url or url):
                match scope.classify(link):
                    case LinkKind.PAGE:
                        pages.append(link)
                    case LinkKind.DOCUMENT:
                        if link not in seen_documents:
                            seen_documents.add(link)
                            await _download_document(http_client, storage, link)
                    case LinkKind.SUBDOMAIN:
                        await storage.add_link(link_origin(link))
                    case LinkKind.EXTERNAL:
                        pass
            if pages:
                await context.add_requests(pages)

        @crawler.failed_request_handler
        async def handle_failure(context: ParselCrawlingContext, error: Exception) -> None:
            log.warning("giving up on %s: %s", context.request.url, error)

        log.info("crawl started: %s (organization %s)", root_url, organization_id)
        try:
            stats = await crawler.run([root_url])
        finally:
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


async def _download_document(http_client: ImpitHttpClient, storage: CrawlStorage, url: str) -> None:
    """Fetch an attachment and hand it to storage. Failures are logged, never raised:
    one broken PDF must not fail the page that linked to it."""
    try:
        async with http_client.stream(url) as response:
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
    except Exception:
        log.error("document %s could not be downloaded", url)
