# Deactivated users keep a working token; no revocation, no refresh

**Priority: medium**

## Problem

`login` refuses `is_active == False` (`auth/application/service.py:16`), but `get_current_user`
(`auth/dependencies.py:46-62`) only checks that the `User` row exists. A user deactivated (or whose
password is reset, once that exists) keeps full access for the remaining `JWT_TTL_MINUTES` (30 min),
and there is no way to revoke a leaked token short of rotating `secret.key` for everyone.
`Organization.active` is likewise only enforced in `request_crawl`/`answer_question`, not at membership
level, so an inactive organization's crawls list and metrics still serve.

Related: with a 30 min TTL and no refresh token, every client must store the password or re-prompt
every half hour, which pushes integrators towards long TTLs.

## Approach

1. In `get_current_user`, raise `NotAuthenticated` when `not user.is_active`.
2. Add a `token_version` (or `password_changed_at`) column on `User`, embed it in the JWT and compare on
   every request: bumping it invalidates all tokens of that user (password reset, deactivation, "log out
   everywhere").
3. Add `POST /auth/refresh` issuing a new access token from a longer-lived refresh token (stored hashed
   in DB, rotated on use), keep access TTL short.
4. Make `require_membership` (or a router-level dependency) reject inactive organizations with 409 so the
   check is not repeated per service.
