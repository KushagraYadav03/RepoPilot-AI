
from enum import Enum

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    field_validator,
)

from app.schemas.sandbox import SandboxResponse


class TestFramework(str, Enum):
    PYTEST = "pytest"
    JUNIT = "junit"


class TestLanguage(str, Enum):
    PYTHON = "python"
    JAVA = "java"


class GenerateTestsRequest(BaseModel):

    model_config = ConfigDict(extra="forbid")

    source_code: str = Field(
        min_length=1,
        max_length=20000,
        description="Source code for which tests must be generated",
    )

    language: TestLanguage

    framework: TestFramework

    filename: str | None = Field(
        default=None,
        max_length=255,
    )

    additional_context: str | None = Field(
        default=None,
        max_length=3000,
    )

    execute_tests: bool = False

    @field_validator("source_code")
    @classmethod
    def validate_source_code(cls, value: str) -> str:

        value = value.strip()

        if not value:
            raise ValueError("Source code cannot be empty")

        return value

    @field_validator("filename")
    @classmethod
    def validate_filename(cls, value: str | None):

        if value is not None:
            value = value.strip()

            if not value:
                return None

            if "/" in value or "\\" in value or ".." in value:
                raise ValueError("Invalid filename")

        return value

    @field_validator("additional_context")
    @classmethod
    def validate_context(cls, value: str | None):

        if value is not None:
            value = value.strip()

            if not value:
                return None

        return value


class GeneratedTestCase(BaseModel):

    model_config = ConfigDict(extra="forbid")

    name: str = Field(
        min_length=1,
        max_length=200,
    )

    purpose: str = Field(
        min_length=1,
        max_length=1000,
    )


class GenerateTestsResponse(BaseModel):

    model_config = ConfigDict(extra="forbid")

    language: TestLanguage

    framework: TestFramework

    generated_code: str = Field(min_length=1)

    test_cases: list[GeneratedTestCase] = Field(
        default_factory=list
    )

    assumptions: list[str] = Field(
        default_factory=list
    )

    validation_passed: bool

    validation_message: str

    execution_result: SandboxResponse | None = None
