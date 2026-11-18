
import pytest

from pydantic import ValidationError

from app.schemas.code_review import (
    CodeLocation,
    ReviewFinding,
    ReviewSeverity,
    ReviewDiffType,
    ReviewStatistics,
    CodeReviewResponse,
)


# =========================================================
# TEST DATA
# =========================================================

def get_valid_finding():
    return {
        "severity": "high",
        "title": "Missing authentication check",
        "location": {
            "file_path": "app/api/routes/chat.py",
            "start_line": 25,
            "end_line": 30,
        },
        "evidence": "user_id = request.user_id",
        "explanation": (
            "The endpoint does not verify whether "
            "the current user owns the requested resource."
        ),
        "suggestion": (
            "Verify resource ownership before processing "
            "the request."
        ),
        "rule_id": "AUTH-001",
        "confidence": 0.95,
    }


# =========================================================
# CODE LOCATION TESTS
# =========================================================

def test_valid_code_location():
    location = CodeLocation(
        file_path="app/main.py",
        start_line=10,
        end_line=20,
    )

    assert location.file_path == "app/main.py"
    assert location.start_line == 10
    assert location.end_line == 20


def test_invalid_line_range():
    with pytest.raises(ValidationError):
        CodeLocation(
            file_path="app/main.py",
            start_line=20,
            end_line=10,
        )


def test_invalid_line_number():
    with pytest.raises(ValidationError):
        CodeLocation(
            file_path="app/main.py",
            start_line=0,
            end_line=10,
        )


def test_empty_file_path():
    with pytest.raises(ValidationError):
        CodeLocation(
            file_path="   ",
            start_line=1,
            end_line=5,
        )


# =========================================================
# REVIEW FINDING TESTS
# =========================================================

def test_valid_review_finding():
    finding = ReviewFinding(**get_valid_finding())

    assert finding.severity == ReviewSeverity.HIGH
    assert finding.title == "Missing authentication check"
    assert finding.location.file_path == (
        "app/api/routes/chat.py"
    )
    assert finding.confidence == 0.95


def test_invalid_severity():
    data = get_valid_finding()
    data["severity"] = "urgent"

    with pytest.raises(ValidationError):
        ReviewFinding(**data)


def test_empty_evidence():
    data = get_valid_finding()
    data["evidence"] = "   "

    with pytest.raises(ValidationError):
        ReviewFinding(**data)


def test_empty_explanation():
    data = get_valid_finding()
    data["explanation"] = ""

    with pytest.raises(ValidationError):
        ReviewFinding(**data)


def test_empty_suggestion():
    data = get_valid_finding()
    data["suggestion"] = ""

    with pytest.raises(ValidationError):
        ReviewFinding(**data)


def test_invalid_confidence():
    data = get_valid_finding()
    data["confidence"] = 1.5

    with pytest.raises(ValidationError):
        ReviewFinding(**data)


def test_optional_fields():
    data = get_valid_finding()

    data.pop("rule_id")
    data.pop("confidence")

    finding = ReviewFinding(**data)

    assert finding.rule_id is None
    assert finding.confidence is None


def test_extra_finding_field_rejected():
    data = get_valid_finding()
    data["unexpected_field"] = "invalid"

    with pytest.raises(ValidationError):
        ReviewFinding(**data)


# =========================================================
# REVIEW STATISTICS TESTS
# =========================================================

def test_review_statistics():
    statistics = ReviewStatistics(
        critical=1,
        high=2,
        medium=3,
        low=2,
        info=1,
    )

    assert statistics.total_findings == 9


def test_default_review_statistics():
    statistics = ReviewStatistics()

    assert statistics.total_findings == 0
    assert statistics.critical == 0


def test_negative_review_statistics():
    with pytest.raises(ValidationError):
        ReviewStatistics(
            critical=-1,
        )


# =========================================================
# COMPLETE CODE REVIEW RESPONSE TESTS
# =========================================================

def test_valid_code_review_response():
    response = CodeReviewResponse(
        repository="example/RepoPilot-AI",
        diff_type="pull_request",
        identifier="10",
        title="Fix authentication",
        summary="Found authentication-related issues.",
        findings=[
            get_valid_finding(),
            {
                **get_valid_finding(),
                "severity": "critical",
                "title": "SQL injection vulnerability",
            },
        ],
    )

    assert response.repository == "example/RepoPilot-AI"
    assert response.diff_type == ReviewDiffType.PULL_REQUEST
    assert len(response.findings) == 2

    assert response.statistics.total_findings == 2
    assert response.statistics.high == 1
    assert response.statistics.critical == 1


def test_commit_review_response():
    response = CodeReviewResponse(
        repository="example/RepoPilot-AI",
        diff_type="commit",
        identifier="abc123",
        summary="No issues found.",
        findings=[],
    )

    assert response.diff_type == ReviewDiffType.COMMIT
    assert response.statistics.total_findings == 0


def test_invalid_diff_type():
    with pytest.raises(ValidationError):
        CodeReviewResponse(
            repository="example/repo",
            diff_type="branch",
            identifier="123",
            summary="Test review",
        )


def test_empty_findings_allowed():
    response = CodeReviewResponse(
        repository="example/repo",
        diff_type="commit",
        identifier="abc123",
        summary="No issues found.",
    )

    assert response.findings == []
    assert response.statistics.total_findings == 0


def test_empty_summary_rejected():
    with pytest.raises(ValidationError):
        CodeReviewResponse(
            repository="example/repo",
            diff_type="commit",
            identifier="abc123",
            summary="   ",
        )


def test_review_response_extra_field_rejected():
    with pytest.raises(ValidationError):
        CodeReviewResponse(
            repository="example/repo",
            diff_type="commit",
            identifier="abc123",
            summary="Review completed.",
            unexpected_field="invalid",
        )
