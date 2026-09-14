# No schema migrations: `create_all` silently leaves existing databases out of date

**Priority: medium**

## Problem

The schema is applied with `SQLModel.metadata.create_all` (`core/db.py:28`), which only creates *missing
tables*. Columns added recently (`Page.title`, `Document.text/text_hash/converted_at/conversion_error`,
`Crawl.requests_finished…links/error/link_id/requested_by_user_id`, `Organization.domain/active`,
`ContentChunk.organization_id` + HNSW index) are not added to a database created before them; the API
then fails at runtime with `UndefinedColumnError` on the first query touching them. The README's only
answer is `docker compose down -v`, i.e. drop all crawled data. `SAEnum(CrawlStatus)`/`SAEnum(Role)`
create Postgres enum types that also cannot gain values without a migration. Changing
`EMBEDDING_DIMENSIONS` changes the `vector(n)` column type silently in code only.

## Approach

1. Add Alembic (`uv add alembic`), `alembic init -t async`, point `env.py` at `SQLModel.metadata` and
   `DATABASE_URL`; generate the baseline from the current models; from then on every model change ships
   with `alembic revision --autogenerate`.
2. `influx init-db` → `alembic upgrade head` + the RLS statements as a migration step (they are
   idempotent).
3. Record `EMBEDDING_DIMENSIONS`/model name in a `settings` table or in the migration so a mismatch is
   detected at startup instead of producing garbage similarities.
