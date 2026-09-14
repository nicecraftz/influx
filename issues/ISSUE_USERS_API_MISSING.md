# User endpoints are stubs; when implemented they must not leak `hashed_password` or orphan organizations

**Priority: low**

## Problem

`user/routes.py` has four stubs (`GET /users`, `GET /users/{id}`, `PATCH`, `DELETE`). Points to settle
before implementing, because the naive version is wrong:
- Returning `User` (the table model) serialises `hashed_password`; the RLS `user` read policy lets any
  member see everyone who shares an organization with them, so the leak would be cross-user.
- `DELETE /users/{id}`: `Participation` cascades, so deleting the only SUPER_ADMIN leaves an organization
  nobody administers; `Crawl.requested_by_user_id` / `Question.user_id` become NULL (fine).
- `PATCH` must not allow `email` changes without re-verification, must hash `password`, and must bump
  the token version (`ISSUE_DEACTIVATED_USER_KEEPS_VALID_TOKEN.md`).
- There is no registration or invitation: a user can only be inserted by SQL with a bcrypt hash produced
  by hand.

## Approach

- `UserRead` schema (`id, name, last_name, email, is_active, created_at`) and `UserUpdate`
  (`name, last_name, password`) in `user/schemas.py`; never return the model.
- `GET /users/me`, `PATCH /users/me`, `DELETE /users/me` (self-service; RLS write policy already limits
  writes to self), `GET /users/{id}` limited to shared-org members (already what RLS returns).
- Deletion: refuse (409) while the user is the last SUPER_ADMIN of any organization.
- Invitation flow: `POST /organizations/{id}/members` with an email creates a `User` with
  `hashed_password = NULL` + a one-time token; the user sets the password through the reset endpoint
  (`ISSUE_PASSWORD_RESET_NOT_IMPLEMENTED.md`).
