from http import HTTPStatus

from influx.core.exceptions import ProblemDetailsException


class InvalidCredentialsException(ProblemDetailsException):
    status = HTTPStatus.UNAUTHORIZED
    type = "tag:influx,2026:invalid-credentials"
    title = "Invalid credentials"
    detail = "Wrong email or password"
    headers = {"WWW-Authenticate": "Bearer"}


class NotAuthenticated(ProblemDetailsException):
    status = HTTPStatus.UNAUTHORIZED
    type = "tag:influx,2026:not-authenticated"
    title = "Not authenticated"
    detail = "A valid bearer token is required"
    headers = {"WWW-Authenticate": "Bearer"}


class NotAMember(ProblemDetailsException):
    status = HTTPStatus.FORBIDDEN
    type = "tag:influx,2026:not-a-member"
    title = "Not a member of the organization"


class InsufficientRole(ProblemDetailsException):
    status = HTTPStatus.FORBIDDEN
    type = "tag:influx,2026:insufficient-role"
    title = "Insufficient role in the organization"
