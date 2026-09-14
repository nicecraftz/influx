from http import HTTPStatus

from influx.core.exceptions import ProblemDetailsException


class InvalidCredentialsException(ProblemDetailsException):
    status = HTTPStatus.UNAUTHORIZED
    type = "/login"
    title = "Invalid Credentials"
    detail = "You have inserted the wrong credentials, maybe your password is wrong?"


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
