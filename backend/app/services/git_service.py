
import base64
import logging

from pathlib import PurePosixPath
from urllib.parse import quote
from typing import Any

import httpx

from fastapi import HTTPException

from app.core.config import settings
from app.utils.file_filters import (
    ALLOWED_EXTENSIONS,
    MAX_FILE_SIZE,
    MAX_TOTAL_SIZE,
    MAX_FILES,
    should_exclude_file,
)


logger = logging.getLogger(__name__)


GITHUB_API_BASE_URL = "https://api.github.com"

GITHUB_HEADERS = {
    "Accept": "application/vnd.github+json",
    "User-Agent": "RepoPilot-AI",
    "X-GitHub-Api-Version": "2022-11-28",
}


def get_github_headers() -> dict:
    """
    Return GitHub API headers.

    Uses authenticated requests when GITHUB_TOKEN is configured.
    Never logs or exposes the token.
    """

    headers = GITHUB_HEADERS.copy()

    token = (settings.github_token or "").strip()

    if token:
        headers["Authorization"] = f"Bearer {token}"

    return headers


def _raise_github_error(
    response: httpx.Response,
    operation: str,
):
    """Raise a useful error containing GitHub's actual response."""

    status_code = response.status_code
    response_text = response.text[:500]

    if status_code == 404:
        raise HTTPException(
            status_code=404,
            detail=(
                f"GitHub {operation}: "
                "repository or resource not found."
            ),
        )

    # GitHub returns 422 for a syntactically valid but
    # non-existent commit SHA.
    if status_code == 422 and operation == "commit diff request":

        try:
            github_message = (
                response.json().get("message", "")
            )
        except (ValueError, AttributeError):
            github_message = ""

        if "no commit found for sha" in github_message.lower():
            raise HTTPException(
                status_code=404,
                detail="Commit not found in the GitHub repository.",
            )

    if status_code == 401:
        raise HTTPException(
            status_code=502,
            detail=(
                f"GitHub {operation} returned 401. "
                "The configured GitHub token is invalid or expired."
            ),
        )

    if status_code == 403:
        remaining = response.headers.get(
            "X-RateLimit-Remaining",
            "unknown",
        )

        reset = response.headers.get(
            "X-RateLimit-Reset",
            "unknown",
        )

        raise HTTPException(
            status_code=502,
            detail=(
                f"GitHub {operation} returned 403. "
                f"Rate limit remaining: {remaining}. "
                f"Rate limit reset: {reset}. "
                f"Response: {response_text}"
            ),
        )

    raise HTTPException(
        status_code=502,
        detail=(
            f"GitHub {operation} failed. "
            f"HTTP status: {status_code}. "
            f"Response: {response_text}"
        ),
    )


async def fetch_github_repo(owner: str, repo: str):

    url = f"{GITHUB_API_BASE_URL}/repos/{owner}/{repo}"

    async with httpx.AsyncClient(
        timeout=20.0,
        follow_redirects=True,
        headers=get_github_headers(),
    ) as client:

        try:
            response = await client.get(url)

        except httpx.RequestError as exc:
            raise HTTPException(
                status_code=502,
                detail=f"Unable to connect to GitHub: {str(exc)}",
            ) from exc

        if response.status_code != 200:
            _raise_github_error(
                response,
                "repository metadata request",
            )

        data = response.json()

        programming_languages = []

        languages_url = data.get("languages_url")

        if languages_url:
            try:
                languages_response = await client.get(
                    languages_url
                )

                if languages_response.status_code == 200:
                    languages_payload = (
                        languages_response.json() or {}
                    )

                    if isinstance(languages_payload, dict):
                        programming_languages = sorted(
                            languages_payload.keys()
                        )

                elif languages_response.status_code in (401, 403):
                    _raise_github_error(
                        languages_response,
                        "repository languages request",
                    )

            except (httpx.RequestError, ValueError):
                programming_languages = []

        latest_commit_sha = None

        default_branch = data.get("default_branch")

        if default_branch:
            encoded_branch = quote(
                default_branch,
                safe="",
            )

            commit_url = (
                f"{GITHUB_API_BASE_URL}/repos/{owner}/{repo}"
                f"/commits/{encoded_branch}"
            )

            try:
                commit_response = await client.get(
                    commit_url
                )

                if commit_response.status_code == 200:
                    commit_data = (
                        commit_response.json() or {}
                    )

                    if isinstance(commit_data, dict):
                        latest_commit_sha = commit_data.get(
                            "sha"
                        )

                elif commit_response.status_code in (401, 403):
                    _raise_github_error(
                        commit_response,
                        "latest commit request",
                    )

            except (httpx.RequestError, ValueError):
                latest_commit_sha = None

    return {
        "name": data.get("name"),
        "full_name": data.get("full_name"),
        "description": data.get("description"),
        "github_url": data.get("html_url"),
        "stars": data.get("stargazers_count", 0),
        "forks": data.get("forks_count", 0),
        "language": data.get("language"),
        "default_branch": default_branch,
        "latest_commit_sha": latest_commit_sha,
        "programming_languages": programming_languages,
    }


