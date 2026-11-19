from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.services.code_review_service import CodeReviewService


@pytest.fixture
def sample_diff():
    return {
        "repository": "owner/repo",
        "diff_type": "pull_request",
        "identifier": "12",
        "title": "Fix authentication",
        "files": [
            {
                "filename": "app/auth.py",
                "status": "modified",
                "additions": 3,
                "deletions": 1,
                "patch": (
                    "@@ -10,1 +10,3 @@\n"
                    "+if user is None:\n"
                    "+    raise Exception('Unauthorized')"
                ),
            }
        ],
    }


@pytest.fixture
def valid_llm_response():
    return """
    {
        "summary": "Authentication validation needs improvement.",
        "findings": [
            {
                "severity": "high",
                "title": "Generic exception used",
                "location": {
                    "file_path": "app/auth.py",
                    "start_line": 11,
                    "end_line": 11
                },
                "evidence": "raise Exception('Unauthorized')",
                "explanation": "A generic exception can hide the actual error type.",
                "suggestion": "Use an appropriate HTTP or authentication exception.",
                "rule_id": "ERR001",
                "confidence": 0.95
            }
        ]
    }
    """


@pytest.mark.asyncio
async def test_review_code_changes_success(
    monkeypatch,
    sample_diff,
    valid_llm_response,
):
    from app.services import code_review_service

    mock_retrieval = monkeypatch.setattr(
        code_review_service,
        "retrieve_repository_chunks",
        lambda **kwargs: [
            {
                "file_path": "app/auth.py",
                "symbol_name": "authenticate",
                "start_line": 1,
                "end_line": 20,
                "content": "def authenticate(user): ...",
                "score": 0.92,
            }
        ],
    )

    mock_llm = AsyncMock()
    mock_llm.generate.return_value = SimpleNamespace(
        text=valid_llm_response
    )

    monkeypatch.setattr(
        code_review_service,
        "LLMService",
        lambda: mock_llm,
    )

    service = CodeReviewService()

    result = await service.review_code_changes(
        repository_id=1,
        diff=sample_diff,
    )

    assert result.repository == "owner/repo"
    assert result.identifier == "12"
    assert result.diff_type.value == "pull_request"

    assert len(result.findings) == 1
    assert result.findings[0].severity.value == "high"

    assert result.statistics.high == 1
    assert result.statistics.total_findings == 1

    mock_llm.generate.assert_awaited_once()


@pytest.mark.asyncio
async def test_review_rejects_invalid_repository_id(
    sample_diff,
):
    service = CodeReviewService()

    with pytest.raises(ValueError):
        await service.review_code_changes(
            repository_id=0,
            diff=sample_diff,
        )


@pytest.mark.asyncio
async def test_review_rejects_empty_diff():
    service = CodeReviewService()

    diff = {
        "repository": "owner/repo",
        "diff_type": "pull_request",
        "identifier": "12",
        "files": [],
    }

    with pytest.raises(
        ValueError,
        match="No changed files",
    ):
        await service.review_code_changes(
            repository_id=1,
            diff=diff,
        )


def test_parse_valid_json(valid_llm_response):
    result = CodeReviewService._parse_llm_response(
        valid_llm_response
    )

    assert result["summary"]


def test_parse_json_with_markdown_fence():
    response = """```json
    {"summary": "No issues found", "findings": []}
    ```"""

    result = CodeReviewService._parse_llm_response(response)

    assert result["summary"] == "No issues found"


def test_parse_invalid_json():
    with pytest.raises(
        ValueError,
        match="invalid JSON",
    ):
        CodeReviewService._parse_llm_response(
            "This is not JSON"
        )


def test_parse_empty_response():
    with pytest.raises(
        ValueError,
        match="empty",
    ):
        CodeReviewService._parse_llm_response("")