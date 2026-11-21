
from pydantic import BaseModel, ConfigDict, Field, StrictInt

from app.schemas.sandbox import SandboxLanguage, SandboxResponse


class ValidatePatchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    finding_index: StrictInt = Field(ge=0)
    patch: str = Field(min_length=1, max_length=100_000)
    language: SandboxLanguage
    test_code: str = Field(min_length=1, max_length=50_000)
    test_filename: str | None = Field(default=None, max_length=100)


class PatchValidationResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    review_id: int = Field(ge=1)
    finding_index: int = Field(ge=0)
    file_path: str = Field(min_length=1, max_length=500)
    patch_applied: bool
    source_matches: bool
    sandbox: SandboxResponse
    message: str = Field(min_length=1, max_length=2000)
