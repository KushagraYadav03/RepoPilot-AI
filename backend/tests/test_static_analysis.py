
import pytest

from app.schemas.code_review import (
    ReviewFinding,
    ReviewSeverity,
)

from app.services.static_analysis_service import (
    StaticAnalysisService,
)

from app.services.code_review_service import (
    CodeReviewService,
)


@pytest.fixture
def service():
    return StaticAnalysisService()


def test_ruff_severity_mapping(service):

    assert service._ruff_severity("F821") == ReviewSeverity.HIGH
    assert service._ruff_severity("E501") == ReviewSeverity.MEDIUM
    assert service._ruff_severity("I001") == ReviewSeverity.LOW
    assert service._ruff_severity("UNKNOWN") == ReviewSeverity.INFO


def test_pmd_severity_mapping(service):

    assert service._pmd_severity("1") == ReviewSeverity.CRITICAL
    assert service._pmd_severity("2") == ReviewSeverity.HIGH
    assert service._pmd_severity("3") == ReviewSeverity.MEDIUM
    assert service._pmd_severity("4") == ReviewSeverity.LOW
    assert service._pmd_severity("5") == ReviewSeverity.INFO
    assert service._pmd_severity("unknown") == ReviewSeverity.MEDIUM


def test_get_evidence(service):

    source_code = (
        "def login():\n"
        "    password = '12345'\n"
        "    return password\n"
    )

    assert service._get_evidence(
        source_code,
        2,
    ) == "password = '12345'"


def test_get_evidence_for_invalid_line(service):

    result = service._get_evidence(
        "print('hello')",
        10,
    )

    assert result == "Source line is unavailable."


def test_parse_pmd_xml(service):

    source_code = (
        "public class Demo {\n"
        "    public void test() {\n"
        "        System.out.println(\"hello\");\n"
        "    }\n"
        "}\n"
    )

    xml_output = """
    <pmd>
        <file name="Demo.java">
            <violation
                beginline="3"
                endline="3"
                rule="SystemPrintln"
                ruleset="Best Practices"
                priority="3">
                System.out.println should not be used.
            </violation>
        </file>
    </pmd>
    """

    findings = service._parse_pmd_xml(
        filename="Demo.java",
        source_code=source_code,
        xml_output=xml_output,
    )

    assert len(findings) == 1

    finding = findings[0]

    assert finding.severity == ReviewSeverity.MEDIUM
    assert finding.location.file_path == "Demo.java"
    assert finding.location.start_line == 3
    assert finding.rule_id == "PMD:SystemPrintln"
    assert "System.out.println" in finding.evidence


def test_parse_invalid_pmd_xml(service):

    findings = service._parse_pmd_xml(
        filename="Demo.java",
        source_code="class Demo {}",
        xml_output="<invalid",
    )

    assert findings == []


def create_finding(
    title,
    file_path,
    start_line,
    rule_id=None,
):

    return ReviewFinding(
        severity="medium",
        title=title,
        location={
            "file_path": file_path,
            "start_line": start_line,
            "end_line": start_line,
        },
        evidence="print('hello')",
        explanation="Test explanation",
        suggestion="Fix the issue",
        rule_id=rule_id,
        confidence=1.0,
    )


def test_merge_ai_and_static_findings():

    ai_findings = [
        create_finding(
            title="Unused variable",
            file_path="app/main.py",
            start_line=5,
            rule_id="RUFF:F841",
        )
    ]

    static_findings = [
        create_finding(
            title="Unused variable",
            file_path="app/main.py",
            start_line=5,
            rule_id="RUFF:F841",
        ),
        create_finding(
            title="Missing return",
            file_path="app/service.py",
            start_line=10,
            rule_id="RUFF:RET501",
        ),
    ]

    merged = CodeReviewService._merge_findings(
        ai_findings=ai_findings,
        static_findings=static_findings,
    )

    assert len(merged) == 2


def test_merge_keeps_different_lines():

    ai_findings = [
        create_finding(
            title="Issue one",
            file_path="app/main.py",
            start_line=5,
            rule_id="RUFF:F841",
        )
    ]

    static_findings = [
        create_finding(
            title="Issue two",
            file_path="app/main.py",
            start_line=10,
            rule_id="RUFF:F841",
        )
    ]

    merged = CodeReviewService._merge_findings(
        ai_findings=ai_findings,
        static_findings=static_findings,
    )

    assert len(merged) == 2
