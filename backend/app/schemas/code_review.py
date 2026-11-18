
from enum import Enum

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    computed_field,
    field_validator,
    model_validator,
)


# =========================================================
# REVIEW ENUMS
# =========================================================

class ReviewSeverity(str, Enum):
    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    INFO = "info"


class ReviewDiffType(str, Enum):
    PULL_REQUEST = "pull_request"
    COMMIT = "commit"


# =========================================================
# CODE LOCATION
# =========================================================

class CodeLocation(BaseModel):
    """
    Identifies the exact location of a code review finding.
    """

    model_config = ConfigDict(extra="forbid")

    file_path: str = Field(
        min_length=1,
        description="Repository-relative path of the affected file",
    )

    start_line: int = Field(
        ge=1,
        description="First affected line number",
    )

    end_line: int = Field(
        ge=1,
        description="Last affected line number",
    )

    @field_validator("file_path")
    @classmethod
    def validate_file_path(cls, value: str) -> str:
        value = value.strip()

        if not value:
            raise ValueError("File path cannot be empty")

        return value

    @model_validator(mode="after")
    def validate_line_range(self):
        if self.end_line < self.start_line:
            raise ValueError(
                "end_line cannot be smaller than start_line"
            )

        return self


# =========================================================
# REVIEW FINDING
# =========================================================

class ReviewFinding(BaseModel):
    """
    Represents one actionable issue discovered during
    an AI-powered code review.
    """

    model_config = ConfigDict(extra="forbid")

    severity: ReviewSeverity = Field(
        description="Severity level of the finding",
    )

    title: str = Field(
        min_length=1,
        max_length=200,
        description="Short title describing the issue",
    )

    location: CodeLocation = Field(
        description="Exact location of the issue",
    )

    evidence: str = Field(
        min_length=1,
        description="Code snippet or diff evidence supporting the finding",
    )

    explanation: str = Field(
        min_length=1,
        description="Why the identified code is problematic",
    )

    suggestion: str = Field(
        min_length=1,
        description="Actionable recommendation to fix the issue",
    )

    rule_id: str | None = Field(
        default=None,
        description="Optional identifier of the review rule",
    )

    confidence: float | None = Field(
        default=None,
        ge=0.0,
        le=1.0,
        description="Confidence score of the finding",
    )

    @field_validator(
        "title",
        "evidence",
        "explanation",
        "suggestion",
    )
    @classmethod
    def validate_non_empty_text(cls, value: str) -> str:
        value = value.strip()

        if not value:
            raise ValueError("This field cannot be empty")

        return value


# =========================================================
# REVIEW STATISTICS
# =========================================================

class ReviewStatistics(BaseModel):
    """
    Severity-wise count of review findings.
    """

    critical: int = Field(default=0, ge=0)
    high: int = Field(default=0, ge=0)
    medium: int = Field(default=0, ge=0)
    low: int = Field(default=0, ge=0)
    info: int = Field(default=0, ge=0)

    @computed_field
    @property
    def total_findings(self) -> int:
        return (
            self.critical
            + self.high
            + self.medium
            + self.low
            + self.info
        )


# =========================================================
# CODE REVIEW RESPONSE
# =========================================================

class CodeReviewResponse(BaseModel):
    """
    Complete structured response returned by the
    AI Code Review Engine.
    """

    model_config = ConfigDict(extra="forbid")

    repository: str = Field(
        min_length=1,
        description="Repository owner and name",
    )

    diff_type: ReviewDiffType

    identifier: str = Field(
        min_length=1,
        description="Pull request number or commit SHA",
    )

    title: str | None = None

    summary: str = Field(
        min_length=1,
        description="Overall summary of the code review",
    )

    findings: list[ReviewFinding] = Field(
        default_factory=list,
        description="List of actionable review findings",
    )

    @computed_field
    @property
    def statistics(self) -> ReviewStatistics:
        counts = {
            severity.value: 0
            for severity in ReviewSeverity
        }

        for finding in self.findings:
            counts[finding.severity.value] += 1

        return ReviewStatistics(**counts)

    @field_validator("repository", "identifier", "summary")
    @classmethod
    def validate_required_text(cls, value: str) -> str:
        value = value.strip()

        if not value:
            raise ValueError("This field cannot be empty")

        return value
