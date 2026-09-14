from datetime import datetime
from http import HTTPStatus

from influx.core.exceptions import ProblemDetailsException
from influx.core.time import utcnow


class CrawlNotFound(ProblemDetailsException):
    status = HTTPStatus.NOT_FOUND
    type = "tag:influx,2026:crawl-not-found"
    title = "Crawl not found"


class CrawlRefused(ProblemDetailsException):
    """The organization cannot be crawled right now (see application/policy.py)."""


class CrawlTooSoon(CrawlRefused):
    status = HTTPStatus.TOO_MANY_REQUESTS
    type = "tag:influx,2026:crawl-too-soon"
    title = "Organization already crawled within the interval"

    def __init__(self, next_allowed_at: datetime, detail: str | None = None) -> None:
        # RFC 6585 §4: Retry-After says when the client may try again.
        wait = max(0, int((next_allowed_at - utcnow()).total_seconds()))
        super().__init__(detail, headers={"Retry-After": str(wait)}, next_allowed_at=next_allowed_at.isoformat())


class NoEnabledLinks(CrawlRefused):
    status = HTTPStatus.CONFLICT
    type = "tag:influx,2026:no-enabled-links"
    title = "No enabled links to crawl"
