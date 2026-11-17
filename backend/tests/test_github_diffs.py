
from unittest.mock import AsyncMock, patch

import httpx
import pytest
from fastapi import HTTPException

from app.services.git_service import (
    extract_github_repository,
    normalize_changed_file,
    calculate_diff_summary,
    fetch_github_pull_requests,
    fetch_github_pull_request_diff,
    fetch_github_commit_diff,
)


def test_extract_github_repository():
    owner, repo = extract_github_repository(
        "https://github.com/example/RepoPilot-AI"
    )

    assert owner == "example"
    assert repo == "RepoPilot-AI"


def test_normalize_changed_file():
    result = normalize_changed_file({
        "filename": "app/main.py",
        "status": "modified",
        "additions": 10,
        "deletions": 5,
        "changes": 15,
        "patch": "@@ -1 +1 @@",
    })

    assert result["filename"] == "app/main.py"
    assert result["status"] == "modified"
    assert result["additions"] == 10
    assert result["deletions"] == 5
    assert result["changes"] == 15
    assert result["patch_available"] is True


def test_normalize_binary_file_without_patch():
    result = normalize_changed_file({
        "filename": "image.png",
        "status": "added",
        "additions": 0,
        "deletions": 0,
        "changes": 0,
    })

    assert result["filename"] == "image.png"
    assert result["patch"] is None
    assert result["patch_available"] is False


def test_calculate_diff_summary():
    files = [
        {
            "additions": 10,
            "deletions": 2,
            "changes": 12,
        },
        {
            "additions": 5,
            "deletions": 3,
            "changes": 8,
        },
    ]

    result = calculate_diff_summary(files)

    assert result == {
        "total_files": 2,
        "additions": 15,
        "deletions": 5,
        "changes": 20,
    }


@pytest.mark.asyncio
async def test_fetch_pull_requests():
    github_response = [
        {
            "number": 10,
            "title": "Fix authentication",
            "state": "open",
            "user": {"login": "developer"},
            "html_url": "https://github.com/example/repo/pull/10",
            "base": {"ref": "main"},
            "head": {"ref": "feature/auth"},
        }
    ]

    with patch(
        "app.services.git_service.github_api_get",
        new_callable=AsyncMock,
        return_value=github_response,
    ):
        result = await fetch_github_pull_requests(
            "example",
            "repo",
            "open",
        )

    assert result["repository"] == "example/repo"
    assert result["count"] == 1
    assert result["pull_requests"][0]["number"] == 10
    assert result["pull_requests"][0]["head_branch"] == "feature/auth"


@pytest.mark.asyncio
async def test_fetch_pull_requests_invalid_state():
    with pytest.raises(HTTPException) as exc:
        await fetch_github_pull_requests(
            "example",
            "repo",
            "invalid",
        )

    assert exc.value.status_code == 422


@pytest.mark.asyncio
async def test_fetch_pull_request_diff():
    pr_data = {
        "number": 10,
        "title": "Add authentication",
        "base": {"sha": "a" * 40},
        "head": {"sha": "b" * 40},
    }

    files_data = [
        {
            "filename": "app/auth.py",
            "status": "modified",
            "additions": 10,
            "deletions": 2,
            "changes": 12,
            "patch": "@@ -1 +1 @@",
        }
    ]

    with patch(
        "app.services.git_service.github_api_get",
        new_callable=AsyncMock,
        side_effect=[pr_data, files_data],
    ):
        result = await fetch_github_pull_request_diff(
            "example",
            "repo",
            10,
        )

    assert result["diff_type"] == "pull_request"
    assert result["identifier"] == "10"
    assert result["title"] == "Add authentication"
    assert result["total_files"] == 1
    assert result["additions"] == 10
    assert result["deletions"] == 2
    assert result["files"][0]["filename"] == "app/auth.py"
    assert result["files"][0]["patch_available"] is True


@pytest.mark.asyncio
async def test_fetch_pull_request_diff_invalid_number():
    with pytest.raises(HTTPException) as exc:
        await fetch_github_pull_request_diff(
            "example",
            "repo",
            0,
        )

    assert exc.value.status_code == 422


@pytest.mark.asyncio
async def test_fetch_commit_diff():
    commit_data = {
        "sha": "a" * 40,
        "commit": {
            "message": "Fix database connection"
        },
        "files": [
            {
                "filename": "app/db/session.py",
                "status": "modified",
                "additions": 4,
                "deletions": 1,
                "changes": 5,
                "patch": "@@ -1 +1 @@",
            }
        ],
    }

    with patch(
        "app.services.git_service.github_api_get",
        new_callable=AsyncMock,
        return_value=commit_data,
    ):
        result = await fetch_github_commit_diff(
            "example",
            "repo",
            "a" * 40,
        )

    assert result["diff_type"] == "commit"
    assert result["message"] == "Fix database connection"
    assert result["total_files"] == 1
    assert result["additions"] == 4
    assert result["deletions"] == 1


@pytest.mark.asyncio
async def test_fetch_commit_diff_invalid_sha():
    with pytest.raises(HTTPException) as exc:
        await fetch_github_commit_diff(
            "example",
            "repo",
            "invalid-sha",
        )

    assert exc.value.status_code == 422


@pytest.mark.asyncio
async def test_github_api_timeout():
    from app.services.git_service import github_api_get

    with patch(
        "httpx.AsyncClient.get",
        new_callable=AsyncMock,
        side_effect=httpx.TimeoutException("timeout"),
    ):
        with pytest.raises(HTTPException) as exc:
            await github_api_get(
                "https://api.github.com/repos/example/repo",
                "test request",
            )

    assert exc.value.status_code == 504