def filter_repository_files(tree: list):

    selected_files = []
    total_size = 0
    seen_paths = set()

    for file in tree:

        if file.get("type") != "blob":
            continue

        path = file.get("path")

        if not path or path in seen_paths:
            continue

        seen_paths.add(path)

        file_path = PurePosixPath(path)
        extension = file_path.suffix.lower()

        if should_exclude_file(path):
            continue

        if extension not in ALLOWED_EXTENSIONS:
            continue

        file_size = file.get("size")

        if not isinstance(file_size, int) or file_size < 0:
            continue

        if file_size > MAX_FILE_SIZE:
            continue

        if len(selected_files) >= MAX_FILES:
            break

        if total_size + file_size > MAX_TOTAL_SIZE:
            continue

        selected_files.append({
            "path": path,
            "sha": file.get("sha"),
            "size": file_size,
            "url": file.get("url"),
        })

        total_size += file_size

    return selected_files


async def fetch_github_tree(owner: str, repo: str):

    repo_data = await fetch_github_repo(
        owner,
        repo,
    )

    branch = repo_data["default_branch"]

    if not branch:
        raise HTTPException(
            status_code=502,
            detail=(
                "GitHub repository does not have "
                "a default branch."
            ),
        )

    encoded_branch = quote(
        branch,
        safe="",
    )

    url = (
        f"{GITHUB_API_BASE_URL}/repos/{owner}/{repo}"
        f"/git/trees/{encoded_branch}?recursive=1"
    )

    async with httpx.AsyncClient(
        timeout=30.0,
        follow_redirects=True,
        headers=get_github_headers(),
    ) as client:

        try:
            response = await client.get(url)

        except httpx.RequestError as exc:
            raise HTTPException(
                status_code=502,
                detail=(
                    "Unable to fetch GitHub repository tree: "
                    f"{str(exc)}"
                ),
            ) from exc

    if response.status_code != 200:
        _raise_github_error(
            response,
            "repository tree request",
        )

    data = response.json()

    tree = data.get("tree", [])

    if data.get("truncated", False):
        raise HTTPException(
            status_code=502,
            detail=(
                "GitHub repository tree is truncated. "
                "Complete repository discovery is not possible."
            ),
        )

    selected_files = filter_repository_files(tree)

    total_files = sum(
        1
        for file in tree
        if file.get("type") == "blob"
    )

    return {
        "repository": repo_data["full_name"],
        "default_branch": branch,
        "tree_sha": data.get("sha"),
        "latest_commit_sha": repo_data.get(
            "latest_commit_sha"
        ),
        "languages": repo_data.get(
            "programming_languages",
            [],
        ),
        "truncated": False,
        "total_files": total_files,
        "included_files": len(selected_files),
        "skipped_files": total_files - len(selected_files),
        "total_size": sum(
            file["size"]
            for file in selected_files
        ),
        "files": selected_files,
    }


# =========================================================
# WEEK 5 - DAY 1: GITHUB DIFF INGESTION
# =========================================================

MAX_DIFF_FILES = 300
GITHUB_PAGE_SIZE = 100


def extract_github_repository(github_url: str) -> tuple[str, str]:
    """
    Extract GitHub owner and repository from a stored URL.
    """

    from app.repositories.repository_repository import (
        normalize_github_url,
    )

    normalized_url = normalize_github_url(github_url)

    parts = [
        part
        for part in normalized_url.rstrip("/").split("/")
        if part
    ]

    if len(parts) != 4:
        raise HTTPException(
            status_code=422,
            detail="Invalid stored GitHub repository URL",
        )

    return parts[2], parts[3]


