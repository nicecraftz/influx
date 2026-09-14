# A crawl whose start fails (DB hiccup) stays PENDING in the DB but is gone from the in-memory queue

**Priority: low**

## Problem

`CrawlScheduler._run` (`crawler/application/scheduler.py:164-172`) first opens a session to flip the row
to ONGOING. If that raises (connection error, pool timeout), `_worker` logs "worker crashed", calls
`task_done()` and moves on: the `Crawl` row remains `PENDING`, but nothing will ever pick it up until the
API restarts and `recover()` re-queues it. Meanwhile `request_crawl` refuses new crawls for 24 h because
the row exists. The same happens for a crawl that `vanished` between submit and start. There is also no
way to cancel a queued or running crawl (`DELETE /crawler/{crawl_id}`), so a stuck one holds a worker
until the process is restarted.

## Approach

- Make the DB the queue: workers poll `SELECT … WHERE status = 'PENDING' ORDER BY id FOR UPDATE SKIP LOCKED`
  with a short backoff; the in-memory `asyncio.Queue` then only serves as a wake-up signal, and a failed
  start is naturally retried. This also fixes the multi-process caveat in `recover()`.
- Add `DELETE /crawler/{crawl_id}` (admin): PENDING → `CANCELLED`; ONGOING → set a per-crawl stop event
  passed to `run_crawl` (same mechanism as `shutdown`).
- Retry the status flip a few times with backoff before giving up, and mark the row FAILED with the
  reason instead of leaving it PENDING.
