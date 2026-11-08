
import httpx

from pathlib import PurePosixPath
from urllib.parse import quote

from fastapi import HTTPException

from app.core.config import settings
from app.utils.file_filters import (
    ALLOWED_EXTENSIONS,
    MAX_FILE_SIZE,
    MAX_TOTAL_SIZE,
    MAX_FILES,
    should_exclude_file,
)


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

    for file_info in selected_files:

        encoded_path = quote(
            file_info["path"],
            safe="/",
        )

        file_info["url"] = (
            f"https://raw.githubusercontent.com/{owner}/{repo}/"
            f"{encoded_branch}/{encoded_path}"
        )

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
