
import re
from enum import Enum
from pathlib import PurePosixPath

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    field_validator,
    model_validator,
)


class SandboxLanguage(str, Enum):
    PYTHON = "python"
    JAVA = "java"


class SandboxRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    language: SandboxLanguage
    source_code: str = Field(min_length=1, max_length=50_000)
    test_code: str = Field(min_length=1, max_length=50_000)
    source_filename: str | None = Field(default=None, max_length=500)
    test_filename: str | None = Field(default=None, max_length=100)

    @field_validator("source_code", "test_code")
    @classmethod
    def validate_code(cls, value: str) -> str:

        # Preserve original source, indentation and trailing newlines.
        # strip() is used only for checking whether content is empty.
        if not value.strip():
            raise ValueError("Code cannot be empty.")

        if "\x00" in value:
            raise ValueError("Code cannot contain null bytes.")

        return value

    @field_validator("source_filename")
    @classmethod
    def validate_source_filename(cls, value: str | None) -> str | None:

        if value is None:
            return value

        if not value or "\x00" in value or "\\" in value:
            raise ValueError("Source filename is invalid.")

        path = PurePosixPath(value)

        if path.is_absolute() or path.as_posix() != value:
            raise ValueError(
                "Source filename must be a normalized relative path."
            )

        if not path.parts or any(
            part in ("", ".", "..") for part in path.parts
        ):
            raise ValueError(
                "Source filename contains an unsafe path segment."
            )

        segment_pattern = re.compile(
            r"^[A-Za-z0-9_-][A-Za-z0-9_.-]*$"
        )

        if any(
            not segment_pattern.fullmatch(part)
            for part in path.parts
        ):
            raise ValueError(
                "Source filename contains unsupported characters."
            )

        if path.suffix.lower() not in {".py", ".java"}:
            raise ValueError(
                "Source filename must end in .py or .java."
            )

        return path.as_posix()

    @field_validator("test_filename")
    @classmethod
    def validate_test_filename(cls, value: str | None) -> str | None:

        if value is None:
            return value

        if (
            not value
            or "\x00" in value
            or "/" in value
            or "\\" in value
            or value in {".", ".."}
        ):
            raise ValueError(
                "Test filename must be a simple filename."
            )

        path = PurePosixPath(value)

        if len(path.parts) != 1:
            raise ValueError(
                "Test filename cannot contain directories."
            )

        stem = path.stem

        if not re.fullmatch(
            r"[A-Za-z0-9_-][A-Za-z0-9_.-]*",
            stem,
        ):
            raise ValueError(
                "Test filename contains unsupported characters."
            )

        if path.suffix.lower() not in {".py", ".java"}:
            raise ValueError(
                "Test filename must end in .py or .java."
            )

        return value

    @model_validator(mode="after")
    def validate_filename_extensions(self):

        expected_extension = (
            ".py"
            if self.language == SandboxLanguage.PYTHON
            else ".java"
        )

        if self.source_filename:
            if (
                PurePosixPath(self.source_filename).suffix.lower()
                != expected_extension
            ):
                raise ValueError(
                    f"Source filename must end in {expected_extension} "
                    f"for {self.language.value}."
                )

        if self.test_filename:
            if (
                PurePosixPath(self.test_filename).suffix.lower()
                != expected_extension
            ):
                raise ValueError(
                    f"Test filename must end in {expected_extension} "
                    f"for {self.language.value}."
                )

        if (
            self.source_filename
            and self.test_filename
            and PurePosixPath(self.source_filename).name
            == self.test_filename
        ):
            raise ValueError(
                "Source and test filenames must be different."
            )

        return self


class SandboxResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    language: SandboxLanguage
    passed: bool
    exit_code: int | None
    stdout: str = ""
    stderr: str = ""
    timed_out: bool = False
    output_limited: bool = False
    execution_time_ms: int = Field(ge=0)
    passed_tests: int = Field(default=0, ge=0)
    failed_tests: int = Field(default=0, ge=0)
    message: str
