from sqlmodel import SQLModel, Field

class ContentChunk(SQLModel, table=True):
    id: int | None = Field(nullable=False, primary_key=True)
    