# The API crawls every 24 h but never converts or embeds, so the index never updates without the CLI

**Priority: medium**

## Problem

`periodic_crawls` (`crawler/application/policy.py:105`) and `POST /crawler/organizations/{id}` produce new
`Page`/`Document` rows, but `convert_documents` and `embed_pages` are reachable only from the CLI
(`src/influx/__init__.py:85-100`). In the documented Docker deployment, the retrieval index therefore
reflects the last time an operator ran `influx embed` by hand: automatic crawls change `Page.hash`, the
old `ContentChunk` rows keep their stale `source_hash`, and answers cite content that may have changed
days ago. There is also no status a member can query to know whether the index is fresh.

## Approach

1. After a crawl closes as SUCCEEDED (`CrawlScheduler._run`), enqueue an ingestion job for the
   organization: `convert_documents(org)` then `embed_pages(org)`, serialised per organization with a
   lock so two crawls of the same org don't race.
2. Run ingestion in the same worker process as the crawler (or a dedicated `influx worker`), never in the
   request path; expose its state on the `Crawl` row (`indexed_at`) or a new `IngestionRun` table, surfaced
   by `GET /crawler/{crawl_id}`.
3. Embedding is sequential per page today; batch pages so a site of 5 000 pages does not take an hour.
