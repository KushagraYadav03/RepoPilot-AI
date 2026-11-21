
import json
import asyncio
import importlib.util
import shutil

import pytest
from pydantic import ValidationError

from app.schemas.code_review import (
    CodeLocation,
    CodeReviewResponse,
    ReviewDiffType,
    ReviewFinding,
    ReviewSeverity,
)

from app.services.code_review_service import (
    CodeReviewService,
)

from app.services.static_analysis_service import (
    StaticAnalysisService,
)


# =========================================================
# TEST DATA
# =========================================================

def create_finding(
    severity=ReviewSeverity.HIGH,
    title="Possible security issue",
    file_path="app/auth.py",
    start_line=10,
    end_line=10,
    rule_id="F821",
    evidence="user_input = request.json",
    confidence=0.95,
):
    return ReviewFinding(
        severity=severity,
        title=title,
        evidence=evidence,
        explanation="This code may contain a problem.",
        suggestion="Validate the input before using it.",
        location=CodeLocation(
            file_path=file_path,
            start_line=start_line,
            end_line=end_line,
        ),
        rule_id=rule_id,
        confidence=confidence,
    )


def create_valid_review_data():
    return {
        "repository": "owner/repo",
        "diff_type": "pull_request",
        "identifier": "12",
        "title": "Code Review",
        "summary": "One potential issue was identified.",
        "findings": [
            {
                "severity": "high",
                "title": "Undefined variable",
                "evidence": "print(user_name)",
                "explanation": "The variable may not be defined.",
                "suggestion": "Define the variable before using it.",
                "location": {
                    "file_path": "app/auth.py",
                    "start_line": 10,
                    "end_line": 10,
                },
                "rule_id": "F821",
                "confidence": 0.95,
            }
        ],
    }


# =========================================================
# RUFF AVAILABILITY
# =========================================================

RUFF_AVAILABLE = (
    shutil.which("ruff") is not None
    or importlib.util.find_spec("ruff") is not None
)


# =========================================================
# 1. REVIEW SCHEMA EVALUATION
# =========================================================

def test_valid_review_response_is_accepted():
    data = create_valid_review_data()

    response = CodeReviewResponse.model_validate(data)

    assert response.repository == "owner/repo"
    assert response.diff_type == ReviewDiffType.PULL_REQUEST
    assert response.identifier == "12"
    assert len(response.findings) == 1


def test_review_statistics_are_calculated_correctly():
    data = create_valid_review_data()

    data["findings"].append(
        {
            "severity": "medium",
            "title": "Potential issue",
            "evidence": "result = calculate()",
            "explanation": "The result should be checked.",
            "suggestion": "Validate the result.",
            "location": {
                "file_path": "app/service.py",
                "start_line": 20,
                "end_line": 20,
            },
            "rule_id": "B001",
            "confidence": 0.80,
        }
    )

    response = CodeReviewResponse.model_validate(data)

    assert response.statistics.total_findings == 2
    assert response.statistics.high == 1
    assert response.statistics.medium == 1
    assert response.statistics.low == 0
    assert response.statistics.critical == 0


def test_invalid_severity_is_rejected():
    data = create_valid_review_data()
    data["findings"][0]["severity"] = "extreme"

    with pytest.raises(ValidationError):
        CodeReviewResponse.model_validate(data)


def test_invalid_diff_type_is_rejected():
    data = create_valid_review_data()
    data["diff_type"] = "invalid_type"

    with pytest.raises(ValidationError):
        CodeReviewResponse.model_validate(data)


def test_extra_field_is_rejected():
    data = create_valid_review_data()
    data["unexpected_field"] = "not allowed"

    with pytest.raises(ValidationError):
        CodeReviewResponse.model_validate(data)


# =========================================================
# 2. FINDING VALIDATION
# =========================================================

def test_confidence_above_one_is_rejected():
    with pytest.raises(ValidationError):
        create_finding(confidence=1.5)


def test_confidence_below_zero_is_rejected():
    with pytest.raises(ValidationError):
        create_finding(confidence=-0.1)


def test_empty_evidence_is_rejected():
    with pytest.raises(ValidationError):
        create_finding(evidence="   ")


