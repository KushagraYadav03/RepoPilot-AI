
from pydantic import BaseModel, ConfigDict, HttpUrl


class RepositoryCreate(BaseModel):
    name: str
    github_url: HttpUrl


class RepositoryResponse(BaseModel):
    id: int
    name: str
    github_url: str
    owner_id: int

    model_config = ConfigDict(from_attributes=True)
