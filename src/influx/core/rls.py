"""Row-level security: tenant isolation enforced by Postgres, not by WHERE clauses.

How it works
------------
Every table gets `ENABLE ROW LEVEL SECURITY` and a pair of policies expressed
in terms of two SQL functions:

    influx_member_organizations()  -> ids of the organizations the current
                                      request's user belongs to
    influx_admin_organizations()   -> the subset where the user is ADMIN

The "current request's user" is the transaction-local setting
`influx.user_id`, written by `scope_to_user()` once the JWT is verified
(see auth/dependencies.py). The functions are SECURITY DEFINER so they can
read `participation` without hitting its own policy (which would recurse).

Who is subject to it
--------------------
Postgres exempts table owners and superusers from RLS, and the app connects
as the owner (DB_USER). So API sessions (`core.db.get_session`) switch every
transaction to DB_API_ROLE, a NOLOGIN role that owns nothing, with

    SELECT set_config('role', 'influx_api', true), set_config('influx.user_id', '<id>', true)

The third argument makes both settings transaction-local: they vanish at
COMMIT/ROLLBACK, so a pooled connection never leaks a scope into the next
request. The switch is re-issued on every transaction the session begins
(`after_begin` event), including the ones after a commit inside a route.

Before a user is known the role is switched but `influx.user_id` is empty, so
every policy evaluates to NULL and the API sees no rows at all: an
unauthenticated request cannot read tenant data even if a route forgets its
dependencies. `/auth/login` is the one route that legitimately reads before
authentication and uses `SystemSessionDep` (owner, unscoped) for that.

The CLI, the crawler and the embedding job open `async_session()` directly,
never switch role, and therefore bypass RLS as before.

This is defence in depth against a route that forgets a WHERE clause or a
membership check, not a sandbox against the app's own SQL: a session can
always `SET ROLE` back to its login role.

Adding a table
--------------
`apply_row_level_security` refuses to run when a table in the metadata has no
entry in `POLICIES`, so a new tenant table cannot be shipped without deciding
who reads it. Write the policy as a pair of SQL boolean expressions
(read, write) over the row's columns; `None` for write means the API can only
read it (writes happen from the CLI or a system session).

Only Postgres is supported; on other dialects the function is a no-op.
"""

from sqlalchemy import event, text
from sqlalchemy.ext.asyncio import AsyncConnection
from sqlalchemy.orm import Session
from sqlmodel import SQLModel
from sqlmodel.ext.asyncio.session import AsyncSession

from influx.core.config import DB_API_ROLE

# session.info key. Present  -> API session: switch role on every transaction.
# Value: the user id once authenticated, None while anonymous.
SCOPE_KEY = "influx.user_id"

_MEMBER = "organization_id IN (SELECT influx_member_organizations())"
_ADMIN = "organization_id IN (SELECT influx_admin_organizations())"

# table name -> (read predicate, write predicate or None). Both are USING /
# WITH CHECK expressions evaluated per row, so they may reference columns.
POLICIES: dict[str, tuple[str, str | None]] = {
    "organization": (
        "id IN (SELECT influx_member_organizations())",
        "id IN (SELECT influx_admin_organizations())",
    ),
    "participation": (_MEMBER, _ADMIN),
    "organizationdeactivation": (_MEMBER, _ADMIN),
    "crawl": (_MEMBER, _ADMIN),
    "crawlrule": (_MEMBER, _ADMIN),
    "link": (_MEMBER, _ADMIN),
    "page": (_MEMBER, _ADMIN),
    "document": (_MEMBER, _ADMIN),
    "contentchunk": (_MEMBER, _ADMIN),
    # A user sees itself and whoever shares an organization with it; it can
    # only change itself. Registration (INSERT) is not an API concern yet.
    "user": (
        "id = influx_current_user_id() OR id IN ("
        "SELECT user_id FROM participation WHERE " + _MEMBER + ")",
        "id = influx_current_user_id()",
    ),
}

