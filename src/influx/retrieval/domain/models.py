from datetime import datetime

from sqlalchemy import Column, Text
from sqlmodel import Field, SQLModel

from influx.core.time import timestamp_field


class Question(SQLModel, table=True):
    """One question asked about an organization's content, with the answer it
    got. Written by the API on every answer; the data behind
    `/retrieval/organizations/{id}/metrics`.
    """

    id: int | None = Field(default=None, primary_key=True)
    text: str = Field(sa_column=Column(Text, nullable=False))
    answer: str = Field(sa_column=Column(Text, nullable=False))
    # Cosine similarity of the best passage: how well the corpus covered the
    # question, whatever the model made of it.
    top_similarity: float = Field(nullable=False)
    # Passages handed to the model.
    passages: int = Field(nullable=False)
    # Embedding + search + generation, wall clock.
    latency_ms: int = Field(nullable=False)
    created_at: datetime = timestamp_field()

    organization_id: int = Field(foreign_key="organization.id", nullable=False, index=True, ondelete="CASCADE")
    # Kept if the user is deleted: the question was still asked.
    user_id: int | None = Field(default=None, foreign_key="user.id", ondelete="SET NULL")
