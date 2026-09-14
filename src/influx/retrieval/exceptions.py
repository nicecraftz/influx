from http import HTTPStatus

from influx.core.exceptions import ProblemDetailsException


class NothingIndexed(ProblemDetailsException):
    """The organization has no embedded content yet: nothing to answer from."""

    status = HTTPStatus.CONFLICT
    type = "tag:influx,2026:nothing-indexed"
    title = "No indexed content to answer from"


class AnswerUnavailable(ProblemDetailsException):
    """Ollama could not be reached or refused the request."""

    status = HTTPStatus.SERVICE_UNAVAILABLE
    type = "tag:influx,2026:answer-unavailable"
    title = "Answering service unavailable"
