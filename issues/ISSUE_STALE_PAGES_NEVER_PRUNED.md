# Pages and documents removed from a site are never deleted; retrieval keeps answering from them

**Priority: medium**

## Problem

`CrawlStorage` only upserts (`crawler/application/storage.py:138-172`). A page or PDF that disappears from
the site keeps its `Page`/`Document` row, its `ContentChunk` rows and its place in the HNSW index, so the
chatbot cites URLs that now 404 and information that was taken down on purpose (an old deadline, a
withdrawn call). `last_seen_at` is written but never read. A `Link` that an admin disables also keeps all
its content. There is no cap on how many crawls' worth of orphans accumulate.

## Approach

1. At the end of a *successful, complete* crawl of a root (not an interrupted or limited one), delete
   `Page`/`Document` rows of that host with `last_seen_at < crawl.started_at` (chunks cascade). Keep a
   grace period (e.g. 2 crawls) to survive transient failures on the site.
2. Pages skipped as HTTP 404/410 in `handle_page` can be deleted immediately.
3. When a `Link` is disabled, delete (or hide with a flag checked by `search_passages`) its content.
4. Add `influx prune --organization-id N --older-than 7d` for operators.
