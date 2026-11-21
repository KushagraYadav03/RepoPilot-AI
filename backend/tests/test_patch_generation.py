
import asyncio
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

import app.services.patch_generation_service as patch_module

from app.services.patch_generation_service import PatchGenerationService


# =========================================================
# TEST DATA
# =========================================================

def get_review_data(file_path="app/main.py"):
    return {
        "repository": "owner/repo",
        "diff_type": "pull_request",
        "identifier": "123",
        "title": "Code Review",
        "summary": "Review summary",
        "findings": [
            {
                "severity": "high",
                "title": "Incorrect calculation",
                "location": {
                    "file_path": file_path,
                    "start_line": 1,
                    "end_line": 2,
                },
                "evidence": "return a - b",
                "explanation": "Incorrect calculation",
                "suggestion": "Use addition",
                "rule_id": "PY001",
                "confidence": 0.95,
            }
        ],
    }


def get_diff_data(file_path="app/main.py"):
    return {
        "head_sha": "abc123",
        "files": [
            {
                "filename": file_path,
                "status": "modified",
            }
        ],
    }


ORIGINAL_SOURCE = (
    "def calculate(a, b):\n"
    "    return a - b\n"
)

UPDATED_SOURCE = (
    "def calculate(a, b):\n"
    "    return a + b\n"
)


def create_service(monkeypatch, generate=None):
    """
    Create service with a mocked LLM.
    """

    monkeypatch.setattr(
        patch_module,
        "LLMService",
        lambda: SimpleNamespace(generate=generate),
    )

    return PatchGenerationService()


def run_generate_patch(service, **kwargs):
    return asyncio.run(
        service.generate_patch(**kwargs)
    )


def valid_generate_kwargs():
    return {
        "owner": "owner",
        "repo": "repo",
        "review_data": get_review_data(),
        "diff_data": get_diff_data(),
        "finding_index": 0,
    }


# =========================================================
# FILE PATH VALIDATION
# =========================================================

@pytest.mark.parametrize(
    "file_path",
    [
        "app/main.py",
        "tests/test_main.py",
        "src/services/example.py",
        "README.md",
    ],
)
def test_validate_file_path_accepts_valid_paths(file_path):
    result = PatchGenerationService.validate_file_path(
        file_path
    )

    assert result == file_path


@pytest.mark.parametrize(
    "file_path",
    [
        "",
        "   ",
        None,
        123,
        "/etc/passwd",
        "../secret.py",
        "app/../secret.py",
        "./app/main.py",
        "app//main.py",
        "app\\main.py",
        "app/main.py/",
        "app/\x00main.py",
    ],
)
def test_validate_file_path_rejects_invalid_paths(file_path):
    with pytest.raises(HTTPException) as exc:
        PatchGenerationService.validate_file_path(
            file_path
        )

    assert exc.value.status_code == 422


# =========================================================
# FINDING SELECTION
# =========================================================

def test_select_finding_returns_correct_finding():
    finding = PatchGenerationService.select_finding(
        get_review_data(),
        0,
    )

    assert finding.title == "Incorrect calculation"
    assert finding.severity.value == "high"
    assert finding.location.file_path == "app/main.py"


@pytest.mark.parametrize(
    "finding_index",
    [
        -1,
        True,
        False,
        1.5,
        "0",
        None,
    ],
)
def test_select_finding_rejects_invalid_index(finding_index):
    with pytest.raises(HTTPException) as exc:
        PatchGenerationService.select_finding(
            get_review_data(),
            finding_index,
        )

    assert exc.value.status_code == 422


def test_select_finding_rejects_out_of_range_index():
    with pytest.raises(HTTPException) as exc:
        PatchGenerationService.select_finding(
            get_review_data(),
            1,
        )

    assert exc.value.status_code == 404


def test_select_finding_rejects_invalid_review_data():
    with pytest.raises(HTTPException) as exc:
        PatchGenerationService.select_finding(
            {"invalid": "data"},
            0,
        )

    assert exc.value.status_code == 422


