# Crawls install/remove the process SIGINT handler, breaking uvicorn's and each other's Ctrl+C handling

**Priority: medium**

## Problem

Two places set the loop-level SIGINT handler while a crawl runs in the API process:

- Crawlee's `BasicCrawler.run` (`crawlee/crawlers/_basic/_basic_crawler.py:750-761`) does
  `add_signal_handler(SIGINT)` and `remove_signal_handler(SIGINT)` when done;
- `_wait_or_interrupt` (`crawler/application/crawler.py:206-226`) does the same while waiting for
  document downloads.

`loop.remove_signal_handler(SIGINT)` restores `signal.default_int_handler`, *not* the previous handler.
uvicorn installs its handler with `signal.signal` (`uvicorn/server.py:330`). So after the first crawl the
API ever runs, Ctrl+C raises `KeyboardInterrupt` in the main thread instead of the graceful shutdown:
in-flight requests are dropped, the lifespan `finally` (scheduler drain, DB dispose) does not run, and
ONGOING crawls are not flushed. With `CRAWL_WORKERS = 2`, two overlapping crawls also overwrite each
other's handler in the CLI, so Ctrl+C during the second crawl is either ignored by the first or turns
into a hard `KeyboardInterrupt` after one of them removes the handler. `docker stop` (SIGTERM) is
unaffected, which is why it has not been noticed.

## Approach

1. Stop touching signals inside crawls: pass Crawlee an option to not install its handler if available,
   otherwise run the crawl through `crawler.run()` in a way that skips it (e.g. run it in a non-main
   thread's loop — Crawlee only installs when `current_thread() is main_thread()`), and drive
   interruption solely through the shared `shutdown` `asyncio.Event`.
2. In `_wait_or_interrupt`, drop the SIGINT handler entirely; have the CLI install *one* SIGINT handler
   in `CrawlScheduler.start()` (next to SIGTERM) that sets `_shutdown`, so Ctrl+C and SIGTERM share the
   same path and the count of workers is irrelevant.
3. Moving the crawler out of the API process (see `ISSUE_NO_CRAWL_LIMITS_UNBOUNDED_MEMORY.md`) removes
   the uvicorn half of the problem structurally.
