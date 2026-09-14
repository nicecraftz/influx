from datetime import datetime
from typing import Annotated

from pydantic import BaseModel, Field, StringConstraints

from influx.core.config import QUESTION_MAX_LENGTH


class QuestionRequest(BaseModel):
    question: Annotated[str, StringConstraints(strip_whitespace=True, min_length=3, max_length=QUESTION_MAX_LENGTH)]


class SourceRead(BaseModel):
    # The number the answer cites as [n].
    index: int
    url: str
    title: str | None
    similarity: float = Field(description="cosine similarity between the question and the passage, -1..1")
    excerpt: str


class AnswerRead(BaseModel):
    id: int
    question: str
    answer: str
    sources: list[SourceRead]
    latency_ms: int


class MetricsRead(BaseModel):
    questions: int
    questions_last_24h: int
    average_latency_ms: float | None
    average_top_similarity: float | None
    last_question_at: datetime | None
