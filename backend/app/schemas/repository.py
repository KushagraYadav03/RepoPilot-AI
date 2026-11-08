
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, HttpUrl, StringConstraints


RepositoryName = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1),
]


class RepositoryCreate(BaseModel):
    name: RepositoryName = Field(..., description="Repository name")
    github_url: HttpUrl


class RepositoryResponse(BaseModel):
    id: int
    name: str
    github_url: str
    owner_id: int
    default_branch: str | None = None
    tree_sha: str | None = None
    last_commit_sha: str | None = None
    programming_languages: str | None = None
    last_synced_at: str | None = None

    model_config = ConfigDict(from_attributes=True)
