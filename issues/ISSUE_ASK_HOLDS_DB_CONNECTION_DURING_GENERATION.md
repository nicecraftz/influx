# Retrieval holds a DB connection for the whole LLM generation → pool exhaustion → container restart

**Priority: high**

## Problem

`POST /api/v1/retrieval/organizations/{id}` (`src/influx/retrieval/application/answer_service.py:52-73`) runs
`search_passages` on the request's `SessionDep`, which opens a transaction (`SET LOCAL hnsw.iterative_scan`,
the RLS `set_config` in `after_begin`), and then **awaits `generate_answer()` with the transaction still open**.
With `qwen3:8b` a generation takes seconds to tens of seconds, and Ollama serves requests mostly serially.

The engine uses SQLAlchemy defaults (`pool_size=5`, `max_overflow=10`, `pool_timeout=30`): 15 concurrent
questions hold all 15 connections. Every other request then waits on the pool, including
`GET /health/ready`, whose DB check has a 5 s `asyncio.timeout` (`core/health.py:50`) → 503 → after 5 failed
probes (~75 s) Docker Compose restarts the API container, killing every crawl in progress.

On top of that the Ollama client has **no timeout** (`AsyncClient(host=OLLAMA_HOST)` → httpx timeout `None`,
`answer_service.py:25`, `embedding_service.py:15`): a hung Ollama keeps the request, its connection and the
transaction open forever.

Any member of any organization can trigger this with a loop of 15 questions; no rate limit exists.

## Approach

1. Do not hold the session across the generation:
   - `search_passages` with the RLS session, then `await session.commit()` (or run the search in its own
     short transaction) **before** calling `generate_answer`;
   - insert the `Question` row in a fresh transaction afterwards.
2. Give the Ollama clients a timeout (`AsyncClient(host=..., timeout=httpx.Timeout(60.0, connect=5.0))`) and
   map `httpx.TimeoutException` to `AnswerUnavailable` (504 or 503).
3. Bound concurrency towards Ollama with an `asyncio.Semaphore` (e.g. 4) and fail fast with 503 +
   `Retry-After` when it is saturated, instead of queueing unboundedly.
4. Add a per-user rate limit on `ask` (see `ISSUE_LOGIN_BLOCKS_EVENT_LOOP_NO_RATE_LIMIT.md`).
5. Size the pool explicitly and make the readiness probe not depend on a free pool connection (or give the
   probe its own tiny pool / `NullPool` engine) so a busy API is not reported as dead.
