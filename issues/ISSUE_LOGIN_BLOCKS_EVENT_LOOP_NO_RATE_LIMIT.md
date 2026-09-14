# Login runs bcrypt synchronously on the event loop and has no brute-force protection

**Priority: high**

## Problem

`check_password` (`src/influx/auth/application/password.py:19-24`) calls `bcrypt.checkpw` (≈250 ms at cost 12)
directly inside the async route (`auth/application/service.py:14`). Nothing in the call is awaited, so the
event loop is blocked for the whole hash: the single uvicorn worker cannot serve *any* other request
(health probes included) while a login is being checked. Unauthenticated `POST /auth/login` at ~5 req/s is
enough to make the API unresponsive; the constant-time dummy hash makes unknown emails just as expensive.

Independently, there is no rate limiting, lockout or CAPTCHA, so online password guessing is only limited
by bcrypt's speed (~4 attempts/s/core).

`POST /auth/reset-password` is public and unbounded too (currently a no-op, see
`ISSUE_STUB_ENDPOINTS_RETURN_200_NULL.md`).

## Approach

1. Run the hash off the loop: `await asyncio.to_thread(bcrypt.checkpw, ...)` (bcrypt releases the GIL, so
   threads scale) and bound concurrency with a semaphore (e.g. `cpu_count()`), returning 503 + `Retry-After`
   beyond that.
2. Add rate limiting on `/auth/login` (and later `/auth/reset-password`, `retrieval/ask`): per IP and per
   email, e.g. token bucket in memory (single process today) — `slowapi` or a small dependency —
   answering 429 with `Retry-After`. Use `X-Forwarded-For` only when behind a trusted proxy.
3. Optional: progressive delay / temporary lockout after N failures per email, logged with the source IP.
