from datetime import datetime

from pydantic import BaseModel, ConfigDict

from influx.crawler.domain.models import CrawlStatus


class CrawlRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    root_url: str
    link_id: int | None
    automated: bool
    status: CrawlStatus
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None
    requests_finished: int
    requests_failed: int
    pages: int
    documents: int
    links: int
    error: str | None
    requested_by_user_id: int | None