# asyncpg prepares each execute as a single statement, hence one string each.
_SETUP = (
    """
    CREATE OR REPLACE FUNCTION influx_current_user_id() RETURNS integer
    LANGUAGE sql STABLE AS $$
        SELECT nullif(current_setting('influx.user_id', true), '')::integer
    $$
    """,
    """
    CREATE OR REPLACE FUNCTION influx_member_organizations() RETURNS SETOF integer
    LANGUAGE sql STABLE SECURITY DEFINER SET search_path = pg_catalog, public AS $$
        SELECT organization_id FROM participation
        WHERE user_id = influx_current_user_id()
    $$
    """,
    """
    CREATE OR REPLACE FUNCTION influx_admin_organizations() RETURNS SETOF integer
    LANGUAGE sql STABLE SECURITY DEFINER SET search_path = pg_catalog, public AS $$
        SELECT organization_id FROM participation
        WHERE user_id = influx_current_user_id() AND role IN ('ADMIN', 'SUPER_ADMIN')
    $$
    """,
    f"""
    DO $$
    BEGIN
        IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '{DB_API_ROLE}') THEN
            CREATE ROLE {DB_API_ROLE} NOLOGIN NOBYPASSRLS;
        END IF;
    END
    $$
    """,
    f"GRANT {DB_API_ROLE} TO CURRENT_USER",
    f"GRANT USAGE ON SCHEMA public TO {DB_API_ROLE}",
    f"GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO {DB_API_ROLE}",
)

_SET_SCOPE = text("SELECT set_config('role', :role, true), set_config('influx.user_id', :user_id, true)")


async def apply_row_level_security(connection: AsyncConnection) -> None:
    """Create the API role, the helper functions and one policy set per table.

    Idempotent; meant to run right after `create_all` in the same transaction.
    """
    if connection.dialect.name != "postgresql":
        return
    tables = {table.name: table for table in SQLModel.metadata.sorted_tables}
    missing = sorted(tables.keys() - POLICIES.keys())
    if missing:
        raise RuntimeError(f"tables without a row-level security policy in core/rls.py: {missing}")

    for statement in _SETUP:
        await connection.execute(text(statement))
    for name, (read, write) in POLICIES.items():
        if name not in tables:
            continue
        quoted = f'"{name}"'  # "user" is a reserved word
        await connection.execute(text(f"GRANT SELECT, INSERT, UPDATE, DELETE ON {quoted} TO {DB_API_ROLE}"))
        await connection.execute(text(f"ALTER TABLE {quoted} ENABLE ROW LEVEL SECURITY"))
        # Permissive policies are OR-ed per command: SELECT gets `read`,
        # INSERT/UPDATE/DELETE get `write` (FOR ALL also covers SELECT, which
        # is fine since write implies read for every entry above).
        await connection.execute(text(f"DROP POLICY IF EXISTS {name}_read ON {quoted}"))
        await connection.execute(text(f"CREATE POLICY {name}_read ON {quoted} FOR SELECT USING ({read})"))
        await connection.execute(text(f"DROP POLICY IF EXISTS {name}_write ON {quoted}"))
        if write is not None:
            await connection.execute(
                text(f"CREATE POLICY {name}_write ON {quoted} FOR ALL USING ({write}) WITH CHECK ({write})")
            )


def mark_api_session(session: AsyncSession) -> None:
    """Make every transaction of this session run as DB_API_ROLE (no user yet)."""
    session.info[SCOPE_KEY] = None


async def scope_to_user(session: AsyncSession, user_id: int) -> None:
    """Attach the authenticated user to the session: policies now see their rows.

    Applies to the transaction already open, if any, and to every later one.
    """
    session.info[SCOPE_KEY] = user_id
    if session.in_transaction():
        await session.execute(_SET_SCOPE, _scope_params(user_id))


def _scope_params(user_id: int | None) -> dict[str, str]:
    return {"role": DB_API_ROLE, "user_id": "" if user_id is None else str(user_id)}


@event.listens_for(Session, "after_begin")
def _switch_role(session: Session, transaction, connection) -> None:
    # Fires on the sync session under the AsyncSession, inside its greenlet,
    # so a plain execute on the connection is the right call here.
    if SCOPE_KEY not in session.info:
        return
    connection.execute(_SET_SCOPE, _scope_params(session.info[SCOPE_KEY]))