def test_empty_title_is_rejected():
    with pytest.raises(ValidationError):
        create_finding(title="   ")


def test_zero_start_line_is_rejected():
    with pytest.raises(ValidationError):
        create_finding(start_line=0)


def test_end_line_before_start_line_is_rejected():
    with pytest.raises(ValidationError):
        create_finding(
            start_line=20,
            end_line=10,
        )


def test_valid_code_location_is_accepted():
    location = CodeLocation(
        file_path="app/auth.py",
        start_line=10,
        end_line=15,
    )

    assert location.file_path == "app/auth.py"
    assert location.start_line == 10
    assert location.end_line == 15


# =========================================================
# 3. LLM OUTPUT VALIDATION
# =========================================================

def test_valid_llm_json_is_parsed():
    service = CodeReviewService()

    response = json.dumps(create_valid_review_data())

    parsed = service._parse_llm_response(response)

    assert isinstance(parsed, dict)
    assert parsed["repository"] == "owner/repo"


def test_markdown_json_code_fence_is_supported():
    service = CodeReviewService()

    response = json.dumps(create_valid_review_data())

    fenced_response = (
        "```json\n"
        + response
        + "\n```"
    )

    parsed = service._parse_llm_response(fenced_response)

    assert parsed["repository"] == "owner/repo"


def test_invalid_json_is_rejected():
    service = CodeReviewService()

    with pytest.raises(ValueError):
        service._parse_llm_response("{invalid json}")


def test_empty_llm_response_is_rejected():
    service = CodeReviewService()

    with pytest.raises(ValueError):
        service._parse_llm_response("")


def test_json_array_is_rejected():
    service = CodeReviewService()

    with pytest.raises(ValueError):
        service._parse_llm_response(
            '[{"severity": "high"}]'
        )


def test_empty_json_object_fails_review_schema_validation():
    with pytest.raises(ValidationError):
        CodeReviewResponse.model_validate({})


# =========================================================
# 4. FINDING DEDUPLICATION EVALUATION
# =========================================================

def test_duplicate_findings_are_merged():
    service = CodeReviewService()

    ai_finding = create_finding(
        title="Undefined variable",
        rule_id="F821",
        file_path="app/auth.py",
        start_line=10,
        end_line=10,
    )

    static_finding = create_finding(
        title="Undefined variable detected by Ruff",
        rule_id="F821",
        file_path="app/auth.py",
        start_line=10,
        end_line=10,
        severity=ReviewSeverity.HIGH,
    )

    merged = service._merge_findings(
        [ai_finding],
        [static_finding],
    )

    assert len(merged) == 1


def test_findings_from_different_lines_are_preserved():
    service = CodeReviewService()

    first_finding = create_finding(
        rule_id="F821",
        start_line=10,
        end_line=10,
    )

    second_finding = create_finding(
        rule_id="F821",
        start_line=20,
        end_line=20,
    )

    merged = service._merge_findings(
        [first_finding],
        [second_finding],
    )

    assert len(merged) == 2


def test_findings_from_different_files_are_preserved():
    service = CodeReviewService()

    first_finding = create_finding(
        file_path="app/auth.py",
    )

    second_finding = create_finding(
        file_path="app/service.py",
    )

    merged = service._merge_findings(
        [first_finding],
        [second_finding],
    )

    assert len(merged) == 2


def test_empty_findings_return_empty_result():
    service = CodeReviewService()

    merged = service._merge_findings([], [])

    assert merged == []


# =========================================================
# 5. RUFF SEVERITY EVALUATION
# =========================================================

def test_ruff_severity_mapping():
    service = StaticAnalysisService()

    assert service._ruff_severity("F821") == ReviewSeverity.HIGH
    assert service._ruff_severity("F401") == ReviewSeverity.LOW
    assert service._ruff_severity("S106") == ReviewSeverity.HIGH
    assert service._ruff_severity("E501") == ReviewSeverity.MEDIUM
    assert service._ruff_severity("I001") == ReviewSeverity.LOW
    assert service._ruff_severity("UNKNOWN") == ReviewSeverity.INFO


