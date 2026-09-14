# Readiness probe creates a new Ollama `AsyncClient` (httpx pool) every 15 s and never closes it

**Priority: low**

## Problem

`_check_ollama` (`core/health.py:58-65`) does `AsyncClient(host=OLLAMA_HOST).list()` on every call. Each
`ollama.AsyncClient` owns an `httpx.AsyncClient` with its own connection pool; it is dropped without
`aclose()`, so sockets are released only when the GC gets to it, with httpx "Unclosed client" warnings.
Compose hits the probe every 15 s and any load balancer will too; over days this is a slow leak and log
noise, not an outage.

## Approach

Reuse one module-level client (as `embedding_service.py`/`answer_service.py` already do, ideally the same
instance) or `async with AsyncClient(...) as client:`; give it the probe timeout instead of wrapping in
`asyncio.timeout`.
