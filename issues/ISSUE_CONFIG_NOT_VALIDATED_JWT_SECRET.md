# Configuration is not validated at startup: empty JWT secret, bad `INFLUX_ENV`, out-of-range values

**Priority: medium**

## Problem

`core/config.py` reads everything with `getenv` and no checks; `main.py:24` reads the JWT secret with
`Path.read_bytes()` and uses whatever comes back:
- an empty or short `secret.key` (e.g. created with `touch`) is accepted → HS256 tokens signed with a
  trivial key can be forged for any `sub`, i.e. any user (the README's `head -c 64 /dev/urandom | base64`
  is fine, but nothing enforces it);
- `JWT_ALGORITHM` is free text (`none`, `RS256` with a symmetric file → encode/decode failures at runtime);
- `INFLUX_ENV` typo (`prod`) selects development logging, which in the container tries to create
  `/app/logs` as the non-root user → `PermissionError`, API does not start;
- `EMBEDDING_DIMENSIONS`, `CHUNK_OVERLAP_WORDS`, `JWT_TTL_MINUTES`, `DB_PORT` cast with `int()` → an
  unrelated traceback at import; `overlap >= max_words` only fails inside `chunkify_text` on the first page;
- `Path.read_bytes()` is a blocking call in the async lifespan (ruff ASYNC240), harmless but flagged.

## Approach

- A single `validate()` in `core/config.py` (or `pydantic-settings`, already installed as a transitive
  dependency) run at import: enum for `INFLUX_ENV`, `JWT_ALGORITHM in {"HS256","HS384","HS512"}`,
  positive ints, `0 <= CHUNK_OVERLAP_WORDS < MAX_WORDS_PER_CHUNK`, `256 <= EMBEDDING_DIMENSIONS <= 768`.
- In the lifespan: `secret = path.read_bytes().strip()`; require `len(secret) >= 32` bytes, else refuse to
  start with a clear message. Read it with `asyncio.to_thread` or before the loop starts.
- Warn (or refuse in production) on default DB credentials
  (`ISSUE_POSTGRES_EXPOSED_DEFAULT_CREDENTIALS.md`).
