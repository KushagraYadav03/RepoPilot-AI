
import ast
import json
import logging
import re

from typing import Any

from app.services.llm_service import LLMService

from app.services.test_generation_prompt import (
    SYSTEM_INSTRUCTION,
    build_test_generation_prompt,
)

from app.services.sandbox_service import (
    SandboxService,
)

from app.schemas.sandbox import (
    SandboxLanguage,
    SandboxRequest,
)

from app.schemas.test_generation import (
    TestFramework,
    TestLanguage,
    GenerateTestsRequest,
    GenerateTestsResponse,
)


logger = logging.getLogger(__name__)


class TestGenerationService:

    __test__ = False

    def __init__(self):

        self.llm_service = LLMService()

        self.sandbox_service = SandboxService()

    async def generate_tests(
        self,
        request: GenerateTestsRequest,
    ) -> GenerateTestsResponse:

        self._validate_framework(
            language=request.language,
            framework=request.framework,
        )

        prompt = build_test_generation_prompt(
            source_code=request.source_code,
            language=request.language.value,
            framework=request.framework.value,
            filename=request.filename,
            additional_context=request.additional_context,
        )

        logger.info(
            "Generating %s tests for %s source code",
            request.framework.value,
            request.language.value,
        )

        llm_response = await self.llm_service.generate(
            prompt=prompt,
            system_instruction=SYSTEM_INSTRUCTION,
            temperature=0.2,
            max_output_tokens=8192,
        )

        generated_data = self._parse_llm_response(
            llm_response.text
        )

        try:

            result = GenerateTestsResponse(
                language=request.language,
                framework=request.framework,
                generated_code=generated_data.get(
                    "generated_code",
                    "",
                ),
                test_cases=generated_data.get(
                    "test_cases",
                    [],
                ),
                assumptions=generated_data.get(
                    "assumptions",
                    [],
                ),
                validation_passed=False,
                validation_message="Validation not completed",
                execution_result=None,
            )

        except Exception as exc:

            logger.exception(
                "Invalid generated test response"
            )

            raise ValueError(
                "LLM returned an invalid test generation response"
            ) from exc

        self._validate_generated_code(
            generated_code=result.generated_code,
            language=request.language,
            framework=request.framework,
        )

        result.validation_passed = True

        result.validation_message = (
            "Generated test code passed structural validation."
        )

        if request.execute_tests:

            logger.info(
                "Executing generated tests inside Docker sandbox"
            )

            sandbox_language = (
                SandboxLanguage.PYTHON
                if request.language == TestLanguage.PYTHON
                else SandboxLanguage.JAVA
            )

            source_filename = request.filename

            if source_filename is None:

                source_filename = (
                    "solution.py"
                    if request.language == TestLanguage.PYTHON
                    else "Solution.java"
                )

            test_filename = (
                "test_solution.py"
                if request.language == TestLanguage.PYTHON
                else "SolutionTest.java"
            )

            sandbox_request = SandboxRequest(
                language=sandbox_language,
                source_code=request.source_code,
                test_code=result.generated_code,
                source_filename=source_filename,
                test_filename=test_filename,
            )

            result.execution_result = (
                await self.sandbox_service.execute(
                    sandbox_request
                )
            )

            if result.execution_result.passed:

                result.validation_message = (
                    "Generated tests passed structural validation "
                    "and Docker execution."
                )

            elif result.execution_result.timed_out:

                result.validation_message = (
                    "Generated tests passed structural validation "
                    "but execution timed out."
                )

            else:

                result.validation_message = (
                    "Generated tests passed structural validation "
                    "but one or more tests failed during execution."
                )

        else:

            result.validation_message += (
                " Tests have not been executed."
            )

        logger.info(
            "Successfully generated %s test cases",
            len(result.test_cases),
        )

        return result

    # ================================================
    # FRAMEWORK VALIDATION
    # ================================================

    @staticmethod
    def _validate_framework(
        language: TestLanguage,
        framework: TestFramework,
    ) -> None:

        valid_combinations = {
            TestLanguage.PYTHON: TestFramework.PYTEST,
            TestLanguage.JAVA: TestFramework.JUNIT,
        }

        expected_framework = valid_combinations.get(language)

        if framework != expected_framework:

            raise ValueError(
                f"{language.value} requires "
                f"{expected_framework.value} framework"
            )

    # ================================================
    # GENERATED CODE VALIDATION
    # ================================================

    @staticmethod
    def _validate_generated_code(
        generated_code: str,
        language: TestLanguage,
        framework: TestFramework,
    ) -> None:

        if not generated_code or not generated_code.strip():

            raise ValueError(
                "Generated test code cannot be empty"
            )

        if language == TestLanguage.PYTHON:

            TestGenerationService._validate_python_tests(
                generated_code
            )

        elif language == TestLanguage.JAVA:

            TestGenerationService._validate_java_tests(
                generated_code
            )

    # ================================================
    # PYTHON TEST VALIDATION
    # ================================================

    @staticmethod
    def _validate_python_tests(
        generated_code: str,
    ) -> None:

        if not generated_code or not generated_code.strip():

            raise ValueError(
                "Generated test code cannot be empty"
            )

        try:

            parsed_code = ast.parse(generated_code)

        except SyntaxError as exc:

            raise ValueError(
                "Generated Python test code contains syntax errors"
            ) from exc

        test_functions = []

        for node in ast.walk(parsed_code):

            if isinstance(
                node,
                (ast.FunctionDef, ast.AsyncFunctionDef),
            ):

                if node.name.startswith("test_"):
                    test_functions.append(node)

            elif isinstance(node, ast.ClassDef):

                if node.name.startswith("Test"):

                    test_methods = [
                        item
                        for item in node.body
                        if isinstance(
                            item,
                            (ast.FunctionDef, ast.AsyncFunctionDef),
                        )
                        and item.name.startswith("test_")
                    ]

                    test_functions.extend(test_methods)

        if not test_functions:

            raise ValueError(
                "Generated Python code does not contain "
                "any valid pytest test functions"
            )

    # ================================================
    # JAVA TEST VALIDATION
    # ================================================

    @staticmethod
    def _validate_java_tests(
        generated_code: str,
    ) -> None:

        has_test_annotation = bool(
            re.search(
                r"@Test\b",
                generated_code,
            )
        )

        has_test_method = bool(
            re.search(
                r"\bvoid\s+test\w*\s*\(",
                generated_code,
            )
        )

        if not has_test_annotation or not has_test_method:

            raise ValueError(
                "Generated Java code must contain "
                "JUnit @Test annotated test methods"
            )

    # ================================================
    # PARSE LLM RESPONSE
    # ================================================

    @staticmethod
    def _parse_llm_response(
        response_text: str,
    ) -> dict[str, Any]:

        if not response_text or not response_text.strip():

            raise ValueError(
                "LLM returned an empty test generation response"
            )

        cleaned_response = response_text.strip()

        if cleaned_response.startswith("```"):

            lines = cleaned_response.splitlines()

            if lines[-1].strip().startswith("```"):
                lines = lines[:-1]

            lines = lines[1:]

            cleaned_response = "\n".join(lines).strip()

        try:

            parsed = json.loads(cleaned_response)

        except json.JSONDecodeError as exc:

            logger.exception(
                "Unable to parse generated test JSON"
            )

            raise ValueError(
                "LLM returned invalid JSON for test generation"
            ) from exc

        if not isinstance(parsed, dict):

            raise ValueError(
                "LLM response must be a JSON object"
            )

        return parsed
