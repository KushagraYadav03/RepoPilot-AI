
import asyncio
import shutil
from types import SimpleNamespace

import pytest

from fastapi import HTTPException

from app.schemas.sandbox import SandboxLanguage
from app.services.patch_validation_service import (
    PatchValidationService,
)


# =========================================================
# MOCK SANDBOX SERVICE
# =========================================================

class MockSandboxService:

    def __init__(self, response=None, error=None):
        self.response = response or SimpleNamespace(
            language=SandboxLanguage.PYTHON,
            passed=True,
            exit_code=0,
            stdout="1 passed",
            stderr="",
            timed_out=False,
            output_limited=False,
            execution_time_ms=100,
            passed_tests=1,
            failed_tests=0,
            message="All generated tests passed.",
        )

        self.error = error
        self.received_request = None

    async def execute(self, request):
        self.received_request = request

        if self.error:
            raise self.error

        return self.response


# =========================================================
# TEST DATA
# =========================================================

SOURCE_CODE = (
    "def add(a, b):\n"
    "    return a + b\n"
)

VALID_PATCH = (
    "--- a/src/calculator.py\n"
    "+++ b/src/calculator.py\n"
    "@@ -1,2 +1,2 @@\n"
    " def add(a, b):\n"
    "-    return a + b\n"
    "+    return a - b\n"
)

UPDATED_SOURCE = (
    "def add(a, b):\n"
    "    return a - b\n"
)


@pytest.fixture
def mock_sandbox():
    return MockSandboxService()


@pytest.fixture
def service(mock_sandbox):
    return PatchValidationService(
        sandbox_service=mock_sandbox
    )


# =========================================================
# FILE PATH VALIDATION
# =========================================================

@pytest.mark.parametrize(
    "file_path",
    [
        "main.py",
        "src/main.py",
        "src/calculator.py",
        "src/my-service.py",
        "src/my.file.py",
        "app/models/user_model.java",
    ],
)
def test_validate_file_path_accepts_valid_paths(file_path):
    result = PatchValidationService.validate_file_path(
        file_path
    )

    assert result == file_path


@pytest.mark.parametrize(
    "file_path",
    [
        "",
        "../main.py",
        "src/../main.py",
        "/main.py",
        "src//main.py",
        "src/./main.py",
        "src\\main.py",
        "main.txt",
        "main.py/",
        "C:/main.py",
        "src/file name.py",
        "src/.hidden.py",
    ],
)
def test_validate_file_path_rejects_unsafe_paths(file_path):

    with pytest.raises(HTTPException) as exc:
        PatchValidationService.validate_file_path(
            file_path
        )

    assert exc.value.status_code == 422


def test_validate_file_path_rejects_null_byte():

    with pytest.raises(HTTPException):
        PatchValidationService.validate_file_path(
            "main.py\x00"
        )


def test_validate_file_path_rejects_long_path():

    file_path = "a" * 498 + ".py"

    with pytest.raises(HTTPException) as exc:
        PatchValidationService.validate_file_path(
            file_path
        )

    assert exc.value.status_code == 422


# =========================================================
# LANGUAGE VALIDATION
# =========================================================

def test_validate_python_language():

    PatchValidationService.validate_language(
        "main.py",
        SandboxLanguage.PYTHON,
    )


def test_validate_java_language():

    PatchValidationService.validate_language(
        "Main.java",
        SandboxLanguage.JAVA,
    )


def test_validate_language_rejects_mismatch():

    with pytest.raises(HTTPException) as exc:
        PatchValidationService.validate_language(
            "Main.java",
            SandboxLanguage.PYTHON,
        )

    assert exc.value.status_code == 422


# =========================================================
# TEST FILENAME VALIDATION
# =========================================================

def test_default_python_test_filename():

    result = PatchValidationService.validate_test_filename(
        None,
        SandboxLanguage.PYTHON,
        "src/calculator.py",
    )

    assert result == "test_calculator.py"


def test_default_java_test_filename():

    result = PatchValidationService.validate_test_filename(
        None,
        SandboxLanguage.JAVA,
        "src/Calculator.java",
    )

    assert result == "CalculatorTest.java"


def test_custom_test_filename():

    result = PatchValidationService.validate_test_filename(
        "calculator_test.py",
        SandboxLanguage.PYTHON,
        "src/calculator.py",
    )

    assert result == "calculator_test.py"


