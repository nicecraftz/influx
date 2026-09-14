from http import HTTPStatus

from influx.core.exceptions import ProblemDetailsException


class OrganizationNotFound(ProblemDetailsException):
    status = HTTPStatus.NOT_FOUND
    type = "tag:influx,2026:organization-not-found"
    title = "Organization not found"


class OrganizationInactive(ProblemDetailsException):
    status = HTTPStatus.CONFLICT
    type = "tag:influx,2026:organization-inactive"
    title = "Organization is inactive"
