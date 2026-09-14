# Engine uses pool defaults: no `pool_pre_ping`, no sizing, no statement timeout

**Priority: low**

## Problem

`create_async_engine(DATABASE_URL)` (`core/db.py:21`) leaves everything at defaults. After a Postgres
restart or a dropped connection the next up-to-15 requests fail with `ConnectionDoesNotExistError` before
the pool recycles them. There is no `statement_timeout`/`lock_timeout`, so a runaway query (or the DDL
lock described in `ISSUE_DDL_ON_EVERY_CLI_COMMAND_LOCKS_API.md`) blocks indefinitely, and no
`application_name`, so `pg_stat_activity` cannot tell the API from the CLI from the crawler. The same
engine is shared by the API and the in-process crawler/ingestion, so a batch flush competes with requests
for the same 15 connections.

## Approach

```python
engine = create_async_engine(
    DATABASE_URL,
    pool_pre_ping=True,
    pool_size=DB_POOL_SIZE, max_overflow=DB_MAX_OVERFLOW, pool_timeout=10,
    connect_args={"server_settings": {
        "application_name": f"influx-{role}",
        "statement_timeout": "30000", "lock_timeout": "5000",
    }},
)
```
with the values in `config.py`; a longer `statement_timeout` for the CLI/ingestion connections
(`SET LOCAL` in the ingestion sessions). Expose pool stats on `/health/ready`.
