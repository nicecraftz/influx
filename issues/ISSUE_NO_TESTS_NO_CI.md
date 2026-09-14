# Zero automated tests and no CI

**Priority: low**

## Problem

There is no `tests/` directory, no `pytest` in the dependencies, and no CI workflow. Everything above was
found by reading; regressions like the `ConnectionError` mapping, the RLS scope switch, the login
constant-time path or `chunkify_text` edge cases will come back unnoticed. The pure functions
(`SiteScope`, `UrlRules`, `chunkify_text`, `extract_text`, `ProblemDetailsException`) are cheap to test
today; the RLS policies are the one part that *must* be tested against a real Postgres, since a wrong
policy is a cross-tenant leak that no unit test will catch.

## Approach

1. `uv add --dev pytest pytest-asyncio httpx testcontainers[postgres]` (or a compose service in CI).
2. Unit tests for `crawler/application/service.py`, `ingestion/application/chunk_service.py`,
   `core/exceptions.py`, `auth/application/tokens.py`.
3. Integration tests with the app on a pgvector container: login (401/422/200), RLS isolation
   (user of org A gets 404 on org B's crawl, 403 on its routes), `ask` with a fake Ollama (`respx`),
   readiness 503 when Ollama is down.
4. GitHub Actions: `ruff check`, `pytest`, `docker build`.
