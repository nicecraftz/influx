# A crawl has no size/time limit and buffers everything in the API process → unbounded runtime and OOM

**Priority: high**

## Problem

Crawls run **inside the API process** (`main.py:26-29`), and `run_crawl` (`crawler/application/crawler.py`)
puts no bound on them:

- no `max_requests_per_crawl`, `max_crawl_depth` or wall-clock limit; the only defence against calendar /
  facet traps is a hand-written `CrawlRule`. One such site occupies one of the two workers indefinitely
  and the 24 h sweep keeps queuing crawls behind it;
- the request queue is `MemoryStorageClient` — every discovered URL (up to 2048 chars, plus Crawlee's
  metadata) lives in RAM for the life of the crawl;
- HTML responses are fully buffered by Crawlee with no size cap (a 500 MB "page" is read into memory);
- documents are buffered to `MAX_DOCUMENT_BYTES` (70 MB) × `DOCUMENT_MAX_CONCURRENCY` (4) per crawl, plus
  up to `STORAGE_BATCH_BYTES` (32 MB) pending, × `CRAWL_WORKERS` (2) → >600 MB worst case, in the same
  process that serves requests and holds the JWT secret;
- `Page.content` has no length cap, so a huge page also becomes a huge row and a huge embedding job.

A tenant's site (or a page redirecting to a large file, see the SSRF issue) can therefore take the API down
with an OOM kill, which also fails every other crawl in progress.

## Approach

1. Pass Crawlee limits: `max_requests_per_crawl` (e.g. 20 000), `max_crawl_depth`, and wrap `crawler.run`
   in `asyncio.timeout(CRAWL_MAX_SECONDS)` → `CrawlInterrupted`, recorded on the `Crawl` row with a
   distinct reason so operators see the site needs rules.
2. Cap page bodies: check `content-length` before reading and abort on stream size, as
   `_download_document` already does; truncate `Page.content` to a configured maximum.
3. Lower `MAX_DOCUMENT_BYTES` (70 MB PDFs are rarely useful for QA) and stream documents to Postgres large
   objects or object storage instead of buffering.
4. Move crawling out of the API process (separate `influx worker` service in compose, same image) so
   memory pressure and restarts of the crawler never affect request serving; the scheduler already reads
   PENDING rows from the DB, so the queue can become the table itself (`SELECT … FOR UPDATE SKIP LOCKED`).
