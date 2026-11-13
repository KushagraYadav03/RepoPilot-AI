
from pydantic import BaseModel, Field


class RepositoryChatRequest(BaseModel):

    query: str = Field(
        min_length=1,
        max_length=5000,
        description="Question about the repository",
    )

    limit: int = Field(
        default=5,
        ge=1,
        le=20,
    )

    score_threshold: float | None = Field(
        default=None,
        ge=0.0,
        le=1.0,
    )


class ChatSourceResponse(BaseModel):

    source_id: str

    file_path: str | None = None

    symbol_name: str | None = None

    symbol_kind: str | None = None

    start_line: int | None = None

    end_line: int | None = None

    commit_sha: str | None = None

    score: float | None = None


class RepositoryChatResponse(BaseModel):

    answer: str

    provider: str

    model: str

    sources: list[ChatSourceResponse]
