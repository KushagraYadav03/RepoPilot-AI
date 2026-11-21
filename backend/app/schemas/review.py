from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.code_review import (
    ReviewDiffType,
    CodeReviewResponse,
)


class CreateCodeReviewRequest(BaseModel):
    repository_id: int = Field(gt=0)

    diff_type: ReviewDiffType

    identifier: str = Field(
        min_length=1,
        max_length=255,
    )


class SavedCodeReviewResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    repository_id: int
    diff_type: ReviewDiffType
    identifier: str
    created_at: datetime
    review: CodeReviewResponse