async def github_api_get(
    url: str,
    operation: str,
    accept: str = "application/vnd.github+json",
) -> Any:
    """
    Make an authenticated GitHub API GET request.

    The GitHub token is never returned or logged.
    """

    headers = get_github_headers()
    headers["Accept"] = accept

    async with httpx.AsyncClient(
        timeout=30.0,
        follow_redirects=True,
        headers=headers,
    ) as client:

        try:
            response = await client.get(url)

        except httpx.TimeoutException as exc:
            raise HTTPException(
                status_code=504,
                detail=f"GitHub {operation} request timed out",
            ) from exc

        except httpx.RequestError as exc:
            raise HTTPException(
                status_code=502,
                detail=f"Unable to connect to GitHub for {operation}",
            ) from exc

    if response.status_code != 200:
        _raise_github_error(response, operation)

    try:
        return response.json()

    except ValueError as exc:
        raise HTTPException(
            status_code=502,
            detail=f"GitHub returned invalid JSON for {operation}",
        ) from exc


def normalize_pull_request(data: dict) -> dict:
    """
    Convert GitHub PR JSON into our API response format.
    """

    return {
        "number": data["number"],
        "title": data.get("title", ""),
        "state": data.get("state", ""),
        "user_login": (
            (data.get("user") or {}).get("login")
        ),
        "html_url": data.get("html_url", ""),
        "base_branch": (
            (data.get("base") or {}).get("ref", "")
        ),
        "head_branch": (
            (data.get("head") or {}).get("ref", "")
        ),
        "created_at": data.get("created_at"),
        "updated_at": data.get("updated_at"),
    }


async def fetch_github_pull_requests(
    owner: str,
    repo: str,
    state: str = "open",
) -> dict:
    """
    Fetch Pull Requests from GitHub.

    Supported states: open, closed, all.
    """

    if state not in {"open", "closed", "all"}:
        raise HTTPException(
            status_code=422,
            detail="State must be open, closed, or all",
        )

    url = (
        f"{GITHUB_API_BASE_URL}/repos/"
        f"{quote(owner, safe='')}/{quote(repo, safe='')}"
        f"/pulls?state={state}&per_page=100"
    )

    data = await github_api_get(
        url,
        "pull request list request",
    )

    if not isinstance(data, list):
        raise HTTPException(
            status_code=502,
            detail="Invalid GitHub pull request response",
        )

    return {
        "repository": f"{owner}/{repo}",
        "count": len(data),
        "pull_requests": [
            normalize_pull_request(item)
            for item in data
        ],
    }


def normalize_changed_file(data: dict) -> dict:
    """
    Normalize GitHub changed-file information.

    GitHub may omit patch for binary or large files.
    """

    patch = data.get("patch")

    return {
        "filename": data.get("filename", ""),
        "status": data.get("status", "unknown"),
        "additions": data.get("additions", 0),
        "deletions": data.get("deletions", 0),
        "changes": data.get("changes", 0),
        "patch": patch,
        "patch_available": isinstance(patch, str),
        "blob_url": data.get("blob_url"),
        "raw_url": data.get("raw_url"),
    }


def calculate_diff_summary(
    files: list[dict],
) -> dict:
    """
    Calculate total additions, deletions and changes.
    """

    return {
        "total_files": len(files),
        "additions": sum(
            item["additions"] for item in files
        ),
        "deletions": sum(
            item["deletions"] for item in files
        ),
        "changes": sum(
            item["changes"] for item in files
        ),
    }


