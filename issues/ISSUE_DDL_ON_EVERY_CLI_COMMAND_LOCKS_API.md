# Every CLI command and every API start re-runs DDL; running the CLI next to a live API stalls requests

**Priority: medium**

## Problem

`_dispatch` (`src/influx/__init__.py:63`) calls `init_db()` before *any* command — `crawl`, `convert`,
`embed` included — and the API lifespan does the same (`main.py:25`). `init_db` runs `create_all`, then
`apply_row_level_security` (`core/rls.py:134-163`): `ALTER TABLE … ENABLE ROW LEVEL SECURITY`,
`DROP POLICY` / `CREATE POLICY` and `GRANT` on every table, all of which take `ACCESS EXCLUSIVE` locks,
inside one transaction.

Consequences:
- `docker compose run app influx convert …` (the documented way) while the API is serving: the DDL waits
  behind any open API transaction (e.g. a question being generated, see
  `ISSUE_ASK_HOLDS_DB_CONNECTION_DURING_GENERATION.md`), and every new request queues behind the DDL's lock
  request → the API freezes for the duration.
- Two processes starting together (API + CLI, or two API replicas) can deadlock or fail on
  `CREATE ROLE` / `CREATE POLICY` races.
- The app user must own the tables and be able to create roles — in production the runtime role should
  not have DDL rights at all.
- `SQLModel.metadata.create_all` never alters existing tables, so this is not even a migration
  (`ISSUE_NO_MIGRATIONS_CREATE_ALL_ONLY.md`).

## Approach

1. Run DDL only from `influx init-db` (or `influx migrate`); remove `init_db()` from `_dispatch` for the
   other commands and from the API lifespan. At startup, just verify the schema/RLS is present
   (`SELECT relrowsecurity FROM pg_class …`) and fail fast with a clear message if not.
2. Make `apply_row_level_security` skip statements whose effect is already in place (check
   `pg_policies`, `pg_class.relrowsecurity`) so re-running is cheap and lock-free when nothing changed.
3. Long term: Alembic migrations, and a separate least-privilege runtime DB user.
