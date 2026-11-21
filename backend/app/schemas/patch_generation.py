
from pydantic import BaseModel, ConfigDict, Field


class GeneratePatchRequest(BaseModel):

    model_config = ConfigDict(extra="forbid")

    finding_index: int = Field(ge=0)


class GeneratedPatchResponse(BaseModel):

    model_config = ConfigDict(extra="forbid")

    review_id: int
    finding_index: int
    file_path: str
    finding_title: str
    patch: str
    message: str