@pytest.mark.parametrize(
    "filename",
    [
        "../test.py",
        "src/test.py",
        "test\\test.py",
        "test.txt",
        "",
        ".",
        "..",
        "test file.py",
        "calculator.py",
    ],
)
def test_rejects_unsafe_test_filenames(filename):

    with pytest.raises(HTTPException):
        PatchValidationService.validate_test_filename(
            filename,
            SandboxLanguage.PYTHON,
            "calculator.py",
        )


# =========================================================
# PATCH HEADER VALIDATION
# =========================================================

def test_valid_patch_headers():

    PatchValidationService.validate_patch_headers(
        VALID_PATCH,
        "src/calculator.py",
    )


def test_rejects_empty_patch():

    with pytest.raises(HTTPException) as exc:
        PatchValidationService.validate_patch_headers(
            "",
            "src/calculator.py",
        )

    assert exc.value.status_code == 422


def test_rejects_patch_with_wrong_file_path():

    with pytest.raises(HTTPException) as exc:
        PatchValidationService.validate_patch_headers(
            VALID_PATCH,
            "src/another.py",
        )

    assert exc.value.status_code == 422


def test_rejects_multiple_file_headers():

    patch = VALID_PATCH + (
        "--- a/another.py\n"
        "+++ b/another.py\n"
        "@@ -1 +1 @@\n"
        "-old\n"
        "+new\n"
    )

    with pytest.raises(HTTPException):
        PatchValidationService.validate_patch_headers(
            patch,
            "src/calculator.py",
        )


def test_rejects_git_metadata():

    patch = (
        "diff --git a/src/calculator.py b/src/calculator.py\n"
        + VALID_PATCH
    )

    with pytest.raises(HTTPException) as exc:
        PatchValidationService.validate_patch_headers(
            patch,
            "src/calculator.py",
        )

    assert exc.value.status_code == 422


def test_rejects_binary_patch():

    patch = (
        "GIT binary patch\n"
        + VALID_PATCH
    )

    with pytest.raises(HTTPException):
        PatchValidationService.validate_patch_headers(
            patch,
            "src/calculator.py",
        )


def test_rejects_patch_without_hunk():

    patch = (
        "--- a/src/calculator.py\n"
        "+++ b/src/calculator.py\n"
    )

    with pytest.raises(HTTPException):
        PatchValidationService.validate_patch_headers(
            patch,
            "src/calculator.py",
        )


def test_rejects_oversized_patch():

    patch = (
        "--- a/src/calculator.py\n"
        "+++ b/src/calculator.py\n"
        "@@ -1 +1 @@\n"
        + ("+" + "a" * 1024 + "\n") * 110
    )

    with pytest.raises(HTTPException) as exc:
        PatchValidationService.validate_patch_headers(
            patch,
            "src/calculator.py",
        )

    assert exc.value.status_code == 413


# =========================================================
# GIT PATCH APPLICATION
# =========================================================

@pytest.mark.skipif(
    shutil.which("git") is None,
    reason="Git is not installed",
)
def test_apply_valid_patch_in_temporary_workspace(service):

    result = service.apply_patch_in_workspace(
        original_source=SOURCE_CODE,
        patch=VALID_PATCH,
        file_path="src/calculator.py",
    )

    assert result == UPDATED_SOURCE


def test_apply_patch_rejects_empty_source(service):

    with pytest.raises(HTTPException) as exc:
        service.apply_patch_in_workspace(
            original_source="",
            patch=VALID_PATCH,
            file_path="src/calculator.py",
        )

    assert exc.value.status_code == 422


def test_apply_patch_rejects_oversized_source(service):

    source = "a" * (50 * 1024 + 1)

    with pytest.raises(HTTPException) as exc:
        service.apply_patch_in_workspace(
            original_source=source,
            patch=VALID_PATCH,
            file_path="src/calculator.py",
        )

    assert exc.value.status_code == 413


def test_apply_patch_rejects_invalid_diff(service):

    with pytest.raises(HTTPException) as exc:
        service.apply_patch_in_workspace(
            original_source=SOURCE_CODE,
            patch=VALID_PATCH,
            file_path="src/another.py",
        )

    assert exc.value.status_code == 422