def test_select_finding_rejects_empty_findings():
    review_data = get_review_data()
    review_data["findings"] = []

    with pytest.raises(HTTPException) as exc:
        PatchGenerationService.select_finding(
            review_data,
            0,
        )

    assert exc.value.status_code == 404


# =========================================================
# CHANGED FILE VALIDATION
# =========================================================

def test_validate_changed_file_accepts_changed_file():
    finding = PatchGenerationService.select_finding(
        get_review_data(),
        0,
    )

    result = PatchGenerationService.validate_changed_file(
        finding,
        get_diff_data(),
    )

    assert result == "app/main.py"


def test_validate_changed_file_rejects_unchanged_file():
    finding = PatchGenerationService.select_finding(
        get_review_data(),
        0,
    )

    diff_data = {
        "files": [
            {"filename": "app/other.py"}
        ]
    }

    with pytest.raises(HTTPException) as exc:
        PatchGenerationService.validate_changed_file(
            finding,
            diff_data,
        )

    assert exc.value.status_code == 422


def test_validate_changed_file_rejects_invalid_files():
    finding = PatchGenerationService.select_finding(
        get_review_data(),
        0,
    )

    with pytest.raises(HTTPException) as exc:
        PatchGenerationService.validate_changed_file(
            finding,
            {"files": "invalid"},
        )

    assert exc.value.status_code == 502


def test_validate_changed_file_rejects_missing_location():
    finding = SimpleNamespace(location=None)

    with pytest.raises(HTTPException) as exc:
        PatchGenerationService.validate_changed_file(
            finding,
            get_diff_data(),
        )

    assert exc.value.status_code == 422


# =========================================================
# GENERATED SOURCE EXTRACTION
# =========================================================

def test_extract_generated_source_accepts_plain_source():
    result = PatchGenerationService.extract_generated_source(
        UPDATED_SOURCE
    )

    assert result == UPDATED_SOURCE


def test_extract_generated_source_removes_markdown_fences():
    response = (
        "```python\n"
        "def calculate(a, b):\n"
        "    return a + b\n"
        "```"
    )

    result = PatchGenerationService.extract_generated_source(
        response
    )

    assert result == UPDATED_SOURCE


def test_extract_generated_source_adds_trailing_newline():
    result = PatchGenerationService.extract_generated_source(
        "print('hello')"
    )

    assert result.endswith("\n")


@pytest.mark.parametrize(
    "response",
    [
        "",
        "   ",
        None,
        123,
    ],
)
def test_extract_generated_source_rejects_invalid_response(response):
    with pytest.raises(HTTPException) as exc:
        PatchGenerationService.extract_generated_source(
            response
        )

    assert exc.value.status_code == 502


# =========================================================
# PYTHON SYNTAX VALIDATION
# =========================================================

def test_validate_python_syntax_accepts_valid_code():
    PatchGenerationService.validate_python_syntax(
        ORIGINAL_SOURCE,
        UPDATED_SOURCE,
        "app/main.py",
    )


def test_validate_python_syntax_rejects_invalid_generated_code():
    with pytest.raises(HTTPException) as exc:
        PatchGenerationService.validate_python_syntax(
            ORIGINAL_SOURCE,
            "def calculate(:\n    return 1\n",
            "app/main.py",
        )

    assert exc.value.status_code == 422
    assert "syntax error" in exc.value.detail.lower()


def test_validate_python_syntax_skips_non_python_files():
    PatchGenerationService.validate_python_syntax(
        "valid source",
        "invalid source",
        "app/main.java",
    )


def test_validate_python_syntax_skips_invalid_original_source():
    PatchGenerationService.validate_python_syntax(
        "def calculate(:",
        "def calculate(:",
        "app/main.py",
    )


# =========================================================
# UNIFIED DIFF GENERATION
# =========================================================

def test_build_unified_diff_generates_patch():
    patch = PatchGenerationService.build_unified_diff(
        ORIGINAL_SOURCE,
        UPDATED_SOURCE,
        "app/main.py",
    )

    assert "--- a/app/main.py" in patch
    assert "+++ b/app/main.py" in patch
    assert "-    return a - b" in patch
    assert "+    return a + b" in patch


