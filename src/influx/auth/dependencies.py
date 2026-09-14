"""Request-level authentication and authorization.

    CurrentUser  -> the User behind the bearer token (401 otherwise)
    Member       -> the caller's Participation in the organization named by
                    the `{id}` path parameter (403 otherwise)
    Admin        -> same, but the role must be ADMIN

Use them as parameter annotations when the route needs the object, or in the
router/route `dependencies=[...]` list when it only needs the check:

    @organizations.get("/{id}")
    async def get_organization(id: int, membership: Member, session: SessionDep): ...

    crawler = APIRouter(prefix="/crawler", dependencies=[Depends(get_current_user)])

`require_membership` builds the dependency for other path parameter names or
roles: `Depends(require_membership(Role.ADMIN, param="organization_id"))`.

Besides checking, `get_current_user` scopes the request's DB session to the
user (core/rls.py), so any later query in the route only sees that user's
organizations whatever its WHERE clause says.
"""

from typing import Annotated

from fastapi import Depends, Path, Request
from fastapi.security import OAuth2PasswordBearer
from jwt import InvalidTokenError

from influx.auth.application.tokens import decode_token
from influx.auth.exceptions import InsufficientRole, NotAMember, NotAuthenticated
from influx.core.db import SessionDep
from influx.core.rls import scope_to_user
from influx.organization.domain.models import Participation, Role
from influx.user.domain.models import User

bearer = OAuth2PasswordBearer(tokenUrl="/api/v1/auth/login", auto_error=False)

_ROLE_RANK = {Role.VIEWER: 0, Role.ADMIN: 1, Role.SUPER_ADMIN: 2}

def get_private_key(request: Request) -> bytes:
    return request.state.private_key

PrivateKeyDep = Annotated[bytes, Depends(get_private_key)]

async def get_current_user(
    token: Annotated[str | None, Depends(bearer)],
    session: SessionDep,
    private_key: PrivateKeyDep,
) -> User:
    if token is None:
        raise NotAuthenticated()
    try:
        user_id = int(decode_token(token, private_key)["sub"])
    except (InvalidTokenError, KeyError, ValueError, TypeError):
        raise NotAuthenticated() from None

    await scope_to_user(session, user_id)
    user = await session.get(User, user_id)
    if user is None:
        raise NotAuthenticated()
    return user


CurrentUser = Annotated[User, Depends(get_current_user)]


def require_membership(role: Role | None = None, *, param: str = "id"):
    """Dependency: the caller belongs to organization `{param}` with at least `role`."""

    async def dependency(
        organization_id: Annotated[int, Path(alias=param)],
        user: CurrentUser,
        session: SessionDep,
    ) -> Participation:
        participation = await session.get(Participation, (organization_id, user.id))
        if participation is None:
            raise NotAMember(f"user {user.id} is not a member of organization {organization_id}")
        if role is not None and _ROLE_RANK[participation.role] < _ROLE_RANK[role]:
            raise InsufficientRole(
                f"organization {organization_id} requires role {role.value}, you have {participation.role.value}"
            )
        return participation

    return dependency


Member = Annotated[Participation, Depends(require_membership())]
Admin = Annotated[Participation, Depends(require_membership(Role.ADMIN))]
SuperAdmin = Annotated[Participation, Depends(require_membership(Role.SUPER_ADMIN))]
