"""Problem Details for HTTP APIs (RFC 9457, which obsoletes RFC 7807).

Raise `ProblemDetailsException` (or a subclass) anywhere in a request and the
handler installed by `register_problem_handlers` turns it into an
`application/problem+json` response. Subclasses usually only override the
class attributes:

    class OrganizationNotFound(ProblemDetailsException):
        status = 404
        type = "tag:influx,2026:organization-not-found"
        title = "Organization not found"

    raise OrganizationNotFound(detail=f"no organization with id {org_id}")

RFC 9457 §3.1.1: `type` need not be dereferenceable; a `tag:` URI is fine
until there is a documentation page to point at. Per §3.1.4, keep `detail`
focused on helping the client fix the request, not on debugging information.
"""

import re
from http import HTTPStatus
from typing import Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

PROBLEM_MEDIA_TYPE = "application/problem+json"

# RFC 9457 §4.2.1: "about:blank" means the problem has no semantics beyond the
# HTTP status code, so the title is the status reason phrase.
BLANK_TYPE = "about:blank"

# RFC 9457 §3.2: extension member names SHOULD start with a letter, consist of
# ALPHA / DIGIT / "_" and be at least three characters long, so they can be
# serialised in formats other than JSON. Enforced at raise time since the
# names are chosen by our own code, never by clients.
_EXTENSION_NAME = re.compile(r"[A-Za-z][A-Za-z0-9_]{2,}")


class ProblemDetailsException(Exception):
    status: int = HTTPStatus.INTERNAL_SERVER_ERROR
    type: str = BLANK_TYPE
    title: str | None = None
    detail: str | None = None
    headers: dict[str, str] | None = None

    def __init__(
        self,
        detail: str | None = None,
        *,
        status: int | None = None,
        type: str | None = None,
        title: str | None = None,
        instance: str | None = None,
        headers: dict[str, str] | None = None,
        **extensions: Any,
    ):
        if status is not None:
            self.status = status
        if type is not None:
            self.type = type
        if title is not None:
            self.title = title
        if detail is not None:
            self.detail = detail
        if headers is not None:
            self.headers = headers
        self.instance = instance
        invalid = [name for name in extensions if not _EXTENSION_NAME.fullmatch(name)]
        if invalid:
            raise TypeError(f"extension member names must match {_EXTENSION_NAME.pattern}: {invalid}")
        self.extensions = extensions
        super().__init__(self.detail or self.resolved_title)

    @property
    def resolved_title(self) -> str:
        if self.title is not None:
            return self.title
        return HTTPStatus(self.status).phrase

    def to_dict(self) -> dict[str, Any]:
        problem: dict[str, Any] = {
            "type": self.type,
            "title": self.resolved_title,
            "status": int(self.status),
        }
        if self.detail is not None:
            problem["detail"] = self.detail
        if self.instance is not None:
            problem["instance"] = self.instance
        problem.update(self.extensions)
        return problem

    def to_response(self, request: Request | None = None) -> JSONResponse:
        # RFC 9457 §3.1.5: a relative `instance` is resolved against the
        # request URI, so an absolute path is the recommended form.
        if self.instance is None and request is not None:
            self.instance = request.url.path
        # §3.1.2: `status` is advisory, the real status code MUST be the same.
        return JSONResponse(
            status_code=self.status,
            content=self.to_dict(),
            media_type=PROBLEM_MEDIA_TYPE,
            headers=self.headers,
        )


class ValidationProblem(ProblemDetailsException):
    """RFC 9457 §3: several problems of the same type are conveyed as one
    problem details object listing them in an extension member (`errors`)."""

    status = HTTPStatus.UNPROCESSABLE_CONTENT
    type = "tag:influx,2026:request-validation-failed"
    title = "Request validation failed"


async def _problem_handler(request: Request, exc: ProblemDetailsException) -> JSONResponse:
    return exc.to_response(request)


async def _http_exception_handler(request: Request, exc: HTTPException) -> JSONResponse:
    detail = exc.detail if isinstance(exc.detail, str) else None
    return ProblemDetailsException(detail, status=exc.status_code, headers=exc.headers).to_response(request)


async def _validation_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
    return ValidationProblem(errors=exc.errors()).to_response(request)


def register_problem_handlers(app: FastAPI) -> None:
    """Make every error the app emits a problem+json document, including the
    HTTPException and validation errors FastAPI raises on its own."""
    app.add_exception_handler(ProblemDetailsException, _problem_handler)
    app.add_exception_handler(HTTPException, _http_exception_handler)
    app.add_exception_handler(RequestValidationError, _validation_handler)