def test_build_unified_diff_rejects_empty_patch():
    with pytest.raises(HTTPException) as exc:
        PatchGenerationService.build_unified_diff(
            ORIGINAL_SOURCE,
            ORIGINAL_SOURCE,
            "app/main.py",
        )

    assert exc.value.status_code == 422


def test_build_unified_diff_rejects_oversized_patch(monkeypatch):
    monkeypatch.setattr(
        patch_module,
        "MAX_PATCH_SIZE",
        1,
    )

    with pytest.raises(HTTPException) as exc:
        PatchGenerationService.build_unified_diff(
            ORIGINAL_SOURCE,
            UPDATED_SOURCE,
            "app/main.py",
        )

    assert exc.value.status_code == 413


# =========================================================
# PATCH GENERATION INTEGRATION TESTS
# =========================================================

def test_generate_patch_success(monkeypatch):

    async def mock_generate(**kwargs):
        assert kwargs["temperature"] == 0.1
        assert kwargs["max_output_tokens"] == 8192

        return SimpleNamespace(
            text=UPDATED_SOURCE
        )

    service = create_service(
        monkeypatch,
        mock_generate,
    )

    async def mock_fetch(**kwargs):
        assert kwargs["owner"] == "owner"
        assert kwargs["repo"] == "repo"
        assert kwargs["file_path"] == "app/main.py"
        assert kwargs["ref"] == "abc123"

        return ORIGINAL_SOURCE

    monkeypatch.setattr(
        patch_module,
        "fetch_github_file_content",
        mock_fetch,
    )

    result = run_generate_patch(
        service,
        **valid_generate_kwargs(),
    )

    assert result["file_path"] == "app/main.py"
    assert result["finding_index"] == 0
    assert result["finding_title"] == "Incorrect calculation"
    assert result["severity"].value == "high"

    assert result["original_source"] == ORIGINAL_SOURCE
    assert result["updated_source"] == UPDATED_SOURCE

    assert "return a + b" in result["patch"]

    assert result["patch_applied"] is False
    assert "preview only" in result["message"].lower()


def test_generate_patch_rejects_missing_owner(monkeypatch):
    service = create_service(monkeypatch)

    kwargs = valid_generate_kwargs()
    kwargs["owner"] = ""

    with pytest.raises(HTTPException) as exc:
        run_generate_patch(service, **kwargs)

    assert exc.value.status_code == 422


def test_generate_patch_rejects_missing_repo(monkeypatch):
    service = create_service(monkeypatch)

    kwargs = valid_generate_kwargs()
    kwargs["repo"] = ""

    with pytest.raises(HTTPException) as exc:
        run_generate_patch(service, **kwargs)

    assert exc.value.status_code == 422


def test_generate_patch_rejects_invalid_diff_data(monkeypatch):
    service = create_service(monkeypatch)

    kwargs = valid_generate_kwargs()
    kwargs["diff_data"] = []

    with pytest.raises(HTTPException) as exc:
        run_generate_patch(service, **kwargs)

    assert exc.value.status_code == 502


def test_generate_patch_rejects_missing_head_sha(monkeypatch):
    service = create_service(monkeypatch)

    kwargs = valid_generate_kwargs()
    kwargs["diff_data"]["head_sha"] = ""

    with pytest.raises(HTTPException) as exc:
        run_generate_patch(service, **kwargs)

    assert exc.value.status_code == 422


def test_generate_patch_handles_missing_github_file(monkeypatch):

    service = create_service(monkeypatch)

    async def mock_fetch(**kwargs):
        return None

    monkeypatch.setattr(
        patch_module,
        "fetch_github_file_content",
        mock_fetch,
    )

    with pytest.raises(HTTPException) as exc:
        run_generate_patch(
            service,
            **valid_generate_kwargs(),
        )

    assert exc.value.status_code == 404


def test_generate_patch_rejects_invalid_github_content(monkeypatch):

    service = create_service(monkeypatch)

    async def mock_fetch(**kwargs):
        return 123

    monkeypatch.setattr(
        patch_module,
        "fetch_github_file_content",
        mock_fetch,
    )

    with pytest.raises(HTTPException) as exc:
        run_generate_patch(
            service,
            **valid_generate_kwargs(),
        )

    assert exc.value.status_code == 502


