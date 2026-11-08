from datetime import datetime

from pydantic import BaseModel, Field


class IngestionStartRequest(BaseModel):
    repository_id: int = Field(..., gt=0)


class IngestionJobResponse(BaseModel):
    id: int
    repository_id: int
    user_id: int
    status: str
    default_branch: str | None = None
    tree_sha: str | None = None
    total_files: int = 0
    processed_files: int = 0
    error_message: str | None = None
    created_at: datetime
    updated_at: datetime