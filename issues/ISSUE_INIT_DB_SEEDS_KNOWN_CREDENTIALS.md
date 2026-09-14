# `init-db` seeds a well-known SUPER_ADMIN account into every database, production included

**Priority: high**

## Problem

`influx init-db` (`src/influx/__init__.py:112-150`) unconditionally creates `mario.rossi@example.com` /
`placeholder` as `SUPER_ADMIN` of an `Esempio` organization, and the README presents it as the standard
setup step. The password is public (README, source), the user is active, and there is no CLI to delete it.
Anyone who can reach the API logs in, consumes Ollama through `retrieval`, queues crawls of
`https://example.com`, and — as soon as the user/member endpoints are implemented — sees whatever those
expose. Default credentials on an internet-facing service is a textbook finding.

`INFLUX_ENV` exists but nothing uses it for this.

## Approach

1. Split seeding from schema creation: `init-db` only creates tables/RLS; add
   `influx seed-example` (refused when `INFLUX_ENV=production` unless `--force`) or drop the example
   entirely.
2. Add the missing operator commands so nobody needs the example: `influx create-user`,
   `influx create-organization --domain … --admin-email …` (see `ISSUE_ORGANIZATION_API_MISSING.md`).
3. If the example must stay for development, generate a random password at seed time and print it once
   instead of a fixed one.