async def fetch_github_pull_request_diff(
    owner: str,
    repo: str,
    pull_number: int,
) -> dict:
    """
    Fetch PR metadata and all available changed-file patches.

    GitHub PR files endpoint supports pagination.
    """

    if pull_number < 1:
        raise HTTPException(
            status_code=422,
            detail="Pull request number must be positive",
        )

    repository_path = (
        f"{quote(owner, safe='')}/{quote(repo, safe='')}"
    )

    pr_url = (
        f"{GITHUB_API_BASE_URL}/repos/"
        f"{repository_path}/pulls/{pull_number}"
    )

    pr_data = await github_api_get(
        pr_url,
        "pull request details request",
    )

    files = []
    files_truncated = False

    for page in range(
        1,
        (MAX_DIFF_FILES // GITHUB_PAGE_SIZE) + 1,
    ):

        remaining = MAX_DIFF_FILES - len(files)

        if remaining <= 0:
            files_truncated = True
            break

        per_page = min(
            GITHUB_PAGE_SIZE,
            remaining,
        )

        files_url = (
            f"{GITHUB_API_BASE_URL}/repos/"
            f"{repository_path}/pulls/{pull_number}/files"
            f"?per_page={per_page}&page={page}"
        )

        page_data = await github_api_get(
            files_url,
            "pull request changed files request",
        )

        if not isinstance(page_data, list):
            raise HTTPException(
                status_code=502,
                detail="Invalid GitHub changed files response",
            )

        files.extend(
            normalize_changed_file(item)
            for item in page_data
        )

        if len(page_data) < per_page:
            break

        if len(files) >= MAX_DIFF_FILES:
            files_truncated = True
            break

    summary = calculate_diff_summary(files)

    head = pr_data.get("head") or {}
    base = pr_data.get("base") or {}

    return {
        "repository": f"{owner}/{repo}",
        "diff_type": "pull_request",
        "identifier": str(pull_number),
        "title": pr_data.get("title"),
        "message": None,
        "base_sha": base.get("sha"),
        "head_sha": head.get("sha"),
        **summary,
        "files_truncated": files_truncated,
        "files": files,
    }


async def fetch_github_commit_diff(
    owner: str,
    repo: str,
    commit_sha: str,
) -> dict:
    """
    Fetch commit metadata and changed files.
    """

    if (
        not commit_sha
        or len(commit_sha) > 255
        or not all(
            character in "0123456789abcdefABCDEF"
            for character in commit_sha
        )
    ):
        raise HTTPException(
            status_code=422,
            detail="Invalid commit SHA",
        )

    repository_path = (
        f"{quote(owner, safe='')}/{quote(repo, safe='')}"
    )

    url = (
        f"{GITHUB_API_BASE_URL}/repos/"
        f"{repository_path}/commits/"
        f"{quote(commit_sha, safe='')}"
    )

    data = await github_api_get(
        url,
        "commit diff request",
    )

    raw_files = data.get("files", [])

    if not isinstance(raw_files, list):
        raise HTTPException(
            status_code=502,
            detail="Invalid GitHub commit files response",
        )

    files_truncated = len(raw_files) >= MAX_DIFF_FILES

    files = [
        normalize_changed_file(item)
        for item in raw_files[:MAX_DIFF_FILES]
    ]

    summary = calculate_diff_summary(files)

    commit = data.get("commit") or {}
    message = commit.get("message")

    return {
        "repository": f"{owner}/{repo}",
        "diff_type": "commit",
        "identifier": data.get("sha", commit_sha),
        "title": None,
        "message": message,
        "base_sha": None,
        "head_sha": data.get("sha", commit_sha),
        **summary,
        "files_truncated": files_truncated,
        "files": files,
    }


async def fetch_github_file_content(
    owner: str,
    repo: str,
    file_path: str,
    ref: str,
) -> str | None:
    """
    Fetch complete source code of a file from GitHub.

    Uses the GitHub Contents API at a specific commit SHA.
    Returns None when source content is unavailable.
    """

    if not owner or not repo or not file_path or not ref:
        return None

    encoded_owner = quote(owner, safe="")
    encoded_repo = quote(repo, safe="")
    encoded_path = quote(file_path, safe="/")
    encoded_ref = quote(ref, safe="")

    url = (
        f"{GITHUB_API_BASE_URL}/repos/"
        f"{encoded_owner}/{encoded_repo}/contents/"
        f"{encoded_path}?ref={encoded_ref}"
    )

    try:
        data = await github_api_get(
            url,
            "changed source file request",
        )

    except HTTPException as exc:

        if exc.status_code == 404:
            logger.warning(
                "Source file not found: %s",
                file_path,
            )
            return None

        raise

    if not isinstance(data, dict):
        return None

    if data.get("type") != "file":
        return None

    if data.get("encoding") != "base64":
        return None

    encoded_content = data.get("content")

    if not isinstance(encoded_content, str):
        return None

    try:
        decoded = base64.b64decode(
            encoded_content,
            validate=False,
        )

        return decoded.decode("utf-8")

    except (ValueError, UnicodeDecodeError):
        logger.warning(
            "Unable to decode source file: %s",
            file_path,
        )
        return None
