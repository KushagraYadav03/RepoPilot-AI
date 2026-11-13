
from pydantic import BaseModel, Field


class RetrievalRequest(BaseModel):
    query: str = Field(
        min_length=1,
        description="Natural language search query",
    )

    limit: int = Field(
        default=5,
        ge=1,
        le=50,
    )

    score_threshold: float | None = Field(
        default=None,
        ge=0.0,
        le=1.0,
    )


class RetrievedChunkResponse(BaseModel):
    id: str
    repository_id: int
    file_path: str | None = None
    symbol_name: str | None = None
    symbol_kind: str | None = None
    start_line: int | None = None
    end_line: int | None = None
    content: str | None = None
    commit_sha: str | None = None
    score: float
