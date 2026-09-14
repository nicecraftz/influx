# Organization, membership, crawl-rule and link management exist only as SQL

**Priority: medium**

## Problem

There is no way to create an organization, invite/remove members, change roles, add `CrawlRule`s or
enable a discovered `Link` except with `psql` (README "Utente e organizzazione"). The models and RLS
policies are ready; the routes in `organization/routes.py` are stubs. Practical consequences: subdomains
found by crawls stay disabled forever, crawler traps cannot be excluded without shell access to the DB,
`OrganizationDeactivation` is never written, `Organization.active` can never change.

Things RLS does **not** enforce and the service layer must (see `core/rls.py` policies):
- `participation` write is `ADMIN`-wide: an ADMIN could promote themselves to SUPER_ADMIN, add anyone as
  SUPER_ADMIN, or delete the last SUPER_ADMIN. Role hierarchy and "at least one SUPER_ADMIN" are
  application rules.
- `organization` write lets an ADMIN change `domain`: crawls would then leave the tenant's scope
  (see `ISSUE_CRAWLER_FOLLOWS_REDIRECTS_OFF_SITE_SSRF.md`). `domain` must be immutable or SUPER_ADMIN +
  validated.
- `link.url` is trusted as a crawl root: enabling must be the only allowed change; creation must
  validate `registrable_domain(host) == organization.domain`.
- `crawlrule.regex` is compiled with `re.compile` at crawl start (`storage.py:41`, `service.py:76`): an
  invalid pattern fails every crawl of the organization with an opaque error, and a pathological one
  (`(a+)+$`) blocks the event loop on every URL (ReDoS) — the 200-char cap does not prevent that.
  Validate at insert (compile, reject nested quantifiers or use the `regex` module with a timeout, dry-run
  against a sample of the org's URLs).
- Creating an organization under RLS is impossible for the API role (`WITH CHECK id IN admin orgs`), so
  creation needs a system session or an operator CLI (`influx create-organization`).

## Approach

Implement, in this order, with a service module (`organization/application/service.py`) that owns the
rules above:
1. `GET /organizations`, `GET /organizations/{id}` (safe read schemas, never the table models).
2. `GET/POST/DELETE /organizations/{id}/members` with role checks (`SuperAdmin` for role changes,
   cannot remove the last SUPER_ADMIN, cannot self-promote).
3. `GET/POST/DELETE /organizations/{id}/rules` with regex validation.
4. `GET /organizations/{id}/links`, `PATCH …/links/{link_id}` (enabled only).
5. `PATCH /organizations/{id}` (name only) and `POST /organizations/{id}/deactivation`
   (writes `OrganizationDeactivation`, processed by an operator CLI that flips `active`).
6. `influx create-organization` / `create-user` CLI for bootstrap instead of the SQL recipe.
