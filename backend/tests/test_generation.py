
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.schemas.test_generation import (
    GenerateTestsRequest,
    TestFramework as Framework,
    TestLanguage as Language,
)

from app.services.test_generation_service import (
    TestGenerationService as GenerationService,
)


@pytest.fixture
def python_request():

    return GenerateTestsRequest(
        source_code=(
            "def add(a, b):\n"
            "    return a + b"
        ),
        language=Language.PYTHON,
        framework=Framework.PYTEST,
        filename="calculator.py",
    )


@pytest.fixture
def valid_python_response():

    return json.dumps({
        "generated_code": (
            "def test_add():\n"
            "    assert 2 + 3 == 5"
        ),
        "test_cases": [
            {
                "name": "test_add",
                "purpose": "Checks addition of positive numbers",
            }
        ],
        "assumptions": [],
    })


@pytest.mark.asyncio
async def test_generate_tests_success(
    monkeypatch,
    python_request,
    valid_python_response,
):

    from app.services import test_generation_service

    mock_llm = AsyncMock()

    mock_llm.generate.return_value = SimpleNamespace(
        text=valid_python_response
    )

    monkeypatch.setattr(
        test_generation_service,
        "LLMService",
        lambda: mock_llm,
    )

    service = GenerationService()

    result = await service.generate_tests(
        python_request
    )

    assert result.language == Language.PYTHON
    assert result.framework == Framework.PYTEST
    assert "def test_add" in result.generated_code
    assert len(result.test_cases) == 1
    assert result.validation_passed is True

    mock_llm.generate.assert_awaited_once()


@pytest.mark.asyncio
async def test_reject_invalid_framework(
    python_request,
):

    service = GenerationService()

    with pytest.raises(
        ValueError,
        match="requires pytest",
    ):

        service._validate_framework(
            Language.PYTHON,
            Framework.JUNIT,
        )


def test_validate_valid_python_tests():

    code = """
def test_add():
    assert 2 + 3 == 5
"""

    GenerationService._validate_python_tests(code)


def test_reject_python_code_with_syntax_error():

    code = """
def test_add(
    assert 2 + 3 == 5
"""

    with pytest.raises(
        ValueError,
        match="syntax errors",
    ):

        GenerationService._validate_python_tests(code)


def test_reject_python_code_without_test_function():

    code = """
def add(a, b):
    return a + b
"""

    with pytest.raises(
        ValueError,
        match="pytest test functions",
    ):

        GenerationService._validate_python_tests(code)


def test_validate_python_test_class():

    code = """
class TestCalculator:

    def test_add(self):
        assert 2 + 3 == 5
"""

    GenerationService._validate_python_tests(code)


def test_validate_valid_java_tests():

    code = """
import org.junit.jupiter.api.Test;

class CalculatorTest {

    @Test
    void testAdd() {
        assertEquals(5, 2 + 3);
    }
}
"""

    GenerationService._validate_java_tests(code)


def test_reject_java_without_test_annotation():

    code = """
class CalculatorTest {

    void testAdd() {
        assertEquals(5, 2 + 3);
    }
}
"""

    with pytest.raises(
        ValueError,
        match="JUnit",
    ):

        GenerationService._validate_java_tests(code)


def test_parse_valid_llm_response():

    response = json.dumps({
        "generated_code": "def test_add(): pass",
        "test_cases": [],
        "assumptions": [],
    })

    result = GenerationService._parse_llm_response(
        response
    )

    assert result["generated_code"] == "def test_add(): pass"


def test_parse_markdown_json():

    response = """```json
{
    "generated_code": "def test_add(): pass",
    "test_cases": [],
    "assumptions": []
}
```"""

    result = GenerationService._parse_llm_response(
        response
    )

    assert result["generated_code"]


def test_reject_invalid_json():

    with pytest.raises(
        ValueError,
        match="invalid JSON",
    ):

        GenerationService._parse_llm_response(
            "invalid response"
        )


def test_reject_empty_llm_response():

    with pytest.raises(
        ValueError,
        match="empty",
    ):

        GenerationService._parse_llm_response("")


def test_reject_non_object_json():

    with pytest.raises(
        ValueError,
        match="JSON object",
    ):

        GenerationService._parse_llm_response(
            '["invalid"]'
        )


def test_reject_empty_generated_code():

    with pytest.raises(
        ValueError,
        match="cannot be empty",
    ):

        GenerationService._validate_python_tests("")
