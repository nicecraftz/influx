# Compose publishes Postgres on all interfaces with `influx/influx` as the default credentials

**Priority: medium**

## Problem

`docker-compose.yml` maps `"${DB_PORT:-5432}:5432"` (all host interfaces) and defaults
`POSTGRES_PASSWORD` to `influx`; `.env.example` ships the same. The `--profile api` deployment described in
the README therefore exposes a superuser-owned database with a guessable password to whatever network the
host is on. `DB_USER` is also the table owner, which bypasses RLS entirely — a leaked DB password is a full
cross-tenant dump.

## Approach

- Bind to loopback by default: `"127.0.0.1:${DB_PORT:-5432}:5432"`, and drop the mapping entirely in the
  `api` profile (the app reaches Postgres on the compose network).
- No default password: `POSTGRES_PASSWORD: ${DB_PASSWORD:?set DB_PASSWORD in .env}`; refuse to start the
  API when `INFLUX_ENV=production` and `DB_PASSWORD == "influx"`.
- Create a separate least-privilege runtime user for the API (`influx_app`, member of `influx_api`,
  no DDL), keep the owner for migrations only (`ISSUE_DDL_ON_EVERY_CLI_COMMAND_LOCKS_API.md`).
