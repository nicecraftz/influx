# 13 routes are `pass` stubs that answer `200 null`, including DELETE and password reset

**Priority: medium**

## Problem

Every handler in `organization/routes.py` (8 routes) and `user/routes.py` (4 routes) plus
`POST /auth/reset-password` (`auth/routes.py:19-21`) has a `pass` body. They are mounted, appear in
`/docs`, and return `200 OK` with body `null`. A client calling `DELETE /api/v1/users/7` or
`PATCH /organizations/3/links/9 {"enabled": true}` gets a success code while nothing happened; a
password-reset flow "succeeds" without doing anything. `/users/*` also has no authorization beyond
"any valid token" (RLS would silently narrow the rows, but the stubs never query).

## Approach

Short term (one line each): raise `ProblemDetailsException(status=501, title="Not implemented")` from
every stub, or don't include the routers in `main.py` until they are real, so clients never see a false
200. Long term: implement them — see `ISSUE_ORGANIZATION_API_MISSING.md`, `ISSUE_USERS_API_MISSING.md`,
`ISSUE_PASSWORD_RESET_NOT_IMPLEMENTED.md`.