def test_apply_patch_rejects_missing_git(
    service,
    monkeypatch,
):

    monkeypatch.setattr(
        "app.services.patch_validation_service.shutil.which",
        lambda command: None,
    )

    with pytest.raises(HTTPException) as exc:
        service.apply_patch_in_workspace(
            original_source=SOURCE_CODE,
            patch=VALID_PATCH,
            file_path="src/calculator.py",
        )

    assert exc.value.status_code == 503


# =========================================================
# PATCH AND SANDBOX INTEGRATION
# =========================================================

def test_validate_and_execute_success(
    service,
    mock_sandbox,
):

    result = asyncio.run(
        service.validate_and_execute(
            file_path="src/calculator.py",
            original_source=SOURCE_CODE,
            patch=VALID_PATCH,
            language=SandboxLanguage.PYTHON,
            test_code=(
                "from calculator import add\n"
                "def test_add():\n"
                "    assert add(5, 2) == 3\n"
            ),
        )
    )

    assert result["patch_applied"] is True
    assert result["source_matches"] is True

    assert (
        result["message"]
        ==
        "Patch was applied successfully to the fetched GitHub source "
        "and the patched source was executed in the sandbox."
    )

    assert mock_sandbox.received_request is not None

    # DEBUG 1: Actual source sent to sandbox.
    print(
        "\nACTUAL:",
        repr(mock_sandbox.received_request.source_code),
    )

    # DEBUG 2: Expected source.
    print(
        "\nEXPECTED:",
        repr(UPDATED_SOURCE),
    )

    # DEBUG 3: Source lengths.
    print(
        "\nACTUAL LENGTH:",
        len(mock_sandbox.received_request.source_code),
    )

    print(
        "EXPECTED LENGTH:",
        len(UPDATED_SOURCE),
    )

    # DEBUG 4: Original patch.
    print(
        "\nPATCH:",
        repr(VALID_PATCH),
    )

    # DEBUG 5: Direct patch application.
    direct_result = service.apply_patch_in_workspace(
        original_source=SOURCE_CODE,
        patch=VALID_PATCH,
        file_path="src/calculator.py",
    )

    print(
        "\nDIRECT APPLY:",
        repr(direct_result),
    )

    print(
        "DIRECT APPLY LENGTH:",
        len(direct_result),
    )

    # Existing assertions.
    assert (
        mock_sandbox.received_request.source_code
        == UPDATED_SOURCE
    )

    assert (
        mock_sandbox.received_request.source_filename
        == "src/calculator.py"
    )

    assert (
        mock_sandbox.received_request.test_filename
        == "test_calculator.py"
    )


def test_validate_and_execute_rejects_empty_tests(service):

    with pytest.raises(HTTPException) as exc:
        asyncio.run(
            service.validate_and_execute(
                file_path="src/calculator.py",
                original_source=SOURCE_CODE,
                patch=VALID_PATCH,
                language=SandboxLanguage.PYTHON,
                test_code="",
            )
        )

    assert exc.value.status_code == 422


def test_validate_and_execute_rejects_invalid_language(
    service,
):

    with pytest.raises(HTTPException) as exc:
        asyncio.run(
            service.validate_and_execute(
                file_path="Calculator.java",
                original_source=SOURCE_CODE,
                patch=VALID_PATCH,
                language=SandboxLanguage.PYTHON,
                test_code="print('hello')",
            )
        )

    assert exc.value.status_code == 422


def test_validate_and_execute_rejects_oversized_tests(
    service,
):

    test_code = "a" * (50 * 1024 + 1)

    with pytest.raises(HTTPException) as exc:
        asyncio.run(
            service.validate_and_execute(
                file_path="src/calculator.py",
                original_source=SOURCE_CODE,
                patch=VALID_PATCH,
                language=SandboxLanguage.PYTHON,
                test_code=test_code,
            )
        )

    assert exc.value.status_code == 413


def test_validate_and_execute_maps_sandbox_error():

    mock_sandbox = MockSandboxService(
        error=RuntimeError("Docker execution failed")
    )

    service = PatchValidationService(
        sandbox_service=mock_sandbox
    )

    with pytest.raises(HTTPException) as exc:
        asyncio.run(
            service.validate_and_execute(
                file_path="src/calculator.py",
                original_source=SOURCE_CODE,
                patch=VALID_PATCH,
                language=SandboxLanguage.PYTHON,
                test_code="def test_add():\n    assert True\n",
            )
        )

    assert exc.value.status_code == 502