@pytest.mark.parametrize(
    "rule_code, expected_severity",
    [
        ("F821", ReviewSeverity.HIGH),
        ("F401", ReviewSeverity.LOW),
        ("F811", ReviewSeverity.LOW),
        ("S106", ReviewSeverity.HIGH),
        ("E501", ReviewSeverity.MEDIUM),
        ("B006", ReviewSeverity.MEDIUM),
        ("I001", ReviewSeverity.LOW),
        ("UP035", ReviewSeverity.LOW),
        ("SIM102", ReviewSeverity.LOW),
        ("UNKNOWN", ReviewSeverity.INFO),
    ],
)
def test_individual_ruff_rule_severity(
    rule_code,
    expected_severity,
):
    service = StaticAnalysisService()

    assert service._ruff_severity(rule_code) == expected_severity


# =========================================================
# 6. KNOWN DEFECT EVALUATION
# =========================================================

@pytest.mark.skipif(
    not RUFF_AVAILABLE,
    reason="Ruff is not installed",
)
def test_known_undefined_variable_defect_is_detected():
    """
    A genuinely undefined variable should be detected by Ruff.
    F821 represents an undefined name.
    """

    service = StaticAnalysisService()

    source_code = (
        "def get_user():\n"
        "    return user_name\n"
    )

    findings = asyncio.run(
        service._run_ruff(
            filename="app/auth.py",
            source_code=source_code,
        )
    )

    finding = next(
        (
            item
            for item in findings
            if item.rule_id == "RUFF:F821"
        ),
        None,
    )

    assert finding is not None
    assert finding.severity == ReviewSeverity.HIGH
    assert finding.location.file_path == "app/auth.py"
    assert finding.location.start_line == 2


@pytest.mark.skipif(
    not RUFF_AVAILABLE,
    reason="Ruff is not installed",
)
def test_known_unused_variable_defect_is_detected():
    """
    An assigned but unused local variable should be detected.
    F841 represents an unused local variable.
    """

    service = StaticAnalysisService()

    source_code = (
        "def calculate_total():\n"
        "    temporary_value = 100\n"
        "    return 200\n"
    )

    findings = asyncio.run(
        service._run_ruff(
            filename="app/calculator.py",
            source_code=source_code,
        )
    )

    assert any(
        finding.rule_id == "RUFF:F841"
        for finding in findings
    )


# =========================================================
# 7. FALSE POSITIVE EVALUATION
# =========================================================

@pytest.mark.skipif(
    not RUFF_AVAILABLE,
    reason="Ruff is not installed",
)
def test_valid_python_code_does_not_generate_false_findings():
    """
    Correctly defined and used variables should not
    generate static analysis findings.
    """

    service = StaticAnalysisService()

    source_code = (
        "def calculate_total(price, tax):\n"
        "    total = price + tax\n"
        "    return total\n"
    )

    findings = asyncio.run(
        service._run_ruff(
            filename="app/calculator.py",
            source_code=source_code,
        )
    )

    assert findings == []


@pytest.mark.skipif(
    not RUFF_AVAILABLE,
    reason="Ruff is not installed",
)
def test_intentionally_suppressed_warning_is_not_reported():
    """
    An explicitly suppressed Ruff warning should not
    appear in the final static analysis findings.
    """

    service = StaticAnalysisService()

    source_code = (
        "def calculate_total():\n"
        "    temporary_value = 100  # noqa: F841\n"
        "    return 200\n"
    )

    findings = asyncio.run(
        service._run_ruff(
            filename="app/calculator.py",
            source_code=source_code,
        )
    )

    assert not any(
        finding.rule_id == "RUFF:F841"
        for finding in findings
    )


@pytest.mark.skipif(
    not RUFF_AVAILABLE,
    reason="Ruff is not installed",
)
def test_python_package_reexport_is_not_reported_as_unused_import():
    """
    Ruff should recognize a public re-export in __init__.py
    instead of incorrectly reporting it as an unused import.
    """

    service = StaticAnalysisService()

    # Explicit redundant alias marks this as a public re-export.
    source_code = "from .models import User as User\n"

    findings = asyncio.run(
        service._run_ruff(
            filename="app/__init__.py",
            source_code=source_code,
        )
    )

    assert not any(
        finding.rule_id == "RUFF:F401"
        for finding in findings
    )
