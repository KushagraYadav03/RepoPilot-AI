
import httpx

from pathlib import PurePosixPath
from urllib.parse import quote

from fastapi import HTTPException


# File ingestion limits

MAX_FILE_SIZE = 1 * 1024 * 1024

MAX_TOTAL_SIZE = 10 * 1024 * 1024

MAX_FILES = 200


# Allowed file extensions

ALLOWED_EXTENSIONS = {
    ".py",
    ".java",
    ".js",
    ".jsx",
    ".ts",
    ".tsx",
    ".html",
    ".css",
    ".json",
    ".md",
    ".txt",
    ".yml",
    ".yaml",
    ".toml",
    ".sql",
    ".sh",
    ".xml",
    ".properties",
    ".go",
    ".rs",
    ".c",
    ".cpp",
    ".h",
    ".hpp",
    ".cs",
    ".php",
    ".rb",
    ".kt"
}


# Sensitive and unnecessary files to exclude

IGNORED_FILES = {
    ".env",
    ".env.local",
    ".env.production",
    "id_rsa",
    "id_ed25519",
    "package-lock.json",
    "yarn.lock",
    "pnpm-lock.yaml",
    "poetry.lock",
    "uv.lock",
    "Cargo.lock",
    "Gemfile.lock",
    "composer.lock"
}


# Folders to exclude

IGNORED_DIRECTORIES = {
    ".git",
    "node_modules",
    "venv",
    ".venv",
    "__pycache__",
    "dist",
    "build",
    ".idea",
    ".vscode",
    "coverage"
}


async def fetch_github_repo(owner: str, repo: str):

    url = f"https://api.github.com/repos/{owner}/{repo}"

    async with httpx.AsyncClient(
        timeout=10.0,
        follow_redirects=True
    ) as client:

        try:
            response = await client.get(
                url,
                headers={
                    "Accept": "application/vnd.github+json"
                }
            )

        except httpx.RequestError:
            raise HTTPException(
                status_code=502,
                detail="Unable to connect to GitHub"
            )

    if response.status_code == 404:
        raise HTTPException(
            status_code=404,
            detail="GitHub repository not found"
        )

    if response.status_code != 200:
        raise HTTPException(
            status_code=502,
            detail="GitHub API request failed"
        )

    data = response.json()

    return {
        "name": data["name"],
        "full_name": data["full_name"],
        "description": data["description"],
        "github_url": data["html_url"],
        "stars": data["stargazers_count"],
        "forks": data["forks_count"],
        "language": data["language"],
        "default_branch": data["default_branch"]
    }


def filter_repository_files(tree: list):

    selected_files = []

    total_size = 0

    for file in tree:

        # Only process actual files

        if file.get("type") != "blob":
            continue

        path = file["path"]

        file_path = PurePosixPath(path)

        file_name = file_path.name

        extension = file_path.suffix.lower()

        # Exclude unwanted folders

        if any(
            directory in IGNORED_DIRECTORIES
            for directory in file_path.parts
        ):
            continue

        # Exclude sensitive and unnecessary files

        if file_name in IGNORED_FILES:
            continue

        # Check allowed extensions

        if extension not in ALLOWED_EXTENSIONS:
            continue

        # Check file size

        file_size = file.get("size")

        if file_size is None:
            continue

        if file_size > MAX_FILE_SIZE:
            continue

        # Check maximum number of files

        if len(selected_files) >= MAX_FILES:
            break

        # Check total ingestion size

        if total_size + file_size > MAX_TOTAL_SIZE:
            continue

        selected_files.append({
            "path": path,
            "sha": file["sha"],
            "size": file_size,
            "url": file.get("url")
        })

        total_size += file_size

    return selected_files


async def fetch_github_tree(owner: str, repo: str):

    repo_data = await fetch_github_repo(owner, repo)

    branch = repo_data["default_branch"]

    encoded_branch = quote(branch, safe="")

    url = (
        f"https://api.github.com/repos/{owner}/{repo}"
        f"/git/trees/{encoded_branch}?recursive=1"
    )

    async with httpx.AsyncClient(
        timeout=20.0,
        follow_redirects=True
    ) as client:

        try:
            response = await client.get(
                url,
                headers={
                    "Accept": "application/vnd.github+json"
                }
            )

        except httpx.RequestError:

            raise HTTPException(
                status_code=502,
                detail="Unable to fetch GitHub repository tree"
            )

    if response.status_code == 404:
        raise HTTPException(
            status_code=404,
            detail="GitHub repository tree not found"
        )

    if response.status_code != 200:
        raise HTTPException(
            status_code=502,
            detail="GitHub tree API request failed"
        )

    data = response.json()

    tree = data.get("tree", [])

    selected_files = filter_repository_files(tree)

    total_files = sum(
        1 for file in tree
        if file.get("type") == "blob"
    )

    return {
        "repository": repo_data["full_name"],
        "default_branch": branch,
        "truncated": data["truncated"],
        "total_files": total_files,
        "included_files": len(selected_files),
        "skipped_files": total_files - len(selected_files),
        "total_size": sum(
            file["size"] for file in selected_files
        ),
        "files": selected_files
    }
