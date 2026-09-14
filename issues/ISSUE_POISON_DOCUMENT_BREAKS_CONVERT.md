# One document that crashes a worker aborts `convert` for the whole organization, forever

**Priority: medium**

## Problem

`_convert_one` re-raises `BrokenProcessPool` (`ingestion/application/document_service.py:110-114`) and
`convert_documents` runs every pending document through the same pool with `asyncio.gather`. When a worker
dies (OOM on a DOCX zip bomb, a segfault in pdfium — both realistic with attacker-supplied files from a
crawled site), *all* in-flight conversions fail with `BrokenProcessPool`, the run stops, and the
offending document keeps `text_hash = NULL`, so it is pending again next time and kills the next run
too. The SIGALRM timeout does not help: it is only delivered between Python bytecodes, and OOM is not a
timeout. Result: one bad file and no document of that organization is ever converted again.

## Approach

1. Mark the document as failed when the pool breaks (`conversion_error = "worker crashed"`), rebuild the
   pool, and continue with the remaining documents; count them in `stats.failed`.
2. Track the document currently assigned per worker (or run one document per fresh process for large
   blobs) so the culprit can be identified with certainty.
3. Put a memory ceiling on workers (`resource.setrlimit(RLIMIT_AS)` in an initializer) so a zip bomb
   raises `MemoryError` inside the worker instead of triggering the OOM killer on the container.
4. Add a per-document attempt counter so a document that failed N times is skipped without `--force`.
