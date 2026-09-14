# `POST /auth/reset-password` is a public no-op

**Priority: low**

## Problem

`reset_password()` in `auth/application/service.py:20-21` is `pass`; the route (`auth/routes.py:19-21`)
takes no body and returns `200 null`. There is no way to recover an account, and invited users
(`hashed_password IS NULL`, see `user/domain/models.py:20-22`) can never log in. The endpoint is also
unauthenticated and unthrottled, so once real it becomes an email-bombing / user-enumeration surface.

## Approach

1. `POST /auth/reset-password {email}` → always 202, regardless of whether the email exists; if it does,
   store `sha256(token)` + expiry (15 min) on the user (or a `PasswordReset` table) and send the raw token
   by email (needs an SMTP config; log it in development).
2. `POST /auth/reset-password/confirm {token, password}` → verify hash + expiry, set the new hash, clear
   the token, bump `token_version` so old JWTs die.
3. Rate limit both per IP and per email (`ISSUE_LOGIN_BLOCKS_EVENT_LOOP_NO_RATE_LIMIT.md`), constant
   response time.
4. Reuse for invitations: the same token lets a NULL-password user choose their first password.