def test_generate_patch_rejects_oversized_source(monkeypatch):

    service = create_service(monkeypatch)

    monkeypatch.setattr(
        patch_module,
        "MAX_SOURCE_FILE_SIZE",
        5,
    )

    async def mock_fetch(**kwargs):
        return "x" * 10

    monkeypatch.setattr(
        patch_module,
        "fetch_github_file_content",
        mock_fetch,
    )

    with pytest.raises(HTTPException) as exc:
        run_generate_patch(
            service,
            **valid_generate_kwargs(),
        )

    assert exc.value.status_code == 413


def test_generate_patch_handles_llm_exception(monkeypatch):

    async def mock_generate(**kwargs):
        raise RuntimeError("LLM unavailable")

    service = create_service(
        monkeypatch,
        mock_generate,
    )

    async def mock_fetch(**kwargs):
        return ORIGINAL_SOURCE

    monkeypatch.setattr(
        patch_module,
        "fetch_github_file_content",
        mock_fetch,
    )

    with pytest.raises(HTTPException) as exc:
        run_generate_patch(
            service,
            **valid_generate_kwargs(),
        )

    assert exc.value.status_code == 502


def test_generate_patch_rejects_empty_llm_response(monkeypatch):

    async def mock_generate(**kwargs):
        return SimpleNamespace(text="")

    service = create_service(
        monkeypatch,
        mock_generate,
    )

    async def mock_fetch(**kwargs):
        return ORIGINAL_SOURCE

    monkeypatch.setattr(
        patch_module,
        "fetch_github_file_content",
        mock_fetch,
    )

    with pytest.raises(HTTPException) as exc:
        run_generate_patch(
            service,
            **valid_generate_kwargs(),
        )

    assert exc.value.status_code == 502


def test_generate_patch_rejects_unchanged_source(monkeypatch):

    async def mock_generate(**kwargs):
        return SimpleNamespace(
            text=ORIGINAL_SOURCE
        )

    service = create_service(
        monkeypatch,
        mock_generate,
    )

    async def mock_fetch(**kwargs):
        return ORIGINAL_SOURCE

    monkeypatch.setattr(
        patch_module,
        "fetch_github_file_content",
        mock_fetch,
    )

    with pytest.raises(HTTPException) as exc:
        run_generate_patch(
            service,
            **valid_generate_kwargs(),
        )

    assert exc.value.status_code == 422
    assert "did not generate any changes" in exc.value.detail.lower()


def test_generate_patch_rejects_invalid_python_output(monkeypatch):

    async def mock_generate(**kwargs):
        return SimpleNamespace(
            text="def calculate(:\n    return 1\n"
        )

    service = create_service(
        monkeypatch,
        mock_generate,
    )

    async def mock_fetch(**kwargs):
        return ORIGINAL_SOURCE

    monkeypatch.setattr(
        patch_module,
        "fetch_github_file_content",
        mock_fetch,
    )

    with pytest.raises(HTTPException) as exc:
        run_generate_patch(
            service,
            **valid_generate_kwargs(),
        )

    assert exc.value.status_code == 422
    assert "syntax error" in exc.value.detail.lower()


def test_generate_patch_does_not_modify_github(monkeypatch):

    github_calls = []
    llm_calls = []

    async def mock_fetch(**kwargs):
        github_calls.append(kwargs)
        return ORIGINAL_SOURCE

    async def mock_generate(**kwargs):
        llm_calls.append(kwargs)
        return SimpleNamespace(text=UPDATED_SOURCE)

    service = create_service(
        monkeypatch,
        mock_generate,
    )

    monkeypatch.setattr(
        patch_module,
        "fetch_github_file_content",
        mock_fetch,
    )

    result = run_generate_patch(
        service,
        **valid_generate_kwargs(),
    )

    assert len(github_calls) == 1
    assert len(llm_calls) == 1

    assert result["patch_applied"] is False
    assert result["original_source"] == ORIGINAL_SOURCE
    assert result["updated_source"] == UPDATED_SOURCE